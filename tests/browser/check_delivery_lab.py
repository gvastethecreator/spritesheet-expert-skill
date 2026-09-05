"""Explicit browser smoke: requires Playwright and its Chromium installation.

Run from the repository root: python tests/browser/check_delivery_lab.py
Uses synthetic test pixels only. Does not invoke image providers or game engines.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
import shutil
from pathlib import Path
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "SKILLS/spritesheet-expert"
spec = importlib.util.spec_from_file_location("delivery_fixtures", ROOT / "tests/unit/test_item_delivery.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root, _ = module.bundle.__wrapped__(Path(temporary))
        report = module.validate_delivery(root / "manifest.json")
        (root / "qa/delivery-check.json").write_text(json.dumps(report), encoding="utf-8")
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(SKILL / "studio")))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get("CHROMIUM_EXECUTABLE") or shutil.which("chromium"))
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/delivery-lab.html")
                page.locator("#folder").set_input_files(root)
                page.wait_for_function("document.getElementById('status').textContent.includes('file references verified')")
                assert page.locator("#items button").count() == 1
                for view in ("source", "placement", "atlas"):
                    page.locator(f'[data-view="{view}"]').click()
                    assert page.locator("#canvas").is_visible()
                page.locator("#zoom").select_option("4")
                page.locator("#background").select_option("white")
                page.locator('[data-view="delivery"]').click()
                page.wait_for_function("document.getElementById('check-output').textContent.includes('manifestAndRecordedArtifactsMatch')")
                assert '"engineSmokeTested": false' in page.locator("#check-output").inner_text()
                page.locator('[data-view="placement"]').click()
                page.locator("#zoom").select_option("1")
                page.locator("#background").select_option("checker")
                screenshots = ROOT / ".scratch/delivery-browser"
                screenshots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshots / "placement.png"), full_page=True)
                stale = dict(report, manifestSha256="0" * 64)
                receipt = Path(temporary) / "stale.json"
                receipt.write_text(json.dumps(stale), encoding="utf-8")
                page.locator("#receipt").set_input_files(receipt)
                page.wait_for_function("document.getElementById('check-output').textContent.includes('REJECTED')")
                (root / "atlas.png").write_bytes(b"not the pinned atlas")
                page.locator("#folder").set_input_files([])
                page.locator("#folder").set_input_files(root)
                page.wait_for_function("document.getElementById('status').textContent.includes('BLOCKED')")
                assert not page.locator("#canvas").is_visible()
                assert not errors, errors
                browser.close()
                print("PASS: exact file identities, four views, zoom/background, matching receipt, stale receipt, corrupted atlas; no browser errors")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
