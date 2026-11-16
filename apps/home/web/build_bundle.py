"""Build the offline browser bundle of the home twin into ``web/dist/``.

The result is a static folder that works from ``file://`` with the network
off: a page built only of classic ``<script>`` tags (the one thing a
``file://`` page may load), every binary asset embedded as base64 inside
those scripts, and a ``fetch`` shim that serves them from memory. Nothing is
fetched at run time; see DECISION.md for why this shape was chosen.

What goes in:

* Pyodide |PYODIDE_VERSION| (CPython 3.13 on WebAssembly): its classic
  loader and engine scripts, the engine wasm, the stdlib, the lock file.
* The NumPy and SciPy wheels Pyodide builds, with openblas.
* ``app.zip``: the pure-Python code of this repository (``otwin`` and the
  Otwin Home packages), the web entry point, and the ``tzdata`` package
  (Pyodide ships no IANA time-zone database, and every schedule and tariff
  here lives in Europe/Madrid).

Build-time network only: assets are downloaded once into a cache directory
(``~/.cache/otwin-home-web`` or ``$OTWIN_HOME_WEB_CACHE``) and reused.

    python apps/home/web/build_bundle.py
    python -m http.server -d apps/home/web/dist   # or GitHub Pages, or file://
    python apps/home/web/build_bundle.py --check  # is dist/ built from the current sources?

Every build stamps ``dist/build-info.js`` with a fingerprint of the sources
it was built from. ``dist/`` is not in git: after changing the sources, or
restoring the repository, rebuild it, or the page in ``dist/`` is the old one.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

PYODIDE_VERSION = "0.28.3"
CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
TZDATA_SPEC = "tzdata"  # latest pure wheel from PyPI, cached

WEB = Path(__file__).resolve().parent
HOME = WEB.parent  # apps/home
REPO = HOME.parents[1]
DIST = WEB / "dist"

#: The scripts the page loads with plain <script src> tags.
SCRIPT_ASSETS = ["pyodide.js", "pyodide.asm.js"]
#: The binaries served by the fetch shim, embedded as base64.
BINARY_ASSETS = ["pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
#: The Python packages loaded into Pyodide (wheel names come from the lock).
PACKAGES = ["numpy", "scipy"]
#: What of this repository goes into app.zip, relative to the repo root.
APP_SOURCES = [
    "src/otwin",
    "apps/home/components",
    "apps/home/calibration",
    "apps/home/scenarios",
    "apps/home/ingest",
    "apps/home/survey",
]
#: The static site, copied as is. The page itself (app.js, app.css) is built
#: from ui/ by Vite, see :func:`build_ui`.
STATIC = [
    "index.html",
    "demo.html",
    "client.js",
    "runtime.js",
    "worker.js",
]
#: The React sources of the page: built to one classic script, because a
#: browser refuses modules from file://.
UI = WEB / "ui"
UI_BUILT = ["app.js", "app.css"]
#: The example files the wizard's "Try with example files" reads.
#: The example files the wizard's "Try with example files" reads: every data
#: file in samples/ (the generator's own script stays out), so a file added
#: to the examples can never be missing from the bundle.
SAMPLE_FILES = sorted(
    str(f.relative_to(WEB / "samples"))
    for f in (WEB / "samples").rglob("*")
    if f.suffix in (".csv", ".json")
)


def cache_dir() -> Path:
    import os

    root = os.environ.get("OTWIN_HOME_WEB_CACHE") or str(
        Path.home() / ".cache" / "otwin-home-web"
    )
    path = Path(root) / f"pyodide-{PYODIDE_VERSION}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch(name: str, url: str) -> Path:
    """``name`` from the cache, downloading it once if missing."""
    path = cache_dir() / name
    if not path.exists():
        print(f"  downloading {name} ...")
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        tmp.rename(path)
    return path


def package_files(lock: dict) -> list[str]:
    """The wheel/zip file names of :data:`PACKAGES` and their dependencies."""
    need: dict[str, str] = {}
    queue = list(PACKAGES)
    while queue:
        name = queue.pop()
        if name in need:
            continue
        p = lock["packages"][name]
        need[name] = p["file_name"]
        queue += p.get("depends", [])
    return sorted(need.values())


def tzdata_wheel() -> Path:
    """The pure-Python tzdata wheel from PyPI, cached."""
    marker = cache_dir() / "tzdata-wheel-name.txt"
    if marker.exists():
        name = marker.read_text().strip()
        if (cache_dir() / name).exists():
            return cache_dir() / name
    with urllib.request.urlopen(f"https://pypi.org/pypi/{TZDATA_SPEC}/json") as r:
        meta = json.load(r)
    wheel = next(
        u for u in meta["urls"] if u["filename"].endswith("py2.py3-none-any.whl")
    )
    path = fetch(wheel["filename"], wheel["url"])
    marker.write_text(wheel["filename"])
    return path


def build_app_zip() -> bytes:
    """The repository's pure-Python code plus tzdata, as one archive.

    Unpacked to ``/app`` in the browser and put on ``sys.path``: ``otwin``
    (the package itself, from ``src/``), the Otwin Home packages, the web
    entry point ``webmain.py`` with its example files, and ``tzdata``.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in APP_SOURCES:
            root = REPO / rel
            base = root.name if root.name != "otwin" else "otwin"
            for f in sorted(root.rglob("*.py")):
                z.write(f, f"{base}/{f.relative_to(root)}")
        for f in sorted((WEB / "py").glob("*.py")):  # webmain.py and its texts
            z.write(f, f.name)
        for name in SAMPLE_FILES:
            z.write(WEB / "samples" / name, f"samples/{name}")
        with zipfile.ZipFile(tzdata_wheel()) as w:
            for info in sorted(w.infolist(), key=lambda i: i.filename):
                if info.filename.startswith("tzdata"):
                    z.writestr(info.filename, w.read(info))
    return buf.getvalue()


