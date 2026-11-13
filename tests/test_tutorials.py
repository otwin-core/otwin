"""The tutorials run, and the notebooks are the tutorials.

``tutorials/build.py`` writes each tutorial twice from one source: the
markdown page with its outputs, and the notebook in ``examples/``. These tests
execute every notebook's code cells in order, in a fresh namespace, and check
that the code in the page is the code in the notebook. A tutorial that stops
running, or a page that drifts from its notebook, fails here.

Needs the ``tutorials`` extra (matplotlib, seaborn, pandas). Skipped without it.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest

sns = pytest.importorskip("seaborn", reason="the tutorials need otwin[tutorials]")
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((ROOT / "examples").glob("*.ipynb"))
PAGES = {p.stem: p for p in (ROOT / "tutorials").glob("*.md")}


def _code_cells(nb: dict) -> list[str]:
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def _code_blocks(md: str) -> list[str]:
    return [m.strip("\n") for m in re.findall(r"```python\n(.*?)```", md, flags=re.S)]


@pytest.mark.parametrize("path", NOTEBOOKS, ids=[p.stem for p in NOTEBOOKS])
def test_the_notebook_runs(path: Path) -> None:
    nb = json.loads(path.read_text(encoding="utf-8"))
    ns: dict = {"__name__": "__tutorial_test__"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for i, src in enumerate(_code_cells(nb)):
            try:
                exec(compile(src, f"{path.name}[cell {i}]", "exec"), ns)
            finally:
                plt.close("all")


@pytest.mark.parametrize("path", NOTEBOOKS, ids=[p.stem for p in NOTEBOOKS])
def test_the_page_and_the_notebook_carry_the_same_code(path: Path) -> None:
    page = PAGES.get(path.stem)
    assert page is not None, (
        f"no tutorial page for {path.name}; run python tutorials/build.py"
    )
    nb = json.loads(path.read_text(encoding="utf-8"))
    assert _code_blocks(page.read_text(encoding="utf-8")) == [
        c.strip("\n") for c in _code_cells(nb)
    ]


def test_there_are_ten_tutorials_with_their_images() -> None:
    assert len(NOTEBOOKS) == 10
    for p in NOTEBOOKS:
        n = p.stem[:2]
        assert (ROOT / "tutorials" / "images" / f"t{n}_hero.png").is_file()
        assert (ROOT / "tutorials" / "images" / f"t{n}_pd.png").is_file()
