"""Write the component reference from the components themselves.

Every public component in :mod:`otwin.components` is instantiated with
representative arguments and asked what it declares: ports, parameters (with
units, defaults and validity rules), storage states, inputs, the outputs the
compiled model will publish, and, for a composite, its parts. That, plus the
class docstring, becomes ``docs/reference/components.md``.

    python docs/generate_components.py            # rewrite the page
    python docs/generate_components.py --check    # exit 1 if it is out of date

The page is committed so it reads on GitHub and on readthedocs alike; CI runs
``--check`` so it cannot drift from the code.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from otwin import expr as ex  # noqa: E402
from otwin.components.base import (  # noqa: E402
    DOMAINS,
    Component,
    ComponentQuantities,
    Composite,
    HeatBranch,
    ResistorBranch,
    SourceBranch,
    StorageBranch,
    TwoPortBranch,
)

OUT = ROOT / "docs" / "reference" / "components.md"

# Modules in the order the page lists them, with a one-line lead for each.
SECTIONS: list[tuple[str, str, str]] = [
    ("electrical", "Electrical", "Voltage across, current through. Ports `p` and `n`."),
    (
        "mechanical",
        "Mechanical (translation)",
        "Velocity across, force through. Ports `a`, `b` or a single `flange`.",
    ),
    (
        "rotational",
        "Rotational",
        "Angular velocity across, torque through. Ports `a`, `b` or a single `flange`.",
    ),
    (
        "hydraulic",
        "Hydraulic",
        "Pressure across, volumetric flow through. Ports `a`, `b`, `inlet`/`outlet`, or a single `port`.",
    ),
    (
        "thermal",
        "Thermal",
        "Temperature across, heat flow through. Ports `a`, `b` or a single `port`.",
    ),
    (
        "twoport",
        "Two-ports",
        "Lossless couplings between two branches, in one domain or across two.",
    ),
    (
        "composite,battery",
        "Composites",
        "Devices built from the primitives: a motor, a battery (and `Pump`, listed under hydraulic). "
        "Their parts are ordinary components named `<device>.<part>`.",
    ),
    (
        "fundamental",
        "Fundamental (any domain)",
        "The four primitives every domain-specific component is made of, for a domain the library does not name.",
    ),
]

# Constructor arguments where the defaults are not enough to instantiate.
EXAMPLES: dict[str, dict[str, Any]] = {
    "hydraulic.Pipe": {"resistance": 5e5},
    "hydraulic.Filter": {"resistance": 2e6},
    "hydraulic.Pump": {"shutoff": 4e5, "max_flow": 0.08},
    "battery.Battery": {
        "capacity": 100.0,
        "ocv": [(0.0, 2.8), (0.5, 3.3), (1.0, 3.55)],
        "rc_branches": [(0.5e-3, 20e3)],
        "thermal": 1200.0,
    },
    "fundamental.Storage": {"domain": "electrical"},
    "fundamental.Dissipator": {"domain": "electrical"},
    "fundamental.Source": {"domain": "electrical"},
}


class _Any(dict):
    """A quantities table that answers every key with a symbol.

    ``extra_outputs`` only needs the names and units, not the values.
    """

    def __missing__(self, key: str) -> ex.Expr:
        return ex.symbol("state", key)


def _instance(module: str, cls: type) -> Component:
    kwargs = dict(EXAMPLES.get(f"{module}.{cls.__name__}", {}))
    if cls.__name__ == "Losses":
        from otwin.components.electrical import Resistor

        return cls(Resistor(1.0, name="r"), name="losses")
    kwargs.setdefault("name", cls.__name__.lower())
    return cls(**kwargs)


def _signature(cls: type) -> str:
    sig = inspect.signature(cls.__init__)
    parts = []
    for p in list(sig.parameters.values())[1:]:
        if p.kind is p.VAR_POSITIONAL:
            parts.append(f"*{p.name}")
        elif p.default is inspect.Parameter.empty:
            parts.append(p.name)
        else:
            parts.append(f"{p.name}={p.default!r}")
    return f"{cls.__name__}({', '.join(parts)})"


def _doc(cls: type) -> str:
    doc = inspect.getdoc(cls) or ""
    # keep the prose; the Args section is rendered from the live parameters
    head, _, _ = doc.partition("\nArgs:")
    return head.strip()


def _constraint(p: Any) -> str:
    if p.positive:
        return "> 0"
    if p.nonneg:
        return "≥ 0"
    return "any"


def _fmt(v: float) -> str:
    return f"{v:g}"


def _outputs(comp: Component) -> list[tuple[str, str]]:
    """The ``<name>.<quantity>`` outputs the compiled model publishes."""
    out: list[tuple[str, str]] = []
    n = comp.name
    if isinstance(comp, Composite):
        for part in comp.parts:
            out += _outputs(part)
    branches = comp.branches() if not isinstance(comp, Composite) else []
    for b in branches:
        label = b.label or n
        if isinstance(b, StorageBranch):
            out.append((f"{label}.{b.state}", b.state_unit))
            out.append((f"{n}.energy", "J"))
        if isinstance(b, HeatBranch):
            out.append((f"{label}.heat_flow", "W"))
            continue
        dom = DOMAINS.get(b.domain)
        if dom is not None:
            out.append((f"{label}.{dom.across}", dom.across_unit))
            out.append((f"{label}.{dom.through}", dom.through_unit))
            out.append((f"{label}.power", "W"))
        if isinstance(b, TwoPortBranch) and b.a2 is not None:
            dom2 = DOMAINS.get(b.a2.domain)
            label2 = b.label2 or f"{n}.2"
            if dom2 is not None:
                out.append((f"{label2}.{dom2.across}", dom2.across_unit))
                out.append((f"{label2}.{dom2.through}", dom2.through_unit))
    q = ComponentQuantities()
    q.across, q.through, q.state, q.params = _Any(), _Any(), _Any(), _Any()
    try:
        for name, (unit, _) in comp.extra_outputs(q).items():
            out.append((f"{n}.{name}", unit))
    except Exception:  # noqa: BLE001 - a device may need real quantities
        pass
    seen: set[str] = set()
    uniq = []
    for k, u in out:
        if k not in seen:
            seen.add(k)
            uniq.append((k, u))
    return uniq


def _states(comp: Component) -> list[tuple[str, str, str]]:
    if isinstance(comp, Composite):
        rows = []
        for part in comp.parts:
            rows += [(s, u, i) for s, u, i in _states(part)]
        return rows
    return [
        (f"{comp.name}.{b.state}", b.state_unit, _fmt(b.initial))
        for b in comp.branches()
        if isinstance(b, StorageBranch)
    ]


def _params(comp: Component) -> list[list[str]]:
    """Declared parameters plus the constant sources, which compile to parameters too."""
    rows = []
    if isinstance(comp, Composite):
        for part in comp.parts:
            rows += _params(part)
        return rows
    for p in comp.parameters.values():
        rows.append(
            [
                f"`{comp.name}.{p.name}`",
                p.unit or "—",
                _fmt(p.value),
                _constraint(p),
                _cell(p.description),
            ]
        )
    for b in comp.branches():
        if isinstance(b, SourceBranch) and b.value is not None:
            rows.append(
                [
                    f"`{b.label or comp.name}.{b.quantity}`",
                    b.unit or "—",
                    _fmt(b.value),
                    "any",
                    f"the imposed {b.quantity.replace('_', ' ')}; `None` makes it an input",
                ]
            )
    return rows


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _inputs(comp: Component) -> list[tuple[str, str]]:
    if isinstance(comp, Composite):
        return []
    return [
        (b.quantity, b.unit)
        for b in comp.branches()
        if isinstance(b, SourceBranch) and b.value is None
    ]


def _kind(comp: Component) -> str:
    if isinstance(comp, Composite):
        return "composite of " + ", ".join(
            f"`{p.name}` ({type(p).__name__})" for p in comp.parts
        )
    kinds = []
    for b in comp.branches():
        if isinstance(b, StorageBranch):
            kinds.append(f"{b.kind} storage")
        elif isinstance(b, ResistorBranch):
            kinds.append("resistor (flow-first law)" if b.law is None else "resistor")
        elif isinstance(b, SourceBranch):
            kinds.append(f"{b.kind} source" + (" (input)" if b.value is None else ""))
        elif isinstance(b, TwoPortBranch):
            kinds.append(b.kind)
        elif isinstance(b, HeatBranch):
            kinds.append("heat injection")
    if not kinds:
        return "reference (the zero of its domain)"
    return ", ".join(dict.fromkeys(kinds))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    line = "| " + " | ".join(headers) + " |\n|" + "---|" * len(headers) + "\n"
    for r in rows:
        line += "| " + " | ".join(r) + " |\n"
    return line


def _entry(module: str, cls: type) -> str:
    comp = _instance(module, cls)
    mod = f"otwin.components.{module}"
    md = [f"### {_heading(module, cls)}", ""]
    md.append(f"`{mod}.{_signature(cls)}`")
    md.append("")
    doc = _doc(cls)
    if doc:
        md.append(doc)
        md.append("")
    kind = f"**Kind:** {_kind(comp)}."
    if comp.series_ports:
        a, b = comp.series_ports
        kind += f" In a `>>` chain it is entered at `{a}` and left at `{b}`."
    md.append(kind)
    md.append("")

    ports = [[f"`{p.name}`", p.domain] for p in comp.ports.values()]
    md.append("**Ports**")
    md.append("")
    md.append(_table(["port", "domain"], ports))

    params = _params(comp)
    if params:
        md.append(
            "**Parameters** (as the compiled model names them; the value column is the example's)"
        )
        md.append("")
        md.append(_table(["parameter", "unit", "value", "valid", "meaning"], params))

    states = _states(comp)
    if states:
        md.append("**States**")
        md.append("")
        md.append(
            _table(["state", "unit", "initial"], [[f"`{s}`", u, i] for s, u, i in states])
        )

    inputs = _inputs(comp)
    if inputs:
        md.append("**Inputs** when the value is `None`")
        md.append("")
        md.append(_table(["input", "unit"], [[f"`{comp.name}`", u] for _, u in inputs]))

    outs = _outputs(comp)
    if outs:
        md.append("**Outputs**")
        md.append("")
        md.append(_table(["output", "unit"], [[f"`{k}`", u or "—"] for k, u in outs]))

    return "\n".join(md).rstrip() + "\n"


def _components(modules: str) -> list[tuple[str, type]]:
    out = []
    for module in modules.split(","):
        mod = importlib.import_module(f"otwin.components.{module}")
        for n in getattr(mod, "__all__", []):
            c = getattr(mod, n)
            if inspect.isclass(c) and issubclass(c, Component) and c is not Component:
                out.append((module, c))
    return out


def _heading(module: str, cls: type) -> str:
    """Two classes share a name (the fundamental two-ports); keep headings unique."""
    if module == "fundamental" and cls.__name__ in ("Transformer", "Gyrator"):
        return f"{cls.__name__} (any domain)"
    return cls.__name__


def render() -> str:
    parts = [
        textwrap.dedent(
            """\
            # Component reference

            Every component in the library, generated from the code by
            `docs/generate_components.py`, so what you read here is what the
            compiler sees. For each one: how to construct it, what it means,
            its ports, the parameters the compiled model exposes by name (every
            one changeable with `with_parameters` or fitted with
            `fit_parameters`), the states it creates, the input it becomes when
            its value is `None`, and the outputs `model.outputs(state)` returns.

            The example instance is named after the class in lower case
            (`resistor`, `tank`), so a parameter listed as `tank.area` is
            `<your name>.area` in your model. Parameter values in the tables are
            the example's, not recommendations.

            The one rule behind every table: at a node, the across variable
            (voltage, velocity, pressure, temperature) is shared and the through
            variables (current, force, flow, heat flow) sum to zero. A component
            is a set of relations between those two on its ports; the compiler
            does the rest. [Components, ports and systems](../concepts/components.md)
            explains the vocabulary; [Modelling](../guides/modelling.md) shows the
            components in use.

            """
        )
    ]
    index = ["## Index", ""]
    for module, title, _ in SECTIONS:
        links = []
        for mod, c in _components(module):
            h = _heading(mod, c)
            anchor = h.lower().replace(" ", "-").replace("(", "").replace(")", "")
            links.append(f"[`{c.__name__}`](#{anchor})")
        index.append(f"- **{title}**: {', '.join(links)}")
    parts.append("\n".join(index) + "\n")
    for module, title, lead in SECTIONS:
        parts.append(f"\n## {title}\n\n{lead}\n")
        for mod, cls in _components(module):
            parts.append("\n" + _entry(mod, cls))
    return "".join(parts).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--check", action="store_true", help="fail if the page is out of date"
    )
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(
                f"{OUT.relative_to(ROOT)} is out of date; run python docs/generate_components.py"
            )
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({text.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
