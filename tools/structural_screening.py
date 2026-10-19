"""Screening-level structural analysis of published USA conceptual CAD models.

Each truss plane (y<0 / y>0 in the published graph) is idealized as a planar
pin-jointed truss in the elevation (x-z) plane and carries half of the deck
line load. Sections are the published rectangular envelopes; loads are
self-weight from envelope volumes plus a uniform 5 kPa live load. The
open-spandrel concrete arch is idealized the same way (ribs, spandrel columns
and piers as bar elements). Results are screening indicators with stated
assumptions, not design verification; transverse (lateral/bracing) systems and
moment connections are outside this idealization.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "usa"

STEEL_E, STEEL_RHO = 200e9, 7850.0
CONCRETE_E, CONCRETE_RHO = 25e9, 2400.0
LIVE_PA = 5000.0
G = 9.80665
PLANE_Y_MIN = 1.0

IN_PLANE_ROLES = {"upper_chord", "lower_chord", "vertical", "diagonal", "counterbrace",
                  "approach_girder", "arch_rib", "spandrel_column", "arch_pier"}
LOAD_ROLES = {"floor_beam", "graded_deck"}
CONCRETE_ROLES = {"arch_rib", "spandrel_column", "arch_pier", "approach_column",
                  "graded_deck", "deck", "arch_wall", "bearing_block"}

ASSUMPTIONS = {
    "idealization": "トラス面（y<0 / y>0）ごとの面内ピン接合トラス。各面が床版線荷重の半分を負担",
    "excluded": "横構・ブレーシング・縦桁の面外効果と節点モーメント（ガセット剛性）は対象外",
    "steel_elastic_modulus_GPa": STEEL_E / 1e9,
    "steel_density_kg_m3": STEEL_RHO,
    "concrete_elastic_modulus_GPa": CONCRETE_E / 1e9,
    "concrete_density_kg_m3": CONCRETE_RHO,
    "live_load_kPa": LIVE_PA / 1000.0,
    "sections": "矩形包絡断面 A=幅×梁成（実断面ではない。軸力・応力は目安）",
    "self_weight": "包絡体積×材料密度。縦桁自重は床版死荷重に含める",
    "deck_material": "コンクリート換算 24 kN/m3（実床版構成の確定ではない）",
}


def material(role):
    if role in CONCRETE_ROLES:
        return "concrete", CONCRETE_E, CONCRETE_RHO
    return "steel", STEEL_E, STEEL_RHO


def bodies_by_role(spec, validation):
    members = {member["name"]: member for member in spec["graph_members"]}
    result = {}
    for body in validation["native"]["bodies"]:
        role = members.get(body["name"], {}).get("role", "")
        result.setdefault(role, []).append(body)
    return result


def plane_elements(spec):
    """Return per-plane (y-sign) lists of 2D bar elements from the graph."""
    planes = {-1: [], 1: []}
    skipped = {}
    for member in spec["graph_members"]:
        role = member["role"]
        if role not in IN_PLANE_ROLES or "p0_mm" not in member:
            continue
        p0 = np.array(member["p0_mm"], dtype=float) / 1000.0
        p1 = np.array(member["p1_mm"], dtype=float) / 1000.0
        if abs(p0[1] - p1[1]) > 0.05 or abs(p0[1]) < PLANE_Y_MIN:
            skipped[role] = skipped.get(role, 0) + 1
            continue
        sign = 1 if p0[1] > 0 else -1
        planes[sign].append({"name": member["name"], "role": role, "p0": p0[[0, 2]],
                             "p1": p1[[0, 2]],
                             "A_m2": member["width_mm"] * member["depth_mm"] * 1e-6})
    return planes, skipped


def build_plane(elements_raw):
    nodes, index = [], {}

    def node_id(point_xz):
        key = (round(float(point_xz[0]), 4), round(float(point_xz[1]), 4))
        if key not in index:
            index[key] = len(nodes)
            nodes.append(np.array(key, dtype=float))
        return index[key]

    elements = []
    for raw in elements_raw:
        length = float(np.linalg.norm(raw["p1"] - raw["p0"]))
        if length <= 1e-9:
            continue
        _, modulus, rho = material(raw["role"])
        elements.append({"name": raw["name"], "role": raw["role"],
                         "i": node_id(raw["p0"]), "j": node_id(raw["p1"]),
                         "A_m2": raw["A_m2"], "E_Pa": modulus, "rho": rho, "L_m": length})
    return nodes, elements


def attach_supports(nodes, elements, validation, spec, warnings):
    """Attach bearings per connected component so multi-level models stay stable."""
    parent = list(range(len(nodes)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in elements:
        parent[find(e["i"])] = find(e["j"])
    component_of = [find(i) for i in range(len(nodes))]
    roles = bodies_by_role(spec, validation)
    points = []
    for body in roles.get("bearing_block", []):
        low = np.array(body["bbox"]["min"], dtype=float) / 1000.0
        high = np.array(body["bbox"]["max"], dtype=float) / 1000.0
        points.append((low + high) / 2.0)
    pivot = None
    for body in roles.get("central_pier", []):
        low = np.array(body["bbox"]["min"], dtype=float) / 1000.0
        high = np.array(body["bbox"]["max"], dtype=float) / 1000.0
        center = (low + high) / 2.0
        pivot = np.array([center[0], center[1], high[2]])
    constrained = []
    groups = {}
    for point in points:
        matched = [node for node, xy in enumerate(nodes) if abs(float(xy[0]) - float(point[0])) <= 2.5]
        if not matched:
            warnings.append(f"bearing at x={point[0]:.2f}m matched no plane node within 2.5m")
            continue
        for node in matched:
            constrained.append((node, "bearing"))
        groups.setdefault(round(float(point[0]), 2), set()).update(matched)
    pivot_nodes = []
    if pivot is not None:
        matched = [node for node, xy in enumerate(nodes)
                   if abs(float(xy[0]) - float(pivot[0])) <= 2.5 and xy[1] <= pivot[2] + 2.5]
        if matched:
            pivot_nodes = matched
            for node in matched:
                constrained.append((node, "central_pier"))
            groups.setdefault(round(float(pivot[0]), 2), set()).update(matched)
        else:
            warnings.append("central pivot matched no plane node within 2.5m")
    supported_components = {component_of[node] for node, _ in constrained}
    dropped = [node for node in range(len(nodes)) if component_of[node] not in supported_components]
    if dropped:
        dropped_components = {component_of[node] for node in dropped}
        warnings.append(f"{len(dropped_components)} unsupported component(s) with {len(dropped)} nodes excluded "
                        "(no bearing matched); their members are not part of the screening results")
    keep = [e for e in elements if component_of[e["i"]] in supported_components
            and component_of[e["j"]] in supported_components]
    return constrained, groups, pivot_nodes, keep, component_of, supported_components


def deck_load_line(spec, validation):
    roles = bodies_by_role(spec, validation)
    decks = roles.get("deck", []) + roles.get("graded_deck", [])
    if not decks:
        return None
    volume = sum(body["volume_mm3"] for body in decks) * 1e-9
    low = np.min(np.array([body["bbox"]["min"] for body in decks]), axis=0) / 1000.0
    high = np.max(np.array([body["bbox"]["max"] for body in decks]), axis=0) / 1000.0
    length, width = float(high[0] - low[0]), float(high[1] - low[1])
    if length <= 0 or width <= 0 or volume <= 0:
        return None
    stringer_mass = sum(body["volume_mm3"] for body in roles.get("stringer", [])) * 1e-9 * STEEL_RHO
    dead = volume * CONCRETE_RHO * G + stringer_mass * G
    area = length * width
    live = area * LIVE_PA
    return {"dead_N": dead, "live_N": live, "line_N_per_m": (dead + live) / length,
            "length_m": length, "width_m": width,
            "equivalent_thickness_m": volume / area,
            "z_low_m": float(low[2]), "z_high_m": float(high[2]),
            "stringer_mass_kg": stringer_mass}


def deck_load_positions(spec):
    positions = set()
    for member in spec["graph_members"]:
        if member["role"] in LOAD_ROLES and "p0_mm" in member:
            positions.add(round(member["p0_mm"][0] / 1000.0, 3))
            positions.add(round(member["p1_mm"][0] / 1000.0, 3))
    return sorted(positions)


def plane_loads(nodes, load_x, deck, warnings):
    """Half of the deck line load per plane, attached to nodes near the deck level."""
    node_loads = {}
    if deck is None or not load_x:
        if deck is not None:
            warnings.append("no floor beams / deck segments in the graph; deck loads not applied")
        return node_loads
    z_center = (deck["z_low_m"] + deck["z_high_m"]) / 2.0
    for position in load_x:
        left = max((x for x in load_x if x < position), default=position)
        right = min((x for x in load_x if x > position), default=position)
        tributary = ((position - left) + (right - position)) / 2.0
        load = deck["line_N_per_m"] / 2.0 * tributary
        best, best_score = None, float("inf")
        for node, xy in enumerate(nodes):
            z_penalty = 5.0 * max(0.0, abs(float(xy[1]) - z_center) - 1.5)
            score = abs(xy[0] - position) + z_penalty
            if score < best_score:
                best, best_score = node, score
        if best is not None:
            node_loads[best] = node_loads.get(best, 0.0) + load
    return node_loads


def solve_plane(nodes, elements, constrained, node_loads, component_of):
    count = len(nodes)
    anchors = {}
    for node, kind in constrained:
        component = component_of[node]
        x = float(nodes[node][0])
        if component not in anchors or x < anchors[component]:
            anchors[component] = x
    fixed = set()
    for node, kind in constrained:
        fixed.add(2 * node + 1)
        if abs(float(nodes[node][0]) - anchors[component_of[node]]) < 1e-6:
            fixed.add(2 * node)
    fixed_dofs = sorted(fixed)
    free_dofs = np.array([dof for dof in range(2 * count) if dof not in fixed], dtype=int)

    stiffness = np.zeros((2 * count, 2 * count))
    for e in elements:
        direction = nodes[e["j"]] - nodes[e["i"]]
        axial = e["E_Pa"] * e["A_m2"] / e["L_m"]
        unit = direction / e["L_m"]
        projection = axial * np.outer(unit, unit)
        dofs = [2 * e["i"], 2 * e["i"] + 1, 2 * e["j"], 2 * e["j"] + 1]
        for a in range(4):
            for b in range(4):
                sign = 1.0 if (a // 2) == (b // 2) else -1.0
                stiffness[dofs[a], dofs[b]] += sign * projection[a % 2, b % 2]

    forces = np.zeros(2 * count)
    for node, load in node_loads.items():
        forces[2 * node + 1] -= load
    for e in elements:
        weight = e["A_m2"] * e["L_m"] * e["rho"] * G
        forces[2 * e["i"] + 1] -= weight / 2.0
        forces[2 * e["j"] + 1] -= weight / 2.0

    displacement = np.zeros(2 * count)
    displacement[free_dofs] = np.linalg.solve(stiffness[np.ix_(free_dofs, free_dofs)], forces[free_dofs])
    reactions = stiffness @ displacement - forces
    return displacement, reactions


def member_forces(nodes, elements, displacement):
    results = []
    for e in elements:
        direction = nodes[e["j"]] - nodes[e["i"]]
        unit = direction / e["L_m"]
        delta = displacement[2 * e["j"]:2 * e["j"] + 2] - displacement[2 * e["i"]:2 * e["i"] + 2]
        force = e["E_Pa"] * e["A_m2"] / e["L_m"] * float(unit @ delta)
        results.append({"name": e["name"], "role": e["role"], "N_N": force,
                        "sigma_MPa": force / (e["A_m2"] * 1e6)})
    return results


def analyze_plane(spec, validation, sign, deck, warnings):
    planes, skipped = plane_elements(spec)
    elements_raw = planes.get(sign, [])
    if len(elements_raw) < 4:
        return None
    nodes, elements = build_plane(elements_raw)
    constrained, groups, pivot_nodes, elements, component_of, supported = attach_supports(
        nodes, elements, validation, spec, warnings)
    if len(groups) < 2:
        return {"status": "failed", "reason": "支点を面内節点に接続できなかった"}
    node_loads = plane_loads(nodes, deck_load_positions(spec), deck, warnings)
    dropped_loads = sum(load for node, load in node_loads.items() if component_of[node] not in supported)
    node_loads = {node: load for node, load in node_loads.items() if component_of[node] in supported}
    if dropped_loads > 0.0:
        warnings.append(f"{dropped_loads / 1000.0:.1f} kN of deck load fell on unsupported components and is not carried")
    displacement, reactions = solve_plane(nodes, elements, constrained, node_loads, component_of)
    member_results = member_forces(nodes, elements, displacement)

    keep_nodes = {node for e in elements for node in (e["i"], e["j"])}
    support_nodes = {node for node, _ in constrained}
    deflection_node, deflection = None, 0.0
    for node, xy in enumerate(nodes):
        if node in support_nodes or node not in keep_nodes:
            continue
        if -displacement[2 * node + 1] > deflection:
            deflection_node, deflection = node, -displacement[2 * node + 1]

    merged_groups = {}
    for x in sorted(groups):
        key = frozenset(groups[x])
        if merged_groups.get(key) != x:
            merged_groups.setdefault(key, x)
    support_x = sorted(merged_groups.values())
    spans = [b - a for a, b in zip(support_x, support_x[1:])]
    main_span = max(spans) if spans else (deck["length_m"] if deck else None)
    counted = set()
    reaction_rows, reaction_total = [], 0.0
    for x in support_x:
        nodes_here = sorted(groups[x] - counted)
        counted.update(nodes_here)
        vertical = sum(reactions[2 * node + 1] for node in nodes_here)
        reaction_rows.append({"x_m": x, "vertical_kN": vertical / 1000.0})
        reaction_total += vertical
    for node in pivot_nodes:
        if node in counted:
            continue
        counted.add(node)
        vertical = reactions[2 * node + 1]
        reaction_rows.append({"x_m": round(float(nodes[node][0]), 2), "vertical_kN": vertical / 1000.0,
                              "kind": "central_pier"})
        reaction_total += vertical
    applied = sum(node_loads.values()) + sum(e["A_m2"] * e["L_m"] * e["rho"] * G for e in elements)
    residual = abs(reaction_total - applied) / max(applied, 1.0)

    tension = sorted(member_results, key=lambda row: -row["N_N"])
    compression = sorted(member_results, key=lambda row: row["N_N"])
    steel_mass = sum(e["A_m2"] * e["L_m"] * e["rho"] for e in elements if e["rho"] == STEEL_RHO)
    concrete_mass = sum(e["A_m2"] * e["L_m"] * e["rho"] for e in elements if e["rho"] == CONCRETE_RHO)

    def brief(row):
        return {"member": row["name"], "kN": abs(row["N_N"]) / 1000.0, "MPa": abs(row["sigma_MPa"])}

    return {"status": "analyzed_plane_truss",
            "plane_y_sign": sign,
            "model": {"nodes": len(nodes), "elements": len(elements),
                      "restrained_nodes": len({node for node, _ in constrained}),
                      "roles": sorted({e["role"] for e in elements})},
            "supports": [{"x_m": x, "vertical_kN": round(row["vertical_kN"], 1)}
                         for x, row in zip(support_x, reaction_rows)],
            "central_pier_reactions": [row for row in reaction_rows if row.get("kind") == "central_pier"],
            "main_span_m": main_span,
            "max_tension": brief(tension[0]) if tension else None,
            "max_compression": brief(compression[0]) if compression else None,
            "max_deflection_mm": deflection * 1000.0 if deflection_node is not None else None,
            "deflection_ratio": (main_span / deflection) if main_span and deflection > 0 else None,
            "masses_kg": {"steel": steel_mass, "concrete": concrete_mass},
            "checks": {"vertical_reaction_residual_relative": residual,
                       "applied_vertical_N": applied},
            "top_tension": [brief(row) for row in tension[:5]],
            "top_compression": [brief(row) for row in compression[:5]],
            "member_count": len(member_results)}, elements, nodes, member_results, displacement


def analyze_articulated(spec, validation):
    warnings = []
    deck = deck_load_line(spec, validation)
    planes, skipped = plane_elements(spec)
    usable = [sign for sign in (-1, 1) if len(planes.get(sign, [])) >= 4]
    if not usable:
        return None
    plane_results = []
    for sign in usable:
        outcome = analyze_plane(spec, validation, sign, deck, warnings)
        if outcome is None:
            continue
        result, *_ = outcome
        plane_results.append(result)
    if not plane_results:
        return {"status": "failed", "reason": "トラス面を構成できなかった", "warnings": warnings}

    best = max(plane_results, key=lambda r: (r["max_tension"] or {"kN": 0})["kN"])
    per_plane = [{"plane_y_sign": r["plane_y_sign"], "status": r["status"],
                  "main_span_m": r["main_span_m"],
                  "max_tension": r["max_tension"], "max_compression": r["max_compression"],
                  "max_deflection_mm": r["max_deflection_mm"],
                  "deflection_ratio": r["deflection_ratio"],
                  "checks": r["checks"]} for r in plane_results]
    masses = {"steel": sum(r["masses_kg"]["steel"] for r in plane_results)}
    if any(r["masses_kg"].get("concrete") for r in plane_results):
        masses["concrete"] = sum(r["masses_kg"].get("concrete", 0.0) for r in plane_results)
    if deck is not None:
        masses["deck_concrete"] = deck["dead_N"] / (CONCRETE_RHO * G)
    return {"status": "analyzed_plane_truss",
            "idealization": "2 plane trusses analyzed independently; each carries half the deck line load",
            "model": {"planes": len(plane_results), "skipped_out_of_plane_roles": skipped},
            "loads": {} if deck is None else {
                "deck_dead_N": deck["dead_N"], "deck_live_N": deck["live_N"],
                "deck_length_m": deck["length_m"], "deck_width_m": deck["width_m"],
                "deck_equivalent_thickness_m": deck["equivalent_thickness_m"],
                "stringer_mass_kg": deck.get("stringer_mass_kg")},
            "main_span_m": best["main_span_m"],
            "max_tension": best["max_tension"], "max_compression": best["max_compression"],
            "max_deflection_mm": best["max_deflection_mm"],
            "deflection_ratio": best["deflection_ratio"],
            "supports": best["supports"],
            "central_pier_reactions": best["central_pier_reactions"],
            "masses_kg": masses,
            "per_plane": per_plane,
            "top_tension": best["top_tension"], "top_compression": best["top_compression"],
            "warnings": warnings}


def analyze_deck_bending(spec, validation):
    roles = bodies_by_role(spec, validation)
    decks = roles.get("deck", [])
    walls = roles.get("arch_wall", [])
    if not decks:
        return None
    deck = decks[0]
    low = np.array(deck["bbox"]["min"], dtype=float) / 1000.0
    high = np.array(deck["bbox"]["max"], dtype=float) / 1000.0
    length, width = float(high[0] - low[0]), float(high[1] - low[1])
    thickness = deck["volume_mm3"] * 1e-9 / (length * width)
    covered = sorted((w["bbox"]["min"][0] / 1000.0, w["bbox"]["max"][0] / 1000.0) for w in walls)
    merged = []
    for start, end in covered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    spans, cursor = [], low[0]
    for start, end in merged:
        if start > cursor + 0.5:
            spans.append((cursor, min(start, high[0])))
        cursor = max(cursor, end)
    if cursor < high[0] - 0.5:
        spans.append((cursor, high[0]))
    rows = []
    for start, end in spans:
        span = end - start
        if span <= 0.5:
            continue
        line_load = (CONCRETE_RHO * G * thickness + LIVE_PA) * width
        moment = line_load * span ** 2 / 8.0
        inertia = width * thickness ** 3 / 12.0
        section_modulus = width * thickness ** 2 / 6.0
        deflection = 5.0 * line_load * span ** 4 / (384.0 * CONCRETE_E * inertia)
        rows.append({"span_m": span, "moment_kNm": moment / 1000.0,
                     "shear_kN": line_load * span / 2.0 / 1000.0,
                     "bending_stress_MPa": moment / section_modulus / 1e6,
                     "deflection_mm": deflection * 1000.0,
                     "deflection_ratio": span / deflection if deflection > 0 else None})
    masses = {"deck_concrete": deck["volume_mm3"] * 1e-9 * CONCRETE_RHO,
              "arch_walls_concrete": sum(w["volume_mm3"] for w in walls) * 1e-9 * CONCRETE_RHO}
    if not rows:
        return {"status": "not_analyzed_structure_type",
                "reason": "閉鎖スペンドル（アーチ壁が全長を覆う）のため床版の明確な支間が取れない。骨組理想化は不適。質量集計のみ提供",
                "deck": {"length_m": length, "width_m": width, "thickness_m": thickness},
                "masses_kg": masses}
    return {"status": "analyzed_deck_bending",
            "deck": {"length_m": length, "width_m": width, "thickness_m": thickness,
                     "inertia_m4": width * thickness ** 3 / 12.0},
            "clear_spans": rows, "masses_kg": masses}


def masses_from_validation(spec, validation):
    steel = sum(body["volume_mm3"] for body in validation["native"]["bodies"]
                if "steel" in (body.get("material") or "").lower()) * 1e-9 * STEEL_RHO
    concrete = sum(body["volume_mm3"] for body in validation["native"]["bodies"]
                   if "concrete" in (body.get("material") or "").lower()) * 1e-9 * CONCRETE_RHO
    return {"steel": steel, "concrete": concrete}


def analyze_case(directory):
    spec = json.loads((directory / "source_spec.json").read_text(encoding="utf-8"))
    validation = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
    base = {"schema": "usa.structural_screening/1", "case_id": spec["id"], "name": spec["name"],
            "family": spec["family"], "scaled": spec["real_world_scale_known"],
            "assumptions": ASSUMPTIONS}
    if not spec["real_world_scale_known"]:
        return {**base, "status": "not_analyzed_unscaled",
                "reason": "未縮尺・正規化モデルのため実寸法に基づく構造計算は意味を持たない"}
    result = analyze_articulated(spec, validation)
    if result is None:
        result = analyze_deck_bending(spec, validation)
    if result is None:
        result = {"status": "not_analyzed_structure_type",
                  "reason": "主要部材が部材端点を持たない概念ソリッドのため面トラス理想化を構成できない。質量集計のみ提供",
                  "masses_kg": masses_from_validation(spec, validation)}
    if result["status"] == "analyzed_deck_bending" and result.get("clear_spans"):
        worst = max(result["clear_spans"], key=lambda row: row["span_m"])
        result["main_span_m"] = worst["span_m"]
        result["max_deflection_mm"] = worst["deflection_mm"]
        result["deflection_ratio"] = worst["deflection_ratio"]
    return {**base, **result}


def main():
    rows = []
    for directory in sorted((OUT / "models").iterdir()):
        if not (directory / "source_spec.json").is_file():
            continue
        result = analyze_case(directory)
        (directory / "structural.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        summary = {key: result.get(key) for key in ("status", "main_span_m", "max_tension",
                                                    "max_compression", "max_deflection_mm", "deflection_ratio")}
        print(f"{result['case_id']}: {json.dumps(summary, ensure_ascii=False)}", flush=True)
        rows.append({"id": result["case_id"], "name": result["name"], "family": result["family"],
                     "status": result["status"], "scaled": result["scaled"],
                     "main_span_m": result.get("main_span_m"),
                     "max_tension": result.get("max_tension"),
                     "max_compression": result.get("max_compression"),
                     "max_deflection_mm": result.get("max_deflection_mm"),
                     "deflection_ratio": result.get("deflection_ratio")})
    (OUT / "structural_summary.json").write_text(
        json.dumps({"schema": "usa.structural_screening_summary/1", "cases": rows,
                    "method": "トラス面ごとの面内ピン接合理想化（各面が床版線荷重の半分）。仮定は各structural.jsonのassumptions参照",
                    "scope": "Screening indicators with stated assumptions; not design verification"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cases: {len(rows)}")


if __name__ == "__main__":
    main()