def source_files() -> list[Path]:
    """Every file of this repository that ends up in ``dist/``."""
    files = [f for rel in APP_SOURCES for f in sorted((REPO / rel).rglob("*.py"))]
    files += sorted((WEB / "py").glob("*.py"))
    files += [WEB / "samples" / name for name in SAMPLE_FILES]
    files += [WEB / name for name in STATIC]
    files += [UI / "package.json", UI / "vite.config.js"]
    files += sorted(f for f in (UI / "src").rglob("*") if f.is_file())
    return files


def build_ui() -> None:
    """Build the page from ui/ with Vite, into ui/dist/app.js and app.css.

    Needs Node and the packages (``npm install`` in ui/, once). The output
    is one classic script: index.html loads it with a plain <script src>,
    which is the only kind of script a file:// page may load.
    """
    if not (UI / "node_modules").is_dir():
        print("  installing the page's packages (npm install, once)")
        run_npm(["install", "--no-audit", "--no-fund"])
    print("  building the page (vite)")
    run_npm(["run", "build"])
    for name in UI_BUILT:
        if not (UI / "dist" / name).is_file():
            raise SystemExit(f"the page did not build: ui/dist/{name} is missing")


def run_npm(args: list[str]) -> None:
    try:
        subprocess.run(["npm", *args], cwd=UI, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit(
            "the page is built with Node: install it (nodejs.org), then run this again"
        ) from None
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"npm {' '.join(args)} failed:\n{exc.stdout}\n{exc.stderr}"
        ) from None


