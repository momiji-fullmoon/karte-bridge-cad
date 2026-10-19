"""Inject the structural screening section into the published karte viewer pages and index.

Reads structural.json written by karte_structural_screening.py, rewrites each
gh_pages/models/<id>/viewer.html (idempotent) and gh_pages/index.html cards.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from karte_structural_screening import structure_values

OUT = Path(__file__).resolve().parents[1]
MARKER = "<h2>簡易構造解析（スクリーニング）</h2>"
ANCHOR = "<details><summary>再構成の前提"
CAVEAT = ("<small>包絡断面・EI一定の連続梁、または2面プラットトラスによる簡易スクリーニング。"
          "合成効果・PC鋼材緊張力・局部断面・座屈・疲労は評価していません。"
          "活荷重は床版全面5kPaの簡易値（TL-20の設計照査ではありません）。"
          ' <a href="structural.json">解析詳細 (JSON)</a> · '
          '<a href="../../structural_summary.json">106橋のサマリ</a></small>')


def structural_html(struct):
    pieces = [MARKER]
    for structure in struct["structures"]:
        tag = structure["tag"]
        spans = structure.get("spans_m")
        if spans is None:
            length = f"{structure['span_m']:g} m"
        else:
            length = " + ".join(f"{span:g}" for span in spans) + " m"
        count = structure.get("girder_count")
        suffix = f"（主桁{count}本）" if count else ""
        text = structure_values(structure)["text"]
        line = f"<p><strong>{tag} {html.escape(structure['form'])}{suffix} ({length})</strong>"
        if text:
            line += f"<br>{html.escape(text)}"
        line += "</p>"
        pieces.append(line)
    pieces.append(f"<p>{CAVEAT}</p>")
    return "".join(pieces)


def patch_viewer(directory):
    path = directory / "viewer.html"
    page = path.read_text(encoding="utf-8")
    if MARKER in page:
        return False
    struct = json.loads((directory / "structural.json").read_text(encoding="utf-8"))
    index = page.index(ANCHOR)
    path.write_text(page[:index] + structural_html(struct) + page[index:], encoding="utf-8")
    return True


def main():
    summary_path = OUT / "structural_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in summary["cases"]}
    updated_pages, updated_cards = 0, 0
    for directory in sorted((OUT / "models").iterdir()):
        if not (directory / "parameters.json").is_file():
            continue
        if not (directory / "structural.json").is_file():
            raise ValueError(f"structural.json missing for {directory.name}; run karte_structural_screening.py first")
        if patch_viewer(directory):
            updated_pages += 1
    index_path = OUT / "index.html"
    index = index_path.read_text(encoding="utf-8")
    for case_id, row in rows.items():
        marker = f'models/{case_id}/viewer.html'
        position = index.index(marker)
        end = index.index("</article>", position)
        if "構造スクリーニング:" in index[position:end]:
            continue
        parts = []
        stress = row["max_stress_MPa"]
        ratio = row["min_deflection_ratio"]
        if stress is not None:
            parts.append(f"最大σ {stress:,.0f} MPa")
        if ratio is not None:
            parts.append(f"たわみ目安 約1/{ratio:,.0f}")
        parts.append(f"{row['structure_count']}構造")
        snippet = f'<p><small>構造スクリーニング: {" · ".join(parts)}</small></p>'
        index = index[:end] + snippet + index[end:]
        updated_cards += 1
    reference = ' · <a href="structural_summary.json">簡易構造スクリーニング一覧</a>'
    if "structural_summary.json" not in index:
        index = index.replace('<a href="manifest.json">出力一覧</a>', '<a href="manifest.json">出力一覧</a>' + reference)
    index_path.write_text(index, encoding="utf-8")
    print(f"viewers updated: {updated_pages}, cards updated: {updated_cards}")


if __name__ == "__main__":
    sys.exit(main())
