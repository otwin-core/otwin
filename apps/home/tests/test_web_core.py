"""The static site's wiring, tested natively. No network, no browser.

The bundle itself (Pyodide, wheels) needs downloads and a browser, so it is
built by ``web/build_bundle.py`` and proven by ``web/verify_wizard.py`` and
``web/verify_offline.py``. What CI pins here: every file the build copies
exists, the page is built the one way that works from ``file://``, its four
sections are kept apart, both languages say everything, and the page says
plainly that files never leave the browser.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
UI = WEB / "ui"
for extra in (WEB, WEB / "py"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import build_bundle  # noqa: E402  (from web/, via the path above)

from survey import QUESTIONS  # noqa: E402


def sources() -> list[Path]:
    """Every source file of the page itself."""
    return sorted(p for p in (UI / "src").rglob("*.js*") if p.is_file())


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
    assert set(data) == {"en", "es"}  # every language, baked
    for lang in ("en", "es"):
        assert [x["id"] for x in data[lang]["questions"]] == [x.id for x in QUESTIONS]
    assert data["es"]["questions"][4]["label"] == "¿Con qué calientas tu casa?"
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
    assert (UI / "src" / "main.jsx").exists()


def test_the_page_shell():
    """index.html is a shell: classic scripts only, because a browser refuses
    modules from file://, where this page must work. The page itself is the
    React bundle (ui/, built by Vite into app.js and app.css)."""
    html = (WEB / "index.html").read_text()
    assert "Your files never leave this computer." in html  # with no JavaScript too
    assert "There is no server, and nothing is uploaded." in html
    assert '<div id="root">' in html
    order = [
        html.index(f'src="{name}"')
        for name in ("questions.js", "build-info.js", "client.js", "app.js")
    ]
    assert order == sorted(order)  # the engine and the stamp load before the page
    assert 'type="module"' not in html  # a module never loads from file://
    assert '<script src="https://' not in html  # nothing loaded from elsewhere
    assert '<link rel="stylesheet" href="app.css" />' in html
    # questions.js, build-info.js and client.js declare their values with
    # const (script scope), so the shell hands them to the bundle
    for name in ("OTWIN_QUESTIONS", "OTWIN_BUILD", "OtwinHome"):
        assert f"window.{name} =" in html


def test_the_page_is_built_as_one_classic_script():
    """Vite must emit an IIFE bundle with its CSS beside it: ES modules do not
    load from file://, and the page has to work opened from disk."""
    config = (UI / "vite.config.js").read_text()
    assert 'format: "iife"' in config  # never "es"
    assert 'entryFileNames: "app.js"' in config
    assert 'assetFileNames: "app.[ext]"' in config
    assert "inlineDynamicImports: true" in config and "cssCodeSplit: false" in config
    package = json.loads((UI / "package.json").read_text())
    for needed in ("react", "react-dom", "@radix-ui/react-tabs"):
        assert needed in package["dependencies"], needed
    assert package["scripts"]["build"] == "vite build"


def test_the_four_sections_are_kept_apart():
    """Each section stands on its own: the householder's home, the demos, the
    simulation to come, and help. A demo never shows questions about the
    householder's own home, because it has its own workspace."""
    app = (UI / "src" / "App.jsx").read_text()
    assert 'const SECTIONS = ["home", "demo", "simulation", "help"]' in app
    assert 'id: "own"' in app and "demo:${state?.demo?.key" in app
    store = (UI / "src" / "store.js").read_text()
    assert "own: emptyWorkspace()" in store
    assert "demo: { ...emptyWorkspace(), key: null }" in store
    engine_js = (UI / "src" / "engine.js").read_text()
    # one engine session, pointed at whichever workspace is asking for it
    assert "export async function useWorkspace" in engine_js
    assert 'await call("forget")' in engine_js
    assert "export function serial" in engine_js  # one engine job at a time
    for part in ("YourHome", "Demo", "Simulation", "Help", "Dashboard"):
        assert (UI / "src" / "parts" / f"{part}.jsx").is_file(), part


def test_the_source_page_opens_the_build_or_says_how_to_make_it():
    """apps/home/web/index.html is the page's source: questions.js and the
    engine exist only in dist/. Opened as it is (an editor's preview), it
    must open the build, or explain the one command, never stay blank."""
    html = (WEB / "index.html").read_text()
    guard = html[html.index('if (typeof OTWIN_QUESTIONS === "undefined")') :]
    assert 'probe.src = "dist/build-info.js"' in guard
    assert 'location.replace("dist/index.html")' in guard
    assert "python apps/home/web/build_bundle.py" in guard
    assert html.index('OTWIN_QUESTIONS === "undefined"') < html.index('src="client.js"')
    assert "build-info.js" in html  # the build stamp reaches the footer


