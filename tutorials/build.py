"""Build the tutorials: one source, two outputs, every number real.

Each tutorial is written once, as a percent-format script in ``tutorials/src``
(``# %% [markdown]`` cells hold the prose, ``# %%`` cells the code). This
script runs every code cell in order, captures what it prints and the figures
it draws, and writes

* ``tutorials/<name>.md``, the page a reader sees on GitHub, with the output
  of every cell under it, and
* ``examples/<name>.ipynb``, the same cells as a notebook with the outputs
  embedded, which the test suite executes.

The two cannot drift apart because neither is edited by hand. Run::

    python tutorials/build.py            # all
    python tutorials/build.py 05         # one, by number prefix
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import sys
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tutorials" / "src"
MD_OUT = ROOT / "tutorials"
NB_OUT = ROOT / "examples"
IMG = ROOT / "tutorials" / "images"


def parse(text: str) -> list[tuple[str, str]]:
    """Split a percent-format script into ``(kind, source)`` cells."""
    cells: list[tuple[str, str]] = []
    kind, buf = None, []
    for line in text.splitlines():
        m = re.match(r"^# %%( \[markdown\])?\s*$", line)
        if m:
            if kind is not None:
                cells.append((kind, "\n".join(buf).strip("\n")))
            kind, buf = ("markdown" if m.group(1) else "code"), []
            continue
        if kind is not None:
            buf.append(line)
    if kind is not None:
        cells.append((kind, "\n".join(buf).strip("\n")))
    out = []
    for k, src in cells:
        if k == "markdown":
            src = "\n".join(
                ln[2:] if ln.startswith("# ") else ln[1:] if ln.startswith("#") else ln
                for ln in src.splitlines()
            )
        out.append((k, src.strip("\n")))
    return [c for c in out if c[1].strip()]


def run(cells: list[tuple[str, str]], slug: str) -> list[dict]:
    """Execute the code cells in one namespace; return cells with outputs."""
    ns: dict = {"__name__": "__tutorial__"}
    results = []
    fig_n = 0
    for kind, src in cells:
        if kind == "markdown":
            results.append({"kind": "markdown", "source": src})
            continue
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(src, f"<{slug}>", "exec"), ns)
        except Exception:
            print(f"\n--- {slug}: a cell failed ---\n{src}\n", file=sys.stderr)
            traceback.print_exc()
            raise
        images = []
        for num in plt.get_fignums():
            fig_n += 1
            name = f"{slug}_fig{fig_n}.png"
            plt.figure(num).savefig(
                IMG / name, dpi=110, bbox_inches="tight", facecolor="white"
            )
            images.append(name)
        plt.close("all")
        results.append(
            {"kind": "code", "source": src, "stdout": buf.getvalue(), "images": images}
        )
    return results


def to_markdown(results: list[dict]) -> str:
    parts = []
    for c in results:
        if c["kind"] == "markdown":
            parts.append(c["source"] + "\n")
            continue
        parts.append("```python\n" + c["source"] + "\n```\n")
        if c["stdout"].strip():
            parts.append("```text\n" + c["stdout"].rstrip() + "\n```\n")
        for img in c["images"]:
            parts.append(f"![{img}](images/{img})\n")
    return "\n".join(parts).rstrip() + "\n"


def to_notebook(results: list[dict]) -> dict:
    cells = []
    for c in results:
        if c["kind"] == "markdown":
            cells.append(
                {"cell_type": "markdown", "metadata": {}, "source": _lines(c["source"])}
            )
            continue
        outputs = []
        if c["stdout"]:
            outputs.append(
                {"output_type": "stream", "name": "stdout", "text": _lines(c["stdout"])}
            )
        for img in c["images"]:
            data = base64.b64encode((IMG / img).read_bytes()).decode("ascii")
            outputs.append(
                {
                    "output_type": "display_data",
                    "metadata": {},
                    "data": {"image/png": data, "text/plain": [f"<Figure {img}>"]},
                }
            )
        cells.append(
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": None,
                "source": _lines(c["source"]),
                "outputs": outputs,
            }
        )
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _lines(text: str) -> list[str]:
    lines = text.splitlines(True)
    return lines if lines else [""]


def build(path: Path) -> None:
    slug = path.stem
    cells = parse(path.read_text(encoding="utf-8"))
    # markdown image links in the source are relative to tutorials/; the
    # notebook lives in examples/, so point them at ../tutorials/
    results = run(cells, slug)
    (MD_OUT / f"{slug}.md").write_text(to_markdown(results), encoding="utf-8")
    nb_results = [
        {**c, "source": c["source"].replace("](images/", "](../tutorials/images/")}
        if c["kind"] == "markdown"
        else c
        for c in results
    ]
    (NB_OUT / f"{slug}.ipynb").write_text(
        json.dumps(to_notebook(nb_results), indent=1), encoding="utf-8"
    )
    print(f"built {slug}: {sum(1 for c in results if c['kind'] == 'code')} code cells")


if __name__ == "__main__":
    IMG.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]
    failed = []
    for p in sorted(SRC.glob("*.py")):
        if only and not any(p.name.startswith(o) for o in only):
            continue
        try:
            build(p)
        except Exception:
            failed.append(p.name)
    if failed:
        print("FAILED:", ", ".join(failed), file=sys.stderr)
        raise SystemExit(1)
