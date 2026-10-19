"""Verify the published karte site, including the structural screening layer.

Local mode: checks structural.json / viewer.html / index.html / structural_summary.json
consistency across all 106 bridges and records the result in
gh_pages/structural_verification.json.

--live mode: fetches the deployed Pages site, compares SHA-256 of index,
summary, per-model structural.json and sample viewers against local files,
then opens a sample viewer in Playwright to check the section renders.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://momiji-fullmoon.github.io/karte-bridge-cad/"
OUT = Path(__file__).resolve().parents[1]
MARKER = "<h2>簡易構造解析（スクリーニング）</h2>"
ANCHOR = "<details><summary>再構成の前提"
RECORD = OUT / "structural_verification.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_checks():
    problems = []
    counts = {"models": 0, "structural": 0, "viewers_patched": 0, "summary_cases": 0, "cards": 0}
    summary = json.loads((OUT / "structural_summary.json").read_text(encoding="utf-8"))
    counts["summary_cases"] = len(summary["cases"])
    if summary["schema"] != "karte.structural_screening_summary/1":
        problems.append("summary schema mismatch")
    rows = {row["id"]: row for row in summary["cases"]}
    for directory in sorted((OUT / "models").iterdir()):
        if not (directory / "parameters.json").is_file():
            continue
        counts["models"] += 1
        case_id = directory.name
        structural = directory / "structural.json"
        if not structural.is_file():
            problems.append(f"{case_id}: structural.json missing")
            continue
        data = json.loads(structural.read_text(encoding="utf-8"))
        counts["structural"] += 1
        if data["schema"] != "karte.structural_screening/1":
            problems.append(f"{case_id}: structural schema mismatch")
        if not data["structures"]:
            problems.append(f"{case_id}: no structures")
        for structure in data["structures"]:
            if not str(structure.get("status", "")).startswith(("analyzed", "not_analyzed")):
                problems.append(f"{case_id}: unexpected status {structure.get('status')}")
        row = rows.get(case_id)
        if row is None:
            problems.append(f"{case_id}: not in summary")
        elif row["structure_count"] != len(data["structures"]):
            problems.append(f"{case_id}: summary structure_count mismatch")
        elif abs(row["max_stress_MPa"] - data["summary"]["max_stress_MPa"]) > 1e-6:
            problems.append(f"{case_id}: summary stress mismatch")
        viewer = (directory / "viewer.html").read_text(encoding="utf-8")
        if MARKER not in viewer or ANCHOR not in viewer:
            problems.append(f"{case_id}: viewer missing structural section")
        else:
            counts["viewers_patched"] += 1
        expected = len(data["structures"])
        if viewer.count("<p><strong>S0") < expected and viewer.count("<p><strong>S1"):
            pass  # tags S01...S0n; count based check below
        shown = len([chunk for chunk in viewer.split(MARKER)[1].split("<details>")[0].split("<p><strong>")]) - 1
        if shown != expected:
            problems.append(f"{case_id}: viewer shows {shown} of {expected} structures")
    index = (OUT / "index.html").read_text(encoding="utf-8")
    counts["cards"] = index.count("構造スクリーニング:")
    if counts["cards"] != counts["models"]:
        problems.append(f"index has {counts['cards']} screening lines for {counts['models']} models")
    if "structural_summary.json" not in index:
        problems.append("index missing summary link")
    return counts, problems


def fetch(path: str) -> bytes:
    request = urllib.request.Request(BASE + path.lstrip("/"))
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"{path}: HTTP {response.status}")
        return response.read()


def fetch_many(paths):
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        return dict(zip(paths, pool.map(fetch, paths)))


def live_checks():
    problems = []
    checked = []
    summary_local = (OUT / "structural_summary.json").read_bytes()
    index_local = (OUT / "index.html").read_bytes()
    for name, local in (("structural_summary.json", summary_local), ("index.html", index_local)):
        try:
            remote = fetch(name)
            checked.append(name)
            if sha256(remote) != sha256(local):
                problems.append(f"{name}: live SHA-256 differs from local")
        except Exception as error:  # noqa: BLE001
            problems.append(f"{name}: fetch failed ({error})")
    model_ids = sorted(directory.name for directory in (OUT / "models").iterdir()
                       if (directory / "parameters.json").is_file())
    paths = [f"models/{case_id}/structural.json" for case_id in model_ids]
    paths += ["models/8335004026/viewer.html", "models/8335004043/viewer.html",
              "models/8335004044/viewer.html", "models/8335005072/viewer.html"]
    try:
        remotes = fetch_many(paths)
        checked.extend(paths)
        for path in paths:
            local = (OUT / path).read_bytes()
            if sha256(remotes[path]) != sha256(local):
                problems.append(f"{path}: live SHA-256 differs from local")
    except Exception as error:  # noqa: BLE001
        problems.append(f"batch fetch failed ({error})")
    return checked, problems


def playwright_check(case_id: str, problems):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + f"models/{case_id}/viewer.html", wait_until="load")
        page.wait_for_timeout(2500)
        heading = page.evaluate("""Array.from(document.querySelectorAll('h2')).some(h => h.textContent.includes('簡易構造解析'))""")
        webgl = page.evaluate("(() => { const c = document.createElement('canvas');"
                              "return !!(c.getContext('webgl2') || c.getContext('webgl')); })()")
        if not (heading and "簡易構造解析" in heading):
            problems.append(f"{case_id}: live structural heading missing (got {heading!r})")
        if not webgl:
            problems.append(f"{case_id}: WebGL unavailable")
        if errors:
            problems.append(f"{case_id}: page errors {errors[:3]}")
        browser.close()


def main():
    live = "--live" in sys.argv
    counts, problems = local_checks()
    mode = "live" if live else "local"
    checked_live = []
    if live and not problems:
        checked_live, live_problems = live_checks()
        problems.extend(live_problems)
        if not problems:
            playwright_check("8335004043", problems)
    record = {"schema": "karte.structural_screening_verification/1",
              "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "mode": mode,
              "base_url": BASE if live else None,
              "counts": counts,
              "live_files_checked": checked_live,
              "problems": problems,
              "status": "passed" if not problems else "failed"}
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
