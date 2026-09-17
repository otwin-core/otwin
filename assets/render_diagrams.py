"""Render the README diagrams from their Mermaid sources.

Every diagram in the README is an SVG in ``assets/diagrams/``, generated from
the ``.mmd`` file with the same name next to it. GitHub renders Mermaid inline
but PyPI and most other places do not, so the README embeds the images and
this script keeps them in step with their sources.

    python assets/render_diagrams.py            # render every out-of-date SVG
    python assets/render_diagrams.py --check    # exit 1 if any SVG is stale
    python assets/render_diagrams.py --force    # render them all

Needs mermaid-cli: ``npm install -g @mermaid-js/mermaid-cli``. Set
``MMDC_CHROMIUM`` to a Chromium executable if puppeteer should not download
its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIAGRAMS = HERE / "diagrams"
STAMP = re.compile(r"<!-- otwin:source-sha256=([0-9a-f]{64}) -->")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stale(src: Path, svg: Path) -> bool:
    if not svg.exists():
        return True
    m = STAMP.search(svg.read_text(encoding="utf-8"))
    return m is None or m.group(1) != _sha(src)


def _render(src: Path, svg: Path) -> None:
    cmd = ["mmdc", "-i", str(src), "-o", str(svg), "-b", "transparent", "-q"]
    chromium = os.environ.get("MMDC_CHROMIUM")
    with tempfile.TemporaryDirectory() as tmp:
        if chromium:
            cfg = Path(tmp) / "puppeteer.json"
            cfg.write_text(
                json.dumps({"executablePath": chromium, "args": ["--no-sandbox"]})
            )
            cmd += ["-p", str(cfg)]
        subprocess.run(cmd, check=True)
    text = svg.read_text(encoding="utf-8")
    # mermaid-cli sets a fixed width on the root; let the image scale with the page
    text = re.sub(r'(<svg[^>]*?) width="[^"]*"', r"\1", text, count=1)
    text = re.sub(r'(<svg[^>]*?) height="[^"]*"', r"\1", text, count=1)
    svg.write_text(
        text.rstrip() + f"\n<!-- otwin:source-sha256={_sha(src)} -->\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--check", action="store_true", help="report stale SVGs, render nothing"
    )
    ap.add_argument("--force", action="store_true", help="render every diagram")
    args = ap.parse_args(argv)

    sources = sorted(DIAGRAMS.glob("*.mmd"))
    stale = [s for s in sources if args.force or _stale(s, s.with_suffix(".svg"))]
    if args.check:
        for s in stale:
            print(
                f"stale: {s.with_suffix('.svg').relative_to(HERE.parent)} (run python assets/render_diagrams.py)"
            )
        print(f"{len(sources)} diagrams, {len(stale)} out of date")
        return 1 if stale else 0
    for s in stale:
        print(f"rendering {s.name}")
        _render(s, s.with_suffix(".svg"))
    print(f"{len(sources)} diagrams, {len(stale)} rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
