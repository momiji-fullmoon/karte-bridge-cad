"""Publish audited SolidCraft USA outputs as an offline, dependency-free 3D site."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def public_metadata(value):
    if isinstance(value, dict):
        return {key: public_metadata(item) for key, item in value.items() if key != "mcp_journal"}
    if isinstance(value, list):
        return [public_metadata(item) for item in value]
    if isinstance(value, str) and value.startswith("/Users/"):
        return Path(value).name
    return value


def category(role):
    if role in {"deck", "graded_deck"}:
        return "deck"
    if role in {"bearing_block", "central_pier", "arch_pier", "approach_column", "bridge_house"}:
        return "supports"
    if any(word in role for word in ("diagonal", "counterbrace", "lateral", "crossbeam")):
        return "bracing"
    return "girders"


COLORS = {"deck": [0.71, 0.69, 0.65], "supports": [0.61, 0.64, 0.66],
          "bracing": [0.65, 0.75, 0.82], "girders": [0.25, 0.46, 0.61]}


def read_3mf(path):
    """Read core 3MF mesh/component instances without an optional XML dependency."""
    with zipfile.ZipFile(path) as archive:
        models = [name for name in archive.namelist() if name.endswith(".model")]
        if len(models) != 1:
            raise ValueError("Expected one core 3MF model part")
        root = ET.fromstring(archive.read(models[0]))
    namespace = {"m": root.tag.split("}")[0][1:]}
    objects = {item.attrib["id"]: item for item in root.findall("m:resources/m:object", namespace)}
    scale = {"micron": 0.001, "millimeter": 1, "centimeter": 10, "inch": 25.4,
             "foot": 304.8, "meter": 1000}[root.attrib.get("unit", "millimeter")]
    meshes = []

    def matrix(element):
        values = element.attrib.get("transform")
        transform = np.eye(4)
        if values:
            transform[:3, :] = np.array([float(value) for value in values.split()]).reshape(4, 3).T
        return transform

    def instance(object_id, transform, ancestors=()):
        if object_id in ancestors:
            raise ValueError("Cyclic 3MF component reference")
        item = objects[object_id]
        mesh_element = item.find("m:mesh", namespace)
        if mesh_element is not None:
            vertices = [[float(vertex.attrib[axis]) for axis in ("x", "y", "z")]
                        for vertex in mesh_element.findall("m:vertices/m:vertex", namespace)]
            faces = [[int(triangle.attrib[axis]) for axis in ("v1", "v2", "v3")]
                     for triangle in mesh_element.findall("m:triangles/m:triangle", namespace)]
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            mesh.apply_transform(transform)
            mesh.apply_scale(scale)
            meshes.append((f"{object_id}_{len(meshes)}", mesh))
        else:
            components = item.findall("m:components/m:component", namespace)
            if not components:
                raise ValueError(f"3MF object {object_id} has neither mesh nor components")
            for component in components:
                instance(component.attrib["objectid"], transform @ matrix(component), (*ancestors, object_id))

    for item in root.findall("m:build/m:item", namespace):
        instance(item.attrib["objectid"], matrix(item))
    return meshes


def make_meshes(directory, case, plan):
    """Bind actual exported meshes to native members by measured bounds/volume."""
    meshes = read_3mf(directory / f"{case['case_id']}.3mf")
    remaining = {body["name"]: body for body in case["native"]["bodies"]}
    members = {member["name"]: member for member in plan["graph_members"]}
    parts, glb_scene = [], trimesh.Scene()
    maximum_bbox_error = maximum_volume_error = 0.0
    total_faces = 0
    for node, mesh in meshes:
        mesh.process(validate=True)
        if mesh.volume < 0:
            mesh.invert()
        if not mesh.is_watertight or not np.isfinite(mesh.vertices).all():
            raise ValueError(f"Exported 3MF mesh is not a finite closed solid: {node}")
        candidates = []
        for name, body in remaining.items():
            bounds = np.array([body["bbox"]["min"], body["bbox"]["max"]])
            bbox_error = float(np.max(np.abs(mesh.bounds-bounds)))
            volume_error = abs(mesh.volume/body["volume_mm3"]-1)
            if bbox_error <= 0.1 and volume_error <= 1e-4:
                candidates.append((bbox_error, volume_error, name))
        if not candidates:
            raise ValueError(f"No measured native member matches exported 3MF object {node}")
        bbox_error, volume_error, name = min(candidates)
        remaining.pop(name)
        member = members[name]
        group = category(member["role"])
        mesh.apply_scale(0.001)  # Web viewer is m / Z-up; source exports are mm.
        flat_vertices = mesh.vertices[mesh.faces].reshape(-1, 3)
        flat_normals = np.repeat(mesh.face_normals, 3, axis=0)
        parts.append({"name": name, "category": group, "color": COLORS[group],
                      "assembly": member["assembly"],
                      "evidence": f"{member['role']} · {member['representation']}",
                      "assumption": f"寸法区分: {member['dimension_status']}。断面・接合詳細は概略形状。",
                      "vertices": np.round(flat_vertices, 6).ravel().tolist(),
                      "normals": np.round(flat_normals, 6).ravel().tolist(),
                      "indices": np.arange(len(flat_vertices)).tolist()})
        mesh.visual.vertex_colors = np.array([*[round(c*255) for c in COLORS[group]], 255], dtype=np.uint8)
        glb_scene.add_geometry(mesh, node_name=name, geom_name=name)
        maximum_bbox_error = max(maximum_bbox_error, bbox_error)
        maximum_volume_error = max(maximum_volume_error, volume_error)
        total_faces += len(mesh.faces)
    if remaining or len(parts) != case["native"]["body_count"]:
        raise ValueError("Exported mesh/native member count mismatch")
    bounds = glb_scene.bounds.tolist()
    glb_scene.apply_transform(trimesh.transformations.rotation_matrix(-math.pi/2, [1, 0, 0]))
    glb_scene.export(directory / "bridge.glb")
    reloaded = trimesh.load(directory / "bridge.glb", force="scene")
    reloaded.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2, [1, 0, 0]))
    if len(reloaded.geometry) != len(parts) or not np.allclose(reloaded.bounds, bounds, rtol=0, atol=1e-5):
        raise ValueError("GLB round-trip member count or coordinate frame mismatch")
    return parts, bounds, {"mesh_source": "audited native 3MF export", "member_count": len(parts),
                           "triangle_count": total_faces, "all_meshes_watertight": True,
                           "max_native_bbox_error_mm": maximum_bbox_error,
                           "max_native_member_volume_relative_error": maximum_volume_error,
                           "glb_round_trip_passed": True, "viewer_units": "m", "viewer_up_axis": "Z",
                           "glb_units": "m", "glb_up_axis": "Y"}


def build(source, destination):
    source, destination = Path(source), Path(destination)
    results = json.loads((source / "results.json").read_text())
    audit = json.loads((source / "audit.json").read_text())
    readings = json.loads((source / "reviewed_readings.json").read_text())
    inventory = json.loads((source / "inventory.json").read_text())
    cases = {case["id"]: case for case in readings["cases"]}
    if not audit["passed"] or results["failures"] or len(results["cases"]) != 15:
        raise ValueError("Expected a successfully audited 15-case generation run")
    if digest(source / "reviewed_readings.json") != results["readings_sha256"]:
        raise ValueError("Reviewed readings snapshot changed")
    destination.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).with_name("usa_viewer.html").read_text()
    cards, published = [], []
    for case in results["cases"]:
        key = case["case_id"]
        original = source / "models" / key
        target = destination / "models" / key
        target.mkdir(parents=True, exist_ok=True)
        plan = json.loads((original / "source_spec.json").read_text())
        for name, artifact in plan["artifacts"].items():
            path = original / name
            if digest(path) != artifact["sha256"] or path.stat().st_size != artifact["bytes"]:
                raise ValueError(f"Source artifact changed: {key}/{name}")
            shutil.copy2(path, target / name)
        main = cases[key]
        primary_hash = plan["sources"][0]["sha256"]
        page = next(page for page in inventory["pages"]
                    if page["source_sha256"] == primary_hash and page["page"] == main["main_page"])
        shutil.copy2(source / page["image"], target / "source_page.png")
        public_plan = public_metadata(plan)
        public_plan["publication"] = {"source_page": "source_page.png", "source_sha256": primary_hash,
                                       "source_page_number": main["main_page"],
                                       "note": "Source file paths are filenames; original PDFs/TIFFs are not bundled. MCP journal omitted."}
        public_case = public_metadata(case)
        public_case["artifacts_directory"] = "."
        write_json(target / "source_spec.json", public_plan)
        write_json(target / "validation.json", public_case)
        parts, bounds, validation = make_meshes(target, case, plan)
        write_json(target / "web_mesh_validation.json", validation)
        unscaled = not case["real_world_scale_known"]
        classification = "未縮尺・正規化確認モデル" if unscaled else "図面寸法に基づく概略モデル"
        dimensions = case["dimensions_mm"]
        size_text = ("100000mm基準に正規化（実寸ではありません）" if unscaled else
                     f"主橋長 {dimensions['main_length']/1000:.3f}m / 幅 {dimensions['width']/1000:.3f}m（採用寸法）")
        assumptions = [{"field": "source_note", "value": note, "reason": "図面読取り時の注記"} for note in case["notes"]]
        assumptions += [{"field": name, "value": value["value_mm"], "reason": value["method"]}
                        for name, value in plan["dimension_sources"].items()]
        data = {"id": key, "bounds": bounds, "parts": parts, "assumptions": assumptions}
        downloads = " · ".join(f'<a href="{key}.{ext}" download>{label}</a>' for ext, label in
                                (("solidcraft", "SolidCraft"), ("step", "STEP"), ("stl", "STL"), ("3mf", "3MF")))
        downloads += ' · <a href="bridge.glb" download>GLB</a>'
        motion = ('<p><a href="motion_15deg.png">15°可動径間の検証画像</a></p>'
                  if case["family"] in {"bascule", "swing_truss"} else "")
        replacements = {"__TITLE__": html.escape(case["name"]), "__CLASS__": classification,
                        "__DIMENSIONS__": size_text, "__ID__": key, "__DOWNLOADS__": downloads,
                        "__NOTICE__": ("未縮尺モデルです。表示・ダウンロード数値は実橋の絶対寸法ではありません。" if unscaled else
                                       "原図寸法と読取りに基づく概略CADです。断面・支承・基礎等には仮定と簡略化があります。"),
                        "__MOTION__": motion, "__ASSUMPTION_COUNT__": str(len(assumptions)),
                        "__MODEL__": json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")}
        page_html = template
        for marker, value in replacements.items():
            page_html = page_html.replace(marker, value)
        (target / "viewer.html").write_text(page_html, encoding="utf-8")
        files = {path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
                 for path in sorted(target.iterdir()) if path.is_file() and path.name != "files.json"}
        write_json(target / "files.json", files)
        published.append({"id": key, "name": case["name"], "family": case["family"], "unscaled": unscaled,
                          "member_count": len(parts), "viewer": f"models/{key}/viewer.html",
                          "web_mesh_validation": validation, "source_files": public_plan["sources"]})
        cards.append(f'<article data-name="{html.escape(key+" "+case["name"]+" "+case["family"])}">'
                     f'<a href="models/{key}/viewer.html"><img src="models/{key}/iso.png" loading="lazy" alt="{html.escape(case["name"])}">'
                     f'<h2>{html.escape(case["name"])}</h2></a><p class="badge {"unscaled" if unscaled else ""}">{classification}</p>'
                     f'<p>{size_text}</p><p>{len(parts)}部材 · {case["family"]}</p>'
                     f'<p><a href="models/{key}/viewer.html">3Dを開く</a> · <a href="models/{key}/{key}.solidcraft" download>SolidCraft</a>'
                     f' · <a href="models/{key}/{key}.step" download>STEP</a> · <a href="models/{key}/source_spec.json">寸法・根拠</a></p></article>')
        print(f"{key}: {len(parts)} parts, mesh/GLB validation passed", flush=True)
    write_json(destination / "manifest.json", {"schema": "usa.web_publication/1", "cases": published,
               "case_count": len(published), "metric_conceptual_models": 11, "unscaled_review_models": 4,
               "source_readings_sha256": results["readings_sha256"],
               "scope": "Conceptual source-linked models; four cases unscaled; no independently measured recognition/quantity accuracy"})
    write_json(destination / "source_audit.json", audit)
    shutil.copy2(source / "reviewed_readings.json", destination / "reviewed_readings.json")
    catalog = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>USA橋梁 3D CAD | カルテ橋梁三次元CAD</title><style>
*{box-sizing:border-box}body{margin:0;background:#0c1725;color:#e2edf7;font:15px system-ui;padding:28px}a{color:#8ed2ff}header{max-width:1200px;margin:auto}h1{font-size:30px}p{line-height:1.7;color:#b7c9db}.badge{display:inline-block;background:#214458;border-radius:5px;padding:5px 9px}.unscaled{background:#62461c;color:#ffdb95}input{width:100%;padding:13px;margin:15px 0 25px;background:#1a2c40;color:white;border:1px solid #46657f;border-radius:6px;font:inherit}#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:20px;max-width:1400px;margin:auto}article{background:#152639;border:1px solid #31455d;border-radius:10px;padding:15px}img{width:100%;aspect-ratio:3/2;object-fit:contain;background:#dfe7ef;border-radius:6px}h2{font-size:18px}article a{text-decoration:none}nav{margin-bottom:18px}
</style><header><nav><a href="../index.html">← 国内カルテ106橋</a> · <a href="README.md">作成方法・精度と前提</a> · <a href="manifest.json">公開モデル一覧</a></nav>
<span class="badge">SOURCE DRAWINGS → EDITABLE SOLIDCRAFT CAD</span><h1>USA橋梁 3D CAD</h1>
<p>米国の歴史的橋梁図面から再構成した15橋。ブラウザ内で回転・拡大・部材選択でき、編集可能なSolidCraftとSTEPもダウンロードできます。</p>
<p><strong>11橋は図面寸法に基づく概略モデル、Chicagoの4橋は未縮尺の正規化モデルです。</strong>欠落寸法・断面・接合詳細等の仮定は各橋の根拠データに記録しています。</p>
<p>15橋すべてでネイティブ再読込・編集・独立STEP検証を実施。5橋で15°可動径間の目標位置を検証。<a href="source_audit.json">元成果物の監査結果</a></p>
<label for="search">橋梁名・ID・形式で検索（表示 <strong id="count">15</strong>橋）</label><input id="search" type="search" placeholder="例: Judsonia / camelback / Chicago"></header><main id="grid">'''
    catalog += "\n".join(cards)+'''</main><script>
const cards=[...document.querySelectorAll('article')];document.getElementById('search').addEventListener('input',event=>{const q=event.target.value.toLowerCase();let n=0;for(const card of cards){const visible=card.dataset.name.toLowerCase().includes(q);card.hidden=!visible;if(visible)n++;}document.getElementById('count').textContent=n;});
</script></html>'''
    (destination / "index.html").write_text(catalog, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Audited drawing2cad output root")
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1] / "usa")
    args = parser.parse_args()
    build(args.source, args.destination)
