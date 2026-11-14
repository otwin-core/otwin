"""The static site's wiring, tested natively. No network, no browser.

The bundle itself (Pyodide, wheels) needs downloads and a browser, so it is
built by ``web/build_bundle.py`` and proven by ``web/verify_wizard.py`` and
``web/verify_offline.py``. What CI pins here: every file the build copies
exists, the generated scripts have the shape the page expects, and the page
says plainly that files never leave the browser.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
for extra in (WEB, WEB / "py"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import build_bundle  # noqa: E402  (from web/, via the path above)

from survey import QUESTIONS  # noqa: E402


def test_asset_scripts_round_trip():
    payload = bytes(range(256)) * 11
    script = build_bundle.asset_script("pyodide.asm.wasm", payload)
    assert script.startswith('otwinRegisterAsset("pyodide.asm.wasm", "')
    b64 = script.split('"')[3]
    assert base64.b64decode(b64) == payload


def test_generated_scripts_have_the_shape_the_page_expects():
    manifest = build_bundle.manifest_script(["assets/00.js", "assets/app.js"])
    assert manifest == 'const OTWIN_ASSET_SCRIPTS = ["assets/00.js", "assets/app.js"];\n'
    q = build_bundle.questions_script()
    assert q.startswith("const OTWIN_QUESTIONS = ") and q.endswith(";\n")
    data = json.loads(q[len("const OTWIN_QUESTIONS = ") : -2])
    assert [x["id"] for x in data["questions"]] == [x.id for x in QUESTIONS]
    assert "Álava" in q  # accents kept as they are


def test_every_file_the_build_copies_exists():
    repo = WEB.parents[2]
    for rel in build_bundle.APP_SOURCES:
        assert (repo / rel).is_dir(), rel
    for name in build_bundle.STATIC:
        assert (WEB / name).is_file(), name
    for name in build_bundle.SAMPLE_FILES:
        assert (WEB / "samples" / name).is_file(), name
    assert (WEB / "py" / "webmain.py").exists()


def test_the_wizard_page():
    html = (WEB / "index.html").read_text()
    assert "Your files never leave this computer." in html
    assert "There is no server, and nothing is uploaded." in html
    # the questions render before the engine, which the client then starts
    assert html.index("questions.js") < html.index("client.js") < html.index("wizard.js")
    for step in ("step1", "step2", "step3"):
        assert f'id="{step}"' in html
    assert 'type="file" multiple' in html and 'id="drop"' in html
    assert '<script src="https://' not in html  # nothing loaded from elsewhere
    css = (WEB / "style.css").read_text()
    assert '"Helvetica Neue", Helvetica, Arial' in css


def test_the_engine_runs_in_a_worker_when_served_and_on_the_page_from_disk():
    client = (WEB / "client.js").read_text()
    assert 'location.protocol === "http:" || location.protocol === "https:"' in client
    assert 'new Worker("worker.js")' in client
    worker = (WEB / "worker.js").read_text()
    assert 'importScripts("runtime.js", "assets/manifest.js")' in worker
    runtime = (WEB / "runtime.js").read_text()
    assert "otwinRegisterAsset" in runtime and "installFetchShim" in runtime
    assert "webmain.dispatch" in runtime
    wizard = (WEB / "wizard.js").read_text()
    assert "innerHTML" not in wizard  # text from files is only ever textContent