def fingerprint() -> str:
    """A hash of everything ``dist/`` is built from: if it differs from the one
    stamped in ``dist/build-info.js``, the page is out of date."""
    h = hashlib.sha256()
    for f in source_files():
        h.update(str(f.relative_to(REPO)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def build_info_script(stamp: str, built: str) -> str:
    """``dist/build-info.js``: when and from what the page was built."""
    info = {"fingerprint": stamp, "built": built}
    return f"const OTWIN_BUILD = {json.dumps(info)};\n"


def built_fingerprint() -> str | None:
    """The fingerprint stamped in ``dist/``, or None when there is no build."""
    path = DIST / "build-info.js"
    if not path.exists():
        return None
    text = path.read_text()
    return json.loads(text[text.index("{") : text.rindex("}") + 1])["fingerprint"]


def check() -> int:
    """Is ``dist/`` built from the sources as they are now? 0 yes, 1 no."""
    stamped = built_fingerprint()
    if stamped is None:
        what = (
            "was built before builds were stamped"
            if (DIST / "index.html").exists()
            else ("has not been built")
        )
        print(f"{DIST} {what}: run python apps/home/web/build_bundle.py")
        return 1
    if stamped != fingerprint():
        print(
            f"{DIST} is out of date: the sources changed since it was built. "
            "Run python apps/home/web/build_bundle.py"
        )
        return 1
    print(f"{DIST} is up to date ({stamped})")
    return 0


def manifest_script(scripts: list[str]) -> str:
    """The list of asset scripts, for worker.js and the page loader."""
    return f"const OTWIN_ASSET_SCRIPTS = {json.dumps(scripts)};\n"


def questions_script() -> str:
    """The questions about the home, baked from :data:`survey.QUESTIONS` in
    every language: ``{"en": ..., "es": ...}``.

    Rendering them from a script (rather than asking the engine) lets the
    page show the questions at once while the engine is still loading.
    """
    sys.path.insert(0, str(HOME))
    from survey import questions_json
    from survey.questions import LANGUAGES

    data = {lang: questions_json(lang) for lang in LANGUAGES}
    return f"const OTWIN_QUESTIONS = {json.dumps(data, ensure_ascii=False)};\n"


def asset_script(name: str, data: bytes) -> str:
    """A classic script registering one embedded asset."""
    b64 = base64.b64encode(data).decode("ascii")
    return f"otwinRegisterAsset({json.dumps(name)}, {json.dumps(b64)});\n"


def main() -> Path:
    """Assemble ``dist/``; returns its path."""
    print(f"Building the offline bundle (Pyodide {PYODIDE_VERSION}) into {DIST}")
    lock_path = fetch("pyodide-lock.json", CDN + "pyodide-lock.json")
    lock = json.loads(lock_path.read_text())
    binaries = BINARY_ASSETS + package_files(lock)
    for name in SCRIPT_ASSETS + [b for b in binaries if b != "pyodide-lock.json"]:
        fetch(name, CDN + name)

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "assets").mkdir(parents=True)
    for name in SCRIPT_ASSETS:
        shutil.copy(cache_dir() / name, DIST / name)
    scripts = []
    total = 0
    for i, name in enumerate(binaries):
        data = (cache_dir() / name).read_bytes()
        total += len(data)
        out = DIST / "assets" / f"{i:02d}.js"
        out.write_text(asset_script(name, data))
        scripts.append(f"assets/{out.name}")
    build_ui()
    app = build_app_zip()
    total += len(app)
    (DIST / "assets" / "app.js").write_text(asset_script("app.zip", app))
    scripts.append("assets/app.js")
    (DIST / "assets" / "manifest.js").write_text(manifest_script(scripts))
    (DIST / "questions.js").write_text(questions_script())
    built = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")  # any language
    (DIST / "build-info.js").write_text(build_info_script(fingerprint(), built))
    for name in STATIC:
        shutil.copy(WEB / name, DIST / name)
    for name in UI_BUILT:
        shutil.copy(UI / "dist" / name, DIST / name)
    (DIST / ".nojekyll").write_text("")  # GitHub Pages: serve every file as it is
    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"  embedded {total / 1e6:.1f} MB of assets; dist/ is {size / 1e6:.1f} MB")
    print(f"  serve {DIST} from any static server (GitHub Pages included), or open")
    print(f"  {DIST / 'index.html'} from disk: it works offline either way")
    return DIST


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    sys.exit(0 if main().exists() else 1)
