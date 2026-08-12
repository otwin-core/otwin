"""``otwin.interfaces`` describes shapes. It must never compute anything.

This is the boundary the whole package hangs off. If an algorithm leaks into
the interface specification then every implementation inherits a behaviour it
did not choose, the Julia and MATLAB implementations acquire something to
mirror that is not in the specification, and the type test starts grading
against an accident.

The guard existed in the pre-merge layout and is carried over deliberately.
Merging thirteen packages into one made the boundary a convention rather than
a package wall, so it needs a test more than it did before, not less.
"""

import ast
import pathlib

import otwin.interfaces

FORBIDDEN = {
    "solve",
    "integrate",
    "fit",
    "forecast",
    "evaluate",
    "calibrate",
    "estimate",
    "predict",
    "simulate",
    "optimise",
    "optimize",
}

INTERFACE_DIR = pathlib.Path(otwin.interfaces.__file__).parent


def test_no_algorithm_names_are_exported():
    """No exported *function* may be named after an action.

    The distinction is grammatical and it is the right one. ``Forecast`` is a
    dataclass -- a noun, a result, a shape, which is exactly what this package
    is for. ``forecast()`` would be a verb, and a verb here means an algorithm
    has crossed the boundary.
    """
    leaked = []
    for name in otwin.interfaces.__all__:
        obj = getattr(otwin.interfaces, name)
        if isinstance(obj, type):
            continue  # a type is a noun; that is what this package exports
        if any(word in name.lower() for word in FORBIDDEN):
            leaked.append(name)

    assert not leaked, (
        f"otwin.interfaces exports the callable(s) {sorted(leaked)}. This "
        f"package declares shapes; anything that computes belongs in "
        f"otwin.model, otwin.estimate or otwin.forecast."
    )


def test_no_module_level_functions_do_real_work():
    """Belt and braces: no public function in the package has a real body.

    ``__all__`` can be edited. This walks the source instead, and flags any
    public module-level function whose body is longer than a constructor or a
    one-line delegation would be.
    """
    offenders = []
    for path in INTERFACE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                body = [n for n in node.body if not isinstance(n, ast.Expr)]
                if len(body) > 3:
                    offenders.append(f"{path.name}:{node.name} ({len(body)} statements)")
    assert not offenders, (
        f"module-level functions with real bodies in otwin.interfaces: {offenders}"
    )


def test_only_numpy_is_imported():
    """NumPy and the standard library. Nothing else, ever.

    Every implementation depends on this module, so a dependency added here is
    a dependency added everywhere -- including for someone who only wants to
    read a manifest.
    """
    allowed = {
        "numpy",
        "numpy.typing",
        "typing",
        "dataclasses",
        "json",
        "datetime",
        "pathlib",
        "collections",
        "collections.abc",
        "enum",
        "math",
        "os",
        "re",
        "sys",
        "warnings",
        "__future__",
        "typing_extensions",
        "abc",
        "copy",
        "hashlib",
    }
    offenders: dict[str, set[str]] = {}

    for path in INTERFACE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import, within the package
                    continue
                mods = {node.module or ""}
            else:
                continue
            bad = {
                m
                for m in mods
                if m.split(".")[0] not in {a.split(".")[0] for a in allowed}
            }
            if bad:
                offenders.setdefault(path.name, set()).update(bad)

    assert not offenders, (
        f"otwin.interfaces imports {offenders}. It may import NumPy and the "
        f"standard library and nothing else."
    )


def test_protocols_are_not_importable_from_a_computing_module():
    """The dependency arrow points one way: implementations -> interfaces.

    If ``otwin.interfaces`` ever imports from ``otwin.model`` or
    ``otwin.forecast``, the arrow has reversed and the specification now
    depends on one of its own implementations.
    """
    computing = {
        "otwin.model",
        "otwin.estimate",
        "otwin.forecast",
        "otwin.io",
        "otwin.signal",
        "otwin.advise",
    }
    for path in INTERFACE_DIR.glob("*.py"):
        source = path.read_text()
        for module in computing:
            assert f"import {module}" not in source, (
                f"{path.name} imports {module}. The specification must not "
                f"depend on an implementation of itself."
            )
