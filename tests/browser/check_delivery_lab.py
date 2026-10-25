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
import subprocess
from pathlib import Path
import tempfile
import threading

import jsonschema
from playwright.sync_api import sync_playwright, expect
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "SKILLS/spritesheet-expert"
spec = importlib.util.spec_from_file_location("delivery_fixtures", ROOT / "tests/unit/test_item_delivery.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def check_prepared_commands(page, temporary, screenshots):
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    schemas = SKILL / 'references/schemas'
    registry = json.loads((SKILL / 'studio/workflows.json').read_text())
    jsonschema.validate(registry, json.loads((schemas / 'studio-workflow-v1.schema.json').read_text()))
    handoff_schema = json.loads((schemas / 'studio-session-v1.schema.json').read_text())
    page.locator('[data-output-mode="json"]').click()
    for workflow in registry['workflows']:
        page.locator('#workflow-select').select_option(workflow['id'])
        job = json.loads(page.locator('#workflow-output').input_value())
        errors = list(jsonschema.Draft202012Validator(handoff_schema).iter_errors(job))
        assert not errors, (workflow['id'], [error.message for error in errors[0].context])
        assert (job['argv'] is None) == workflow['requiresProvider']
    page.locator('#workflow-select').select_option('build-deterministic-item-atlas')
    source = 'assets/á 雪 \' " ‘ ’ ‚ ‛ $(1+1) `echo UNEXPECTED` ; & | > < %PATH% ! *.png'
    output = 'build/quoted folder\\'
    page.get_by_label('Source image · required', exact=True).fill(source)
    page.get_by_label('Output directory · required', exact=True).fill(output)
    job = json.loads(page.locator('#workflow-output').input_value())
    expected = ['python', 'scripts/build_deterministic_item_atlas.py', source,
                '--output-dir', output, '--provenance', 'imported', '--alpha-high', '64',
                '--alpha-low', '2', '--halo-radius', '6', '--grid-quantum', '32',
                '--padding', '16', '--max-width', '4096']
    assert job['argv'] == expected
    probe = temporary / 'command quoting'
    (probe / 'scripts').mkdir(parents=True)
    (probe / expected[1]).write_text('import json, sys\nprint(json.dumps(sys.argv[1:]))\n')
    shells = {'powershell': shutil.which('pwsh'), 'posix': shutil.which('sh')}
    assert shells['powershell' if os.name == 'nt' else 'posix'], 'Native shell is required for the quoting regression'
    for shell, executable in shells.items():
        page.get_by_label('Command shell', exact=True).select_option(shell)
        current = json.loads(page.locator('#workflow-output').input_value())
        assert current['jobId'] == job['jobId'] and current['argv'] == expected
        assert current['commandShell'] == shell
        page.locator('[data-output-mode="command"]').click()
        command = page.locator('#workflow-output').input_value()
        assert command == current['command']
        page.get_by_role('button', name='Copy output', exact=True).click()
        expect(page.locator('#output-feedback')).to_have_text('Copied.')
        clipboard = page.evaluate('navigator.clipboard.readText()')
        assert clipboard.replace('\r\n', '\n') == command
        with page.expect_download() as downloaded:
            page.get_by_role('button', name='Download', exact=True).click()
        downloaded.value.save_as(probe / 'download.txt')
        assert (probe / 'download.txt').read_text(encoding='utf-8') == command
        if executable:
            script = probe / ('command.ps1' if shell == 'powershell' else 'command.sh')
            script.write_text(clipboard, encoding='utf-8', newline='\n')
            flags = ['-NoProfile', '-NonInteractive', '-File'] if shell == 'powershell' else []
            result = subprocess.run([executable, *flags, str(script)], cwd=probe, capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
            assert json.loads(result.stdout) == expected[2:], result.stdout
            multiline = [*expected, '', 'first line\nsecond line\t雪', "'\"\\"]
            rendered = page.evaluate("async ({argv, shell}) => (await import('./commands.js')).renderCommand(argv, shell)", {'argv': multiline, 'shell': shell})
            page.evaluate('text => navigator.clipboard.writeText(text)', rendered)
            copied_multiline = page.evaluate('navigator.clipboard.readText()')
            script.write_text(copied_multiline, encoding='utf-8', newline='\n')
            result = subprocess.run([executable, *flags, str(script)], cwd=probe, capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
            assert json.loads(result.stdout) == multiline[2:], result.stdout
            print(f'PASS: {shell} receives exact prepared arguments, including quotes, Unicode, shell syntax, empty strings and LF newlines')
        page.locator('[data-output-mode="json"]').click()
    page.get_by_label('Command shell', exact=True).select_option('powershell')
    page.locator('[data-output-mode="command"]').click()
    page.screenshot(path=str(screenshots / 'prepared-command-quoting.png'), full_page=True)
    page.locator('[data-output-mode="json"]').click()
    for field, value in [('source', ''), ('source', '   '), ('alphaHigh', ''), ('alphaHigh', '256'), ('alphaHigh', '1.5')]:
        page.locator(f'#workflow-field-{field}').fill(value)
        expect(page.locator('#workflow-output')).to_have_value('')
        for button in ['copy-output', 'download-output', 'queue-output']:
            expect(page.locator(f'#{button}')).to_be_disabled()
        page.get_by_role('button', name='Reset', exact=True).click()
    expect(page.locator('#queue-output')).to_be_enabled()
    page.get_by_label('Source image · required', exact=True).fill(source)
    page.get_by_label('Output directory · required', exact=True).fill(output)
    print('PASS: invalid prepared jobs cannot be copied, downloaded or queued')


def check_workspace(browser, temporary, source, screenshots):
    from serve_item_studio import Studio, Handler
    studio = Studio(temporary / "initial workspace", temporary / "no-models.json")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, studio=studio))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    base = f"http://127.0.0.1:{server.server_port}"
    project = temporary / "art project"
    try:
        page.goto(base + "/#workspaces")
        expect(page.locator("#workspace-name")).to_have_text("initial workspace")
        page.get_by_text("Create, open or import work", exact=True).click()
        page.locator("#workspace-create-name").fill("QA project")
        page.locator("#workspace-create-path").fill(str(project))
        page.get_by_role("button", name="Create and open", exact=True).click()
        expect(page.locator("#workspace-name")).to_have_text("QA project")
        page.locator('[data-view="launcher"]').click()
        check_prepared_commands(page, temporary, screenshots)
        page.locator("#workflow-select").select_option("build-deterministic-item-atlas")
        page.locator('[data-output-mode="json"]').click()
        job = json.loads(page.locator("#workflow-output").input_value())
        page.locator('[data-output-mode="prompt"]').click()
        page.locator('[data-output-mode="json"]').click()
        assert json.loads(page.locator("#workflow-output").input_value())["jobId"] == job["jobId"]
        page.locator("#queue-output").click()
        expect(page.locator("#output-feedback")).to_contain_text("Saved")
        page.locator('[data-view="queue"]').click()
        expect(page.locator("#queue-count")).to_have_text("1 job")
        page.reload()
        expect(page.locator(".queue-id")).to_have_text(job["jobId"])
        page.locator('[data-view="process"]').click()
        page.locator("#local-source").set_input_files(source)
        page.locator("#local-collection").fill("Synthetic test pixels")
        page.locator("#local-job").select_option(job["jobId"])
        page.locator("#local-models").select_option("none")
        page.locator("#local-start").click()
        expect(page.locator("#local-items .local-card")).to_have_count(1, timeout=60000)
        expect(page.locator("#local-export")).to_be_disabled()
        page.locator("#local-items input").check()
        expect(page.locator("#local-crop-pair")).to_be_visible()
        page.screenshot(path=str(screenshots / "workspace-review.png"), full_page=True)
        page.locator("#local-approve").click()
        expect(page.locator("#local-export")).to_be_enabled()
        with page.expect_download() as downloaded:
            page.locator("#local-export").click()
        download = downloaded.value
        download.save_as(temporary / "download.zip")
        run_id = page.locator("#local-runs").input_value()
        saved = studio.store.catalog()["exports"][0]
        assert (temporary / "download.zip").read_bytes() == studio.store.export_file(saved["id"])[0].read_bytes()
        assert studio.store.metadata(run_id)["jobId"] == job["jobId"]
        page.locator('[data-view="workspaces"]').click()
        card = page.locator(f'[data-run-id="{run_id}"]')
        expect(card).to_contain_text("1 sprites · 0 awaiting review")
        expect(page.locator("#workspace-exports a")).to_have_count(1)
        card.get_by_text("Name and collection", exact=True).click()
        card.get_by_label("Run name", exact=True).fill("Reviewed fixture")
        card.get_by_label("Collection", exact=True).fill("Approved test fixtures")
        card.get_by_role("button", name="Save", exact=True).click()
        expect(card.get_by_role("heading")).to_have_text("Reviewed fixture")
        page.locator("#workspace-collection").select_option("Approved test fixtures")
        expect(card).to_be_visible()
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(screenshots / "workspace-catalog.png"), full_page=True)
        card.get_by_role("button", name="Archive", exact=True).click()
        expect(card).to_have_count(0)
        page.locator("#workspace-archived").check()
        expect(card).to_be_visible()
        card.get_by_role("button", name="Restore", exact=True).click()
        expect(card.get_by_role("button", name="Archive", exact=True)).to_be_visible()
        previous = page.request.get(base + "/api/session").json()
        page.get_by_text("Create, open or import work", exact=True).click()
        page.locator("#workspace-create-name").fill("Separate project")
        page.locator("#workspace-create-path").fill(str(temporary / "separate project"))
        page.get_by_role("button", name="Create and open", exact=True).click()
        expect(page.locator("#workspace-name")).to_have_text("Separate project")
        expect(page.locator("#workspace-runs article")).to_have_count(0)
        stale = page.request.post(base + "/api/handoffs", headers={"X-Studio-Token": previous["token"], "X-Workspace-Id": previous["workspace"]["id"]},
                                  data={"kind": "archive", "jobIds": [job["jobId"]]})
        assert stale.status == 403
        page.locator('[data-view="queue"]').click()
        expect(page.locator("#queue-count")).to_have_text("0 jobs")
        page.locator('[data-view="workspaces"]').click()
        page.get_by_text("Create, open or import work", exact=True).click()
        page.locator("#workspace-open-path").fill(str(project))
        page.get_by_role("button", name="Open workspace", exact=True).click()
        expect(page.locator("#workspace-name")).to_have_text("QA project")
        expect(page.locator(f'[data-run-id="{run_id}"]')).to_contain_text("Reviewed fixture")
        page.locator('[data-view="queue"]').click()
        expect(page.locator("#queue-count")).to_have_text("1 job")
        page.get_by_role("button", name="Archive queue", exact=True).click()
        expect(page.locator("#queue-count")).to_have_text("0 jobs")
        assert studio.store.handoffs()[0]["archived"] is True
        # Copy a non-temporal row lane; snapshots must not appear as deliveries.
        from unpack_atlas_run import import_pngs
        static_run = temporary / 'static-source'; static_run.mkdir()
        import_pngs(static_run, [source], 'items', ['token'], source_type='fixture')
        (static_run / 'qa').mkdir(); shutil.copyfile(source, static_run / 'qa/preview.png')
        page.locator('[data-view="workspaces"]').click()
        page.locator('#workspace-collection').select_option('')
        summary = page.get_by_text('Create, open or import work', exact=True)
        if not summary.evaluate('(node) => node.parentElement.open'):
            summary.click()
        page.locator('#workspace-adopt-path').fill(str(static_run))
        page.locator('#workspace-adopt-name').fill('Static test')
        page.locator('#workspace-adopt-lane').select_option('true-grid')
        page.get_by_role('button', name='Copy into workspace', exact=True).click()
        card = page.locator('.workspace-run').filter(has=page.get_by_role('heading', name='Static test', exact=True))
        expect(card).to_contain_text('true-grid')
        card.get_by_text('Inspect saved evidence', exact=True).click()
        card.get_by_role('combobox', name='Evidence for Static test').select_option('qa/preview.png')
        expect(card.frame_locator('iframe').locator('img')).to_be_visible()
        card.get_by_role('button', name='Save snapshot ZIP', exact=True).click()
        expect(page.get_by_role('link', name='Static test · Snapshot', exact=True)).to_be_visible()
        page.screenshot(path=str(screenshots / 'workspace-lanes.png'), full_page=True)
        assert not errors, errors
        print("PASS: workspace creation/switch/isolation, persisted stable jobs, linked alpha run, unflagged review, saved export, collections, archive/restore; no browser errors")
    finally:
        page.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
                # Directory inputs require a directory, not the empty file-list API.
                # Switch roots to exercise stale-view clearing as well as hash rejection.
                corrupted = Path(temporary) / "corrupted"
                shutil.copytree(root, corrupted)
                (corrupted / "atlas.png").write_bytes(b"not the pinned atlas")
                page.locator("#folder").set_input_files(corrupted)
                page.wait_for_function("document.getElementById('status').textContent.includes('BLOCKED')")
                assert not page.locator("#canvas").is_visible()
                check_pages_and_review_identity(page, Path(temporary), f"http://127.0.0.1:{server.server_port}", screenshots)
                assert not errors, errors
                check_workspace(browser, Path(temporary), root / "source.png", screenshots)
                browser.close()
                print("PASS: exact file identities, four views, zoom/background, matching receipt, stale receipt, corrupted atlas; no browser errors")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def check_pages_and_review_identity(page, temporary, base, screenshots):
    from spritecore.item_sheet import build_item_atlas, PackingConfig
    source = temporary / "page-source.png"
    sheet = Image.new('RGBA', (150, 50))
    for index, color in enumerate(((200, 40, 30, 255), (30, 180, 80, 255), (60, 100, 220, 255))):
        ImageDraw.Draw(sheet).rectangle((5 + index*50, 5, 37 + index*50, 35), fill=color)
    sheet.save(source)
    root = temporary / "multi-page"
    manifest = build_item_atlas(source, root, provenance='fixture', packing=PackingConfig(max_width=64, max_height=64, quantum=16, padding=8))
    assert len(manifest['pages']) == 3
    page.locator('#folder').set_input_files(root)
    expect(page.locator('#items button')).to_have_count(3)
    page.locator('[data-view="atlas"]').click()
    page.locator('#overlay').select_option('off')
    for index, item in enumerate(manifest['items']):
        page.locator('#items button').nth(index).click()
        expect(page.locator('#item-info')).to_contain_text(item['geometry']['pageId'])
        x, y, _, _ = item['geometry']['frame']
        actual = page.locator('#canvas').evaluate('(canvas, point) => [...canvas.getContext("2d").getImageData(...point, 1, 1).data]', [x+1, y+1])
        with Image.open(root / item['artifacts']['rgba']) as crop:
            assert actual == list(crop.getpixel((1, 1)))
    page.screenshot(path=str(screenshots / 'multi-page.png'), full_page=True)
    page.goto(base + '/#atlas')
    page.locator('#manifest-input').set_input_files(root / 'manifest.json')
    page.locator('#run-folder-input').set_input_files(root)
    expect(page.locator('#export-review')).to_be_enabled()
    cards = page.locator('#item-grid .item-card')
    cards.nth(0).click()
    original_target = page.locator('#inspector-item-id').inner_text()
    page.evaluate('''() => {
        const digest = crypto.subtle.digest.bind(crypto.subtle);
        crypto.subtle.digest = (...args) => new Promise(resolve => {
            window.releaseReviewDigest = () => { crypto.subtle.digest = digest; resolve(digest(...args)); };
        });
    }''')
    page.locator('#replacement-input').set_input_files(source)
    page.wait_for_function('typeof window.releaseReviewDigest === "function"')
    cards.nth(1).click()
    page.evaluate('window.releaseReviewDigest()')
    expect(page.locator('#replacement-preview')).to_be_hidden()
    cards.nth(0).click()
    expect(page.locator('#replacement-preview')).to_be_visible()
    expect(page.locator('#inspector-item-id')).to_have_text(original_target)
    with page.expect_download() as downloaded:
        page.locator('#export-review').click()
    review_path = temporary / 'race-review.json'; downloaded.value.save_as(review_path)
    review = json.loads(review_path.read_text())
    assert [item['itemId'] for item in review['items'] if item.get('replacement')] == [original_target]
    page.screenshot(path=str(screenshots / 'review-target.png'), full_page=True)
    # A same-named file in another folder must not satisfy the exact crop path.
    wrong = temporary / 'wrong-relative'; shutil.copytree(root, wrong)
    manifest['items'][0]['artifacts']['rgba'] = 'missing/' + Path(manifest['items'][0]['artifacts']['rgba']).name
    (wrong / 'manifest.json').write_text(json.dumps(manifest))
    page.locator('#manifest-input').set_input_files(wrong / 'manifest.json')
    page.locator('#run-folder-input').set_input_files(wrong)
    expect(page.locator('#review-feedback')).to_contain_text('Missing exact artifact')
    expect(page.locator('#export-review')).to_be_disabled()
    print('PASS: three atlas pages render their own native pixels; delayed replacement stays on its original item; basename collision blocks review')


if __name__ == "__main__":
    main()
