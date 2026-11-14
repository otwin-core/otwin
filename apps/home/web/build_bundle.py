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
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import urllib.request
import zipfile
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
#: The static site, copied as is.
STATIC = [
    "index.html",
    "demo.html",
    "style.css",
    "wizard.js",
    "client.js",
    "runtime.js",
    "worker.js",
]
#: The example files the wizard's "Try with example files" reads.
SAMPLE_FILES = [
    "home.json",
    "consumo_horario_enero_2026.csv",
    "estacion_meteo_enero_2026.csv",
    "open_meteo_enero_2026.json",
]


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
        z.write(WEB / "py" / "webmain.py", "webmain.py")
        for name in SAMPLE_FILES:
            z.write(WEB / "samples" / name, f"samples/{name}")
        with zipfile.ZipFile(tzdata_wheel()) as w:
            for info in sorted(w.infolist(), key=lambda i: i.filename):
                if info.filename.startswith("tzdata"):
                    z.writestr(info.filename, w.read(info))
    return buf.getvalue()


def manifest_script(scripts: list[str]) -> str:
    """The list of asset scripts, for worker.js and the page loader."""
    return f"const OTWIN_ASSET_SCRIPTS = {json.dumps(scripts)};\n"


def questions_script() -> str:
    """The wizard's first step, baked from :data:`survey.QUESTIONS`.

    Rendering it from a script (rather than asking the engine) lets the page
    show the questions at once while the engine is still loading.
    """
    sys.path.insert(0, str(HOME))
    from survey import questions_json

    return (
        f"const OTWIN_QUESTIONS = {json.dumps(questions_json(), ensure_ascii=False)};\n"
    )


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
    app = build_app_zip()
    total += len(app)
    (DIST / "assets" / "app.js").write_text(asset_script("app.zip", app))
    scripts.append("assets/app.js")
    (DIST / "assets" / "manifest.js").write_text(manifest_script(scripts))
    (DIST / "questions.js").write_text(questions_script())
    for name in STATIC:
        shutil.copy(WEB / name, DIST / name)
    (DIST / ".nojekyll").write_text("")  # GitHub Pages: serve every file as it is
    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"  embedded {total / 1e6:.1f} MB of assets; dist/ is {size / 1e6:.1f} MB")
    print(f"  serve {DIST} from any static server (GitHub Pages included), or open")
    print(f"  {DIST / 'index.html'} from disk: it works offline either way")
    return DIST


if __name__ == "__main__":
    sys.exit(0 if main().exists() else 1)
