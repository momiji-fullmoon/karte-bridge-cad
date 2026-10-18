"""Verify public files, model binding, relative links and real WebGL interactions."""
from __future__ import annotations

import argparse
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit

import numpy as np

from build_usa_site import digest, write_json


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.model, self.in_model = [], "", False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.links += [attrs[key] for key in ("src", "href") if key in attrs]
        if tag == "script" and attrs.get("id") == "model":
            self.in_model = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_model = False

    def handle_data(self, text):
        if self.in_model:
            self.model += text


def verify(root):
    output = root / "usa"
    manifest = json.loads((output / "manifest.json").read_text())
    cases = manifest["cases"]
    assert len(cases) == 15 and len({case["id"] for case in cases}) == 15
    assert sum(case["unscaled"] for case in cases) == 4
    checked_files, checked_links, total_parts = 0, 0, 0
    for case in cases:
        directory = output / "models" / case["id"]
        files = json.loads((directory / "files.json").read_text())
        assert set(files) == {path.name for path in directory.iterdir() if path.is_file() and path.name != "files.json"}
        for name, evidence in files.items():
            path = directory / name
            assert path.stat().st_size == evidence["bytes"] and digest(path) == evidence["sha256"], path
            assert evidence["bytes"] < 100*1024*1024, path
            checked_files += 1
        page = Page((directory / "viewer.html").read_text())
        data = json.loads(page.model)
        spec = json.loads((directory / "source_spec.json").read_text())
        native = json.loads((directory / "validation.json").read_text())["native"]
        native_by_name = {body["name"]: body for body in native["bodies"]}
        assert {part["name"] for part in data["parts"]} == {part["name"] for part in spec["graph_members"]}
        assert len(data["parts"]) == native["body_count"] == case["member_count"]
        for part in data["parts"]:
            points = np.array(part["vertices"]).reshape(-1, 3)
            normals = np.array(part["normals"]).reshape(-1, 3)
            assert points.shape == normals.shape and np.isfinite(points).all() and np.isfinite(normals).all()
            assert len(part["indices"]) % 3 == 0 and max(part["indices"]) < len(points)
            body = native_by_name[part["name"]]
            expected = np.array([body["bbox"]["min"], body["bbox"]["max"]])*0.001
            # 3MF stores float32 coordinates at ~100m extents; allow 0.01mm,
            # including the viewer's rounding to six decimal places in metres.
            assert np.allclose([points.min(axis=0), points.max(axis=0)], expected, rtol=0, atol=1e-5), part["name"]
        total_parts += len(data["parts"])
    pages = [output / "index.html", *sorted((output / "models").glob("*/viewer.html"))]
    for path in pages:
        text = path.read_text()
        assert "/Users/" not in text and "__MODEL__" not in text
        for link in Page(text).links:
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path:
                continue
            destination = (path.parent / unquote(url.path)).resolve()
            assert destination.is_relative_to(root.resolve()) and destination.is_file(), (path, link)
            checked_links += 1
    for path in output.rglob("*.json"):
        assert "/Users/" not in path.read_text(), path
    assert 'href="usa/index.html"' in (root / "index.html").read_text()
    assert total_parts == 2132
    sizes = [path.stat().st_size for path in output.rglob("*") if path.is_file()]
    report = {"passed": True, "case_count": len(cases), "source_scaled_models": 11, "unscaled_models": 4,
              "hashed_case_files_checked": checked_files, "relative_links_checked": checked_links,
              "native_matched_parts": total_parts, "maximum_file_bytes": max(sizes), "total_publication_bytes": sum(sizes),
              "scope": "Public artifact integrity, native/web member correspondence and working local links; not deployment confirmation"}
    write_json(output / "publication_validation.json", report)
    print(json.dumps(report, indent=2))
    return cases


