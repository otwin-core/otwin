"""Every ```python block in the documentation is executed here.

Documentation rots in a specific way: the prose stays plausible while the code
stops running. Nothing catches it, because nobody runs a Markdown file. So the
examples are run as tests.

The contract is simple and visible in the source of every page:

* a ```python fence is a runnable step. All of them in one file share a
  namespace and run in document order, because that is how a reader meets them.
* a ```{code-block} python fence is an illustrative fragment. It is not run,
  and it should not look like something you could paste.

If an example needs data, it synthesises it. A doc example that depends on a
file in someone's home directory is a doc example that only works for them.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
# A runnable block, and the ```text block that follows it if there is one.
# The second group is the claimed output, and it is checked rather than trusted.
FENCE = re.compile(
    r"^```python\n(?P<code>.*?)^```\n"
    r"(?:\n(?:.*?\n)??^```text\n(?P<out>.*?)^```\n)?",
    re.MULTILINE | re.DOTALL,
)


def _pages() -> list[Path]:
    return sorted(p for p in DOCS.rglob("*.md") if "_build" not in p.parts)


def _blocks(page: Path) -> list[tuple[str, str | None]]:
    text = page.read_text()
    out = []
    for m in FENCE.finditer(text):
        # Only pair the output when it is the very next thing in the file;
        # a ```text block further down belongs to something else.
        claimed = m.group("out")
        if claimed is not None:
            between = text[m.end("code") + 4 : m.start("out") - 8]
            if between.strip():
                claimed = None
        out.append((m.group("code"), claimed))
    return out


@pytest.mark.parametrize("page", _pages(), ids=lambda p: str(p.relative_to(DOCS)))
def test_the_examples_on_this_page_run(page: Path) -> None:
    blocks = _blocks(page)
    if not blocks:
        pytest.skip("no runnable examples")

    # One namespace per page: block 3 may use what block 1 defined, exactly as a
    # reader working down the page would.
    namespace: dict[str, object] = {"__name__": "__docs__"}
    for i, (block, claimed) in enumerate(blocks, start=1):
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                exec(compile(block, f"{page.name}#block{i}", "exec"), namespace)
        except Exception as exc:  # noqa: BLE001 - the message is the point
            raise AssertionError(
                f"{page.relative_to(DOCS)} block {i} failed: "
                f"{type(exc).__name__}: {exc}\n\n{block}"
            ) from exc

        if claimed is None:
            continue
        printed = buffer.getvalue().strip()
        expected = claimed.strip()
        assert printed == expected, (
            f"{page.relative_to(DOCS)} block {i}: the page claims an output the "
            f"code does not produce.\n\nclaimed:\n{expected}\n\nactual:\n{printed}"
        )


def test_every_page_is_reachable_from_a_toctree() -> None:
    """An orphan page is written, published, and never found."""
    referenced = set()
    for page in _pages():
        text = page.read_text()
        for match in re.finditer(r"^```\{toctree\}\n(.*?)^```", text, re.M | re.S):
            for line in match.group(1).splitlines():
                line = line.strip()
                if line and not line.startswith(":"):
                    referenced.add((page.parent / line).resolve())

    root = (DOCS / "index.md").resolve()
    orphans = [
        p.relative_to(DOCS)
        for p in _pages()
        if p.resolve() != root and p.with_suffix("").resolve() not in referenced
    ]
    assert not orphans, f"not in any toctree: {orphans}"