def test_a_build_is_stamped_with_what_it_was_built_from(tmp_path, monkeypatch):
    stamp = build_bundle.fingerprint()
    assert len(stamp) == 16 and stamp == build_bundle.fingerprint()  # deterministic
    files = build_bundle.source_files()
    assert WEB / "py" / "webmain.py" in files and WEB / "py" / "texts.py" in files
    assert UI / "src" / "App.jsx" in files  # the page's own sources
    assert UI / "vite.config.js" in files
    script = build_bundle.build_info_script(stamp, "2026-11-16 12:00")
    assert script.startswith("const OTWIN_BUILD = ")
    monkeypatch.setattr(build_bundle, "DIST", tmp_path)
    assert build_bundle.check() == 1  # no build
    (tmp_path / "index.html").write_text("")
    assert build_bundle.check() == 1  # an old build, without a stamp
    (tmp_path / "build-info.js").write_text(build_bundle.build_info_script("0" * 16, "x"))
    assert build_bundle.check() == 1  # built from other sources
    (tmp_path / "build-info.js").write_text(script)
    assert build_bundle.check() == 0


def test_a_local_build_is_not_stale():
    """dist/ is not in git. If there is one here, it must be built from the
    sources as they are, or the page shows old code (python
    apps/home/web/build_bundle.py rebuilds it)."""
    if not (build_bundle.DIST / "index.html").exists():
        pytest.skip("no local build in web/dist/")
    assert build_bundle.built_fingerprint() == build_bundle.fingerprint(), (
        "web/dist/ is out of date: run python apps/home/web/build_bundle.py"
    )


def test_the_engine_runs_in_a_worker_when_served_and_on_the_page_from_disk():
    client = (WEB / "client.js").read_text()
    assert 'location.protocol === "http:" || location.protocol === "https:"' in client
    assert 'new Worker("worker.js")' in client
    # a browser that refuses workers over http still gets the engine, on the page
    assert ".catch((e) =>" in client and "return startOnPage();" in client
    worker = (WEB / "worker.js").read_text()
    assert 'importScripts("runtime.js", "assets/manifest.js")' in worker
    runtime = (WEB / "runtime.js").read_text()
    assert "otwinRegisterAsset" in runtime and "installFetchShim" in runtime
    assert "webmain.dispatch" in runtime
    # text from files and from the engine is only ever text: React escapes it,
    # and nothing in the page sets HTML from a string
    for source in sources():
        assert "dangerouslySetInnerHTML" not in source.read_text(), source


def test_every_example_file_the_page_reads_is_in_the_bundle():
    """The page reads its demos from the bundle, not from the repository:
    each file a demo names, and each demo's truth, must be shipped."""
    import webmain

    shipped = set(build_bundle.SAMPLE_FILES)
    for _, (label, home, names) in webmain.SAMPLE_SETS.items():
        assert home in shipped, label
        assert str(Path(home).parent / "truth.json").lstrip("./") in shipped, label
        missing = [n for n in names if n not in shipped]
        assert not missing, f"{label}: {missing} are not in the bundle"


def test_both_languages_say_everything():
    """Every word of the page, every sentence of the engine and every question
    exists in English and in Spanish: the page never shows a bare key or
    switches language mid-sentence."""
    import texts

    from survey.questions import PROVINCES, SPANISH

    js = (UI / "src" / "i18n.js").read_text()
    blocks = re.split(r"\n  (en|es): \{\n", js)
    keys = {
        blocks[i]: set(
            re.findall(
                r'^    "?([a-z_A-Z0-9 ]+)"?:', blocks[i + 1].split("\n  },")[0], re.M
            )
        )
        for i in (1, 3)
    }
    assert keys["en"] == keys["es"] and len(keys["en"]) > 200
    # every key the page asks for exists
    asked = set()
    for source in sources():
        text = source.read_text()
        asked |= set(re.findall(r'\bt\("([a-z_0-9]+)"', text))
        asked |= set(re.findall(r'translate\(lang, "([a-z_0-9]+)"', text))
    assert asked <= keys["en"], sorted(asked - keys["en"])
    assert len(asked) > 60  # the page really is worded from here
    # the engine's sentences
    missing = [k for k, v in texts.TEXTS.items() if "es" not in v or "en" not in v]
    assert not missing, missing
    # the questions (province names are the same in both)
    names = {p.label for p in PROVINCES}
    untranslated = [
        t
        for q in QUESTIONS
        for t in [q.label, q.help, *(o.label for o in q.options)]
        if t and t not in names and t not in SPANISH
    ]
    assert not untranslated, untranslated