def browser_verify(root, cases):
    from playwright.sync_api import sync_playwright

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    screenshots = root / "usa" / "browser_screenshots"
    screenshots.mkdir(exist_ok=True)
    errors, missing, external = [], [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", lambda response: missing.append(response.url) if response.status >= 400 else None)
            page.on("request", lambda request: external.append(request.url)
                    if request.url.startswith("http") and not request.url.startswith(base) else None)
            page.goto(base+"/index.html")
            assert page.locator("article").count() == 106
            page.locator('a[href="usa/index.html"]').click()
            assert page.locator("article").count() == 15
            page.locator("#search").fill("Chicago")
            assert page.locator("article:visible").count() == 4
            assert page.locator("#count").inner_text() == "4"
            page.locator("#search").fill("")
            assert page.locator("article:visible").count() == 15
            assert page.locator("#grid img").evaluate_all("""async images => {
                images.forEach(image => image.loading='eager');
                await Promise.all(images.map(image => image.decode()));
                return images.every(image => image.naturalWidth>0);
            }""")
            page.screenshot(path=str(screenshots / "gallery_desktop.png"), full_page=True)
            checked = []
            for case in cases:
                page.goto(base+"/usa/"+case["viewer"])
                page.wait_for_function("typeof buffers !== 'undefined' && buffers.length > 0")
                state = page.evaluate("""() => {
                    draw();const pixels=new Uint8Array(canvas.width*canvas.height*4);
                    gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
                    let foreground=0;for(let i=0;i<pixels.length;i+=4){if(Math.abs(pixels[i]-12)>2||Math.abs(pixels[i+1]-21)>2||Math.abs(pixels[i+2]-33)>2)foreground++;}
                    return {count:data.parts.length,error:gl.getError(),foreground};
                }""")
                assert state["count"] == case["member_count"] and state["error"] == 0 and state["foreground"] > 100, (case, state)
                assert page.locator("#parts option").count() == case["member_count"]+1
                if case["id"] in {"AR-51_Judsonia", "CT-0629_Nineveh_Falls", "Chicago_Columbus_Drive"}:
                    page.screenshot(path=str(screenshots / f"{case['id']}.png"))
                checked.append(case["id"])
            page.goto(base+"/usa/models/AR-51_Judsonia/viewer.html")
            canvas = page.locator("#canvas")
            initial = canvas.screenshot()
            page.get_by_role("button", name="側面", exact=True).click()
            assert canvas.screenshot() != initial
            page.get_by_role("button", name="全体", exact=True).click()
            initial = canvas.screenshot()
            page.locator("#groups input").first.uncheck()
            assert canvas.screenshot() != initial
            page.locator("#groups input").first.check()
            page.locator("#parts").select_option("0")
            assert page.locator("#detail").inner_text()
            page.locator("#parts").select_option("-1")
            initial = canvas.screenshot()
            page.get_by_role("button", name="分解表示", exact=True).click()
            assert canvas.screenshot() != initial
            page.get_by_role("button", name="分解表示", exact=True).click()
            box = canvas.bounding_box()
            x, y = box["x"]+box["width"]*0.5, box["y"]+box["height"]*0.5
            initial = canvas.screenshot()
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x+90, y+40, steps=8)
            page.mouse.up()
            assert canvas.screenshot() != initial
            initial = canvas.screenshot()
            page.keyboard.down("Shift")
            page.mouse.down()
            page.mouse.move(x+130, y+70, steps=6)
            page.mouse.up()
            page.keyboard.up("Shift")
            assert canvas.screenshot() != initial
            initial = canvas.screenshot()
            page.mouse.wheel(0, -180)
            page.wait_for_timeout(150)
            assert canvas.screenshot() != initial
            with page.expect_download() as captured:
                page.get_by_role("button", name="画像保存", exact=True).click()
            assert Path(captured.value.path()).read_bytes().startswith(b"\x89PNG")
            with page.expect_download() as downloaded:
                page.locator('a[href="AR-51_Judsonia.solidcraft"]').click()
            assert digest(downloaded.value.path()) == digest(root / "usa/models/AR-51_Judsonia/AR-51_Judsonia.solidcraft")
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(base+"/usa/index.html")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#grid img").evaluate_all("""async images => {
                images.forEach(image => image.loading='eager');
                await Promise.all(images.map(image => image.decode()));
            }""")
            page.screenshot(path=str(screenshots / "gallery_mobile.png"), full_page=True)
            page.goto((root / "usa/models/AR-81_DeGray/viewer.html").as_uri())
            page.wait_for_function("typeof buffers !== 'undefined' && buffers.length === 46")
            assert page.evaluate("gl.getError()") == 0
            browser.close()
        assert not errors and not missing and not external, (errors, missing, external)
        result = {"passed": True, "browser": "Google Chrome / WebGL2 SwiftShader", "cases_checked": checked,
                  "javascript_errors": errors, "failed_responses": missing, "external_requests": external,
                  "checks": ["existing 106 domestic cards", "USA search", "all 15 preview images", "all 15 real WebGL models", "nonempty rendered pixels",
                             "view controls", "part visibility", "part selection", "explode", "rotation", "pan", "zoom",
                             "PNG capture", "native CAD download hash", "mobile layout", "offline file viewer"]}
        write_json(root / "usa/browser_verification.json", result)
        print("Browser verification: passed for all 15 models and interactions")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    models = verify(args.root)
    if args.browser:
        browser_verify(args.root, models)
