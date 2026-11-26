"""Sphinx configuration for the otwin documentation.

Two decisions worth stating, because both are visible in every page.

**The API reference is generated, never written.** `autosummary` walks the
package and reads the docstrings that `pytest --doctest-modules` already
executes on every commit. A hand-written parameter table is a second source of
truth that goes stale the first time somebody changes a default, and nothing
tells you it has. Here, a signature that drifts breaks the test suite before it
reaches the docs.

**Napoleon is not optional.** The package has two docstring dialects: newer
modules such as ``otwin.forecast.conformal`` use native reST roles, older ones
such as ``otwin.model.phs`` use Google-style ``Args:``. Napoleon reads the
second, Sphinx reads the first, and both render the same way.
"""

from __future__ import annotations

import json
import os
from importlib.metadata import version as _version
from pathlib import Path

BRAND = Path(__file__).resolve().parents[1] / "assets" / "brand"

project = "otwin"
copyright = "2026, otwin-core"
author = "otwin-core"

# Read from the installed distribution rather than restating it here. One more
# place for the version to live is one more place for it to disagree.
release = _version("otwin")
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx.ext.mathjax",
    "sphinx_copybutton",
    "sphinx_design",
    "sphinxcontrib.mermaid",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Markdown ---------------------------------------------------------------
# MyST rather than reST for the prose. The reference section is generated, so
# the only hand-written files are the ones a contributor should not need to
# learn a markup language to edit.
myst_enable_extensions = [
    "amsmath",       # \begin{align} ... \end{align}
    "colon_fence",   # ::: directives, which survive a Markdown renderer
    "deflist",
    "dollarmath",    # $x$ and $$x$$
    "linkify",
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3

# -- Autodoc ----------------------------------------------------------------
autosummary_generate = True
autodoc_member_order = "bysource"       # the order the author chose, not alphabetical
autodoc_typehints = "description"       # types in the parameter list, not the signature
autodoc_typehints_description_target = "documented_params"
autodoc_class_signature = "separated"

# numpy's annotations expand to `ndarray[tuple[Any, ...], dtype[floating[Any]]]`
# in a rendered signature, which is true and unreadable. The aliases the source
# actually uses are the ones a reader should see.
autodoc_type_aliases = {
    "Array": "otwin.interfaces.Array",
    "Vector": "otwin.interfaces.Array",
    "IndexArray": "otwin.interfaces.IndexArray",
    # `np.bool_` ends in an underscore, which reStructuredText reads as a
    # hyperlink reference to a target that does not exist. Rendered into a
    # parameter description by `autodoc_typehints = "description"`, it is a
    # build error rather than a typo.
    "npt.NDArray[np.bool_]": "numpy.ndarray of bool",
}

autodoc_default_options = {
    "members": True,
    "undoc-members": False,      # an undocumented member is a gap, not a page
    "show-inheritance": True,
}

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_use_param = True
# Render an `Attributes:` section as `:ivar:` fields inside the class body
# rather than as separate `py:attribute` directives. Without this, every
# dataclass attribute is documented twice on the same page -- once by autodoc
# from the annotation, once by napoleon from the docstring -- and Sphinx is
# right to complain about it.
napoleon_use_ivar = True
napoleon_use_rtype = True
napoleon_preprocess_types = True

# -- Cross-project links ----------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
}

# Fetching three inventories over the network turns an offline build into a
# wall of warnings, and `fail_on_warning` turns those into a failure. Set
# OTWIN_DOCS_OFFLINE=1 to build without them; Read the Docs has network and
# does not set it.
if os.environ.get("OTWIN_DOCS_OFFLINE"):
    intersphinx_mapping = {}

# -- HTML -------------------------------------------------------------------
html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_title = f"otwin {release}"

# The brand masters live in assets/brand and are referenced from there, never
# copied: Sphinx copies the logo and favicon into the build itself. The
# wordmark is a drawing and is placed, never typed (DESIGN.md).
html_logo = "../assets/brand/logo.svg"
html_favicon = "../assets/brand/favicon.svg"


# Diagrams take the brand Mermaid configuration: white nodes with an ink
# outline, straight edges, the brand font.
# A custom init replaces the extension's own, import line included, so the
# import is written here with the version pinned next to it.
_MERMAID = json.loads((BRAND / "mermaid-config.json").read_text())
mermaid_version = "11.2.0"
mermaid_init_js = (
    f'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@{mermaid_version}'
    '/dist/mermaid.esm.min.mjs";'
    f"mermaid.initialize({{startOnLoad: false, ...{json.dumps(_MERMAID)}}});"
)

html_theme_options = {
    "logo": {
        "image_light": "../assets/brand/logo.svg",
        "image_dark": "../assets/brand/logo-white.svg",
        "alt_text": "otwin",
    },
    # Syntax colour would be colour without meaning; code reads in the grey scale.
    "pygments_light_style": "friendly_grayscale",
    "pygments_dark_style": "native",
    "github_url": "https://github.com/otwin-core/otwin",
    "show_prev_next": True,
    "navigation_with_keys": False,
    "show_toc_level": 2,
    "icon_links": [
        {
            "name": "PyPI",
            "url": "https://pypi.org/project/otwin/",
            "icon": "fa-brands fa-python",
        },
    ],
    "footer_start": ["copyright"],
    "footer_end": ["sphinx-version"],
}

# Read the Docs serves two builds: "stable" from the latest release tag, which
# is what pip installs, and "latest" from main. The second documents work that
# is not on PyPI yet, so it says so on every page.
if os.environ.get("READTHEDOCS_VERSION") == "latest":
    html_theme_options["announcement"] = (
        "These pages follow the main branch and can describe features that "
        "are not on PyPI yet. For the release that <code>pip install</code> "
        'gives you, read the <a href="https://otwin.readthedocs.io/en/stable/">'
        "stable documentation</a>."
    )

html_context = {
    "github_user": "otwin-core",
    "github_repo": "otwin",
    "github_version": "main",
    "doc_path": "docs",
}

# -- Warnings we accept -----------------------------------------------------
# `fail_on_warning: true` in .readthedocs.yaml means every entry here is a
# deliberate exemption with a reason, not a swept-under-the-rug list.
nitpicky = False
suppress_warnings = [
    # sphinx-design registers its own directives; MyST reports the ones it
    # does not know about at parse time even when they resolve later.
    "myst.header",
]
