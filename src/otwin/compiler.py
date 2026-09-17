"""The model compiler: from a component graph to a port-Hamiltonian system.

Pipeline::

    System
      -> flatten composites, validate parameters and names
      -> build nodes (union of connected ports, one reference node)
      -> collect branches: storages, resistors, sources, two-ports
      -> pin node potentials through across-storages and across-sources
      -> write one conservation equation per unpinned node group
         and two constraint equations per two-port
      -> solve them symbolically (linear in the unknowns, or refuse)
      -> recover every through variable by peeling the pin trees
      -> assemble dx/dt for every state, in two forms:
           executable (nonlinear laws as written)
           structural (nonlinear laws as secant conductances)
      -> read J, R, G, D off the structural form by differentiation
      -> symbolic Jacobian of the executable form
      -> PHSIR

Every failure is reported in physical terms: which ports, which
components, what to change. The compiler never returns a model it cannot
account for.
"""

from __future__ import annotations

import math
import warnings
from collections import defaultdict
from dataclasses import dataclass, field

from . import expr as ex
from .components.base import (
    DOMAINS,
    Branch,
    Component,
    ComponentQuantities,
    Composite,
    Connection,
    Ground,
    HeatBranch,
    Port,
    ResistorBranch,
    SourceBranch,
    StorageBranch,
    TwoPortBranch,
)
from .expr import Expr
from .ir import (
    PHSIR,
    BranchRecord,
    ComponentRecord,
    InputVar,
    NodeRecord,
    OutputVar,
    ParamVar,
    PhysicalSystemIR,
    StateVar,
)
from .system import System

__all__ = ["compile_system", "CompileError", "StructureWarning"]

_TINY = 1e-12


class CompileError(ValueError):
    """The system cannot be compiled. The message says what is wrong in the
    language of components and connections."""


class StructureWarning(UserWarning):
    """The model compiled but a structural check did not pass at the initial
    state (typically a dissipation that is not positive semidefinite)."""


# ----------------------------------------------------------------------------
# Node bookkeeping
# ----------------------------------------------------------------------------
class _Node:
    """A set of ports joined into one potential. Index 0 is the reference."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.ports: list[Port] = []
        self.domain: str = "any"
        self.reference = False
        self.name = ""

    def __repr__(self) -> str:
        return self.name


@dataclass
class _Pin:
    """A branch that fixes the potential difference across it."""

    branch: Branch
    node_a: _Node
    node_b: _Node
    across: Expr  # potential(a) - potential(b)


@dataclass
class _Ctx:
    """Everything the passes share while compiling one system.

    Filled in order: components, nodes and branches by :func:`_build_nodes`
    and :func:`_collect_branches`; states, efforts, parameters and ports by
    :func:`_declare_symbols`; series-resistor placeholders, node potentials
    and two-port currents by the potential passes; secant placeholders and the
    final parameter renaming by assembly. ``effort_syms`` are placeholders for
    ``dH/dx`` that are substituted only after J and R have been read off.
    """

    comps: list[Component]
    nodes: list[_Node]
    ref: _Node
    branches: list[Branch]
    node_of: dict[Port, _Node]
    composites: list[Component] = field(default_factory=list)
    states: list[StateVar] = field(default_factory=list)
    state_syms: list[Expr] = field(default_factory=list)
    effort_syms: list[Expr] = field(default_factory=list)
    grad_H: list[Expr] = field(default_factory=list)
    energies: list[Expr] = field(default_factory=list)
    storage_branches: list[StorageBranch] = field(default_factory=list)
    params: list[ParamVar] = field(default_factory=list)
    inputs: list[InputVar] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    port_values: list[Expr] = field(default_factory=list)
    port_branches: list[SourceBranch] = field(default_factory=list)
    potentials: dict[_Node, Expr] = field(default_factory=dict)
    twoport_currents: dict[TwoPortBranch, tuple[Expr, Expr]] = field(default_factory=dict)
    pin_parent: dict[_Node, _Pin] = field(default_factory=dict)
    pin_order: list[_Node] = field(default_factory=list)
    secants: dict[Expr, Expr] = field(default_factory=dict)
    rename: dict[Expr, Expr] = field(default_factory=dict)
    # resistors whose flow is set in series: branch -> (placeholder, through a->b)
    series: dict[ResistorBranch, tuple[Expr, Expr]] = field(default_factory=dict)
    inverse_map: dict[Expr, Expr] = field(default_factory=dict)
    representation: str = "port-hamiltonian"


def _terminal_str(t: Port | None) -> str:
    """A port's qualified name for messages, ``"reference"`` for ``None``."""
    return "reference" if t is None else t.qualified


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def compile_system(
    system: System, *, name: str | None = None, jacobian: bool = True, check: bool = True
) -> PHSIR:
    """Compile a :class:`~otwin.system.System` into a :class:`~otwin.ir.PHSIR`."""
    comps, links = system.flattened()
    if not comps:
        raise CompileError("the system has no components")
    _validate_components(comps)
    ctx = _build_nodes(comps, links)
    ctx.composites = _composites(system.components)
    _collect_branches(ctx)
    _declare_symbols(ctx)
    _series_resistors(ctx)
    unknown_eqs = _pin_potentials(ctx)
    ctx.inverse_map = _inverse_map(ctx, structural=False)
    _solve_unknowns(ctx, unknown_eqs)
    rhs_exec, port_out_exec, quantities = _assemble(ctx, structural=False)
    rhs_struct, port_out_struct, _ = _assemble(ctx, structural=True)
    J, R, G, D = _extract_structure(ctx, rhs_struct, port_out_struct)
    effort_map = dict(zip(ctx.effort_syms, ctx.grad_H, strict=True))
    rhs = [e.substitute(effort_map) for e in rhs_exec]
    port_outputs = [e.substitute(effort_map) for e in port_out_exec]
    outputs = _outputs(ctx, quantities, effort_map)
    energy = ex.const(0.0)
    for h in ctx.energies:
        energy = energy + h
    jac = None
    if jacobian:
        jac = [[e.diff(s) for s in ctx.state_syms] for e in rhs]
    physical = _physical_ir(system, ctx, name)

    def fin(e: Expr) -> Expr:
        return e.substitute(ctx.rename)

    def fin_mat(m: list[list[Expr]]) -> list[list[Expr]]:
        return [[fin(e) for e in row] for row in m]

    ir = PHSIR(
        name=physical.name,
        states=list(ctx.states),
        params=list(ctx.params),
        inputs=list(ctx.inputs),
        energy=fin(energy),
        grad_H=[fin(e) for e in ctx.grad_H],
        J=fin_mat(J),
        R=fin_mat(R),
        ports=list(ctx.ports),
        port_values=[fin(e) for e in ctx.port_values],
        G=fin_mat(G),
        D=fin_mat(D),
        rhs=[fin(e) for e in rhs],
        port_outputs=[fin(e) for e in port_outputs],
        outputs={k: OutputVar(k, o.unit, fin(o.expr)) for k, o in outputs.items()},
        jacobian=fin_mat(jac) if jac is not None else None,
        representation=ctx.representation,
        physical=physical,
        metadata={"n_nodes": len(ctx.nodes) - 1},
    )
    if check:
        _check_structure(ir)
    return ir


# ----------------------------------------------------------------------------
# Validation and nodes
# ----------------------------------------------------------------------------
def _validate_components(comps: list[Component]) -> None:
    """Reject duplicate names and out-of-range parameters among the flattened
    components, as :class:`CompileError`."""
    seen: dict[str, Component] = {}
    for c in comps:
        if c.name in seen:
            raise CompileError(
                f"two components are named {c.name!r}; give one of them a name="
            )
        seen[c.name] = c
        for p in c.parameters.values():
            try:
                p.validate(c.name)
            except ValueError as e:
                raise CompileError(f"invalid parameter: {e}") from None


def _build_nodes(comps: list[Component], links: list[Connection]) -> _Ctx:
    """Union-find the connected ports into nodes and start the context.

    All :class:`Ground` ports merge into node 0, the reference. Refuses a node
    that mixes domains, a port that belongs to no listed component, and an
    unconnected port of a multi-port component; warns about a loose ground.
    """
    parent: dict[Port, Port] = {}

    def find(t: Port) -> Port:
        while parent.setdefault(t, t) is not t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    def union(a: Port, b: Port) -> None:
        ra, rb = find(a), find(b)
        if ra is not rb:
            parent[ra] = rb

    ports: list[Port] = [t for c in comps for t in c.ports.values()]
    for t in ports:
        find(t)
    ref_terminals = [t for c in comps if isinstance(c, Ground) for t in c.ports.values()]
    for link in links:
        for t in link:
            if t not in parent:
                raise CompileError(
                    f"port {t.qualified} belongs to a component that is not in the "
                    "system; add it with System.add or connect it"
                )
        for t in link[1:]:
            union(link[0], t)
    for t in ref_terminals[1:]:
        union(ref_terminals[0], t)

    groups: dict[Port, list[Port]] = defaultdict(list)
    for t in ports:
        groups[find(t)].append(t)

    nodes: list[_Node] = []
    node_of: dict[Port, _Node] = {}
    ref = _Node(0)
    ref.reference = True
    ref.name = "reference"
    nodes.append(ref)
    if ref_terminals:
        ref_root = find(ref_terminals[0])
        for t in groups.pop(ref_root):
            ref.ports.append(t)
            node_of[t] = ref
    for members in groups.values():
        n = _Node(len(nodes))
        n.ports = members
        domains = {t.domain for t in members if t.domain != "any"}
        if len(domains) > 1:
            names = ", ".join(f"{t.qualified} [{t.domain}]" for t in members)
            raise CompileError(
                f"incompatible connection: {names} end up on the same node. Terminals "
                "of different domains cannot share a node; couple domains with a "
                "Transformer or a Gyrator."
            )
        n.domain = domains.pop() if domains else "any"
        n.name = (
            members[0].qualified
            if len(members) == 1
            else "+".join(sorted(t.qualified for t in members))
        )
        nodes.append(n)
        for t in members:
            node_of[t] = n

    dangling = [
        n.ports[0]
        for n in nodes[1:]
        if len(n.ports) == 1
        and not isinstance(n.ports[0].component, Ground)
        and len(n.ports[0].component.ports) > 1
    ]
    if dangling:
        names = ", ".join(t.qualified for t in dangling)
        raise CompileError(
            f"port(s) not connected to anything: {names}. Every port of a "
            "two-port component must be connected; use Ground (Fixed, Atmosphere) "
            "for the ones that are nailed down."
        )
    linked = {t for link in links for t in link}
    for t in ref_terminals:
        if t not in linked:
            warnings.warn(
                f"{t.qualified} is not connected to anything",
                UserWarning,
                stacklevel=4,
            )
    return _Ctx(comps=comps, nodes=nodes, ref=ref, branches=[], node_of=node_of)


def _composites(components: list[Component]) -> list[Component]:
    """Every composite in the tree, outermost first."""

    out: list[Component] = []

    def visit(c: Component) -> None:
        if isinstance(c, Composite):
            out.append(c)
            for part in c.parts:
                visit(part)

    for c in components:
        visit(c)
    return out


def _leaves(c: Component) -> list[Component]:
    """The non-composite components under ``c`` (``c`` itself if it is one)."""
    if isinstance(c, Composite):
        return [leaf for part in c.parts for leaf in _leaves(part)]
    return [c]


def _collect_branches(ctx: _Ctx) -> None:
    """Ask every component for its branches and fill ``ctx.branches`` and
    ``ctx.storage_branches``. A heat branch or a non-power-conjugate (thermal)
    storage marks the representation pseudo-port-Hamiltonian; a system with no
    storage is refused."""
    for c in ctx.comps:
        for b in c.branches():
            if b.a.domain != "any" and b.a.domain not in DOMAINS:
                raise CompileError(f"{c.name}: unknown domain {b.a.domain!r}")
            ctx.branches.append(b)
            if isinstance(b, HeatBranch):
                ctx.representation = "pseudo-port-hamiltonian"
            if isinstance(b, StorageBranch):
                if b.kind not in ("across", "through"):
                    raise CompileError(
                        f"{c.name}: storage kind must be across or through"
                    )
                ctx.storage_branches.append(b)
                if (
                    b.domain == "thermal"
                    or not DOMAINS.get(b.domain, DOMAINS["electrical"]).power_conjugate
                ):
                    ctx.representation = "pseudo-port-hamiltonian"
    if not ctx.storage_branches:
        raise CompileError(
            "the system stores no energy: it has no capacitor, inductor, mass, spring, "
            "tank, inertia or thermal mass, so there is no state to integrate"
        )


def _node(ctx: _Ctx, t: Port | None) -> _Node:
    """The node of a port; ``None`` is the reference."""
    return ctx.ref if t is None else ctx.node_of[t]


def _declare_symbols(ctx: _Ctx) -> None:
    """Create the model's variables from the collected branches.

    Parameters become :class:`ParamVar` entries plus a renaming from the
    component's identity-based symbol to ``<component>.<name>``. Each storage
    yields a state symbol, an energy ``H(x)``, its gradient and an effort
    placeholder ``__effort.i``. Each source becomes a port: an input symbol
    when its value is ``None``, otherwise a ``<name>.<quantity>`` parameter;
    inputs are listed first.
    """
    for c in ctx.comps:
        for pname, p in c.parameters.items():
            ctx.params.append(
                ParamVar(
                    f"{c.name}.{pname}", p.value, p.unit, c.name, p.description or pname
                )
            )
            ctx.rename[c.symbol(pname)] = ex.symbol("param", f"{c.name}.{pname}")
    for i, b in enumerate(ctx.storage_branches):
        sname = f"{b.component.name}.{b.state}"
        s = ex.symbol("state", sname)
        e = ex.symbol("param", f"__effort.{i}")
        h = b.energy(s)
        ctx.states.append(
            StateVar(
                sname,
                b.state_unit,
                b.component.name,
                b.quantity,
                float(b.initial),
                b.kind,
            )
        )
        ctx.state_syms.append(s)
        ctx.effort_syms.append(e)
        ctx.energies.append(h)
        ctx.grad_H.append(h.diff(s))
    # ports: inputs first, then constant sources
    sources = [b for b in ctx.branches if isinstance(b, SourceBranch)]
    for b in sorted(sources, key=lambda b: b.value is not None):
        pname = b.component.name
        if b.value is None:
            ctx.inputs.append(InputVar(pname, b.unit, b.component.name, b.quantity))
            ctx.port_values.append(ex.symbol("input", pname))
        else:
            ctx.params.append(
                ParamVar(
                    f"{pname}.{b.quantity}", b.value, b.unit, b.component.name, b.quantity
                )
            )
            ctx.port_values.append(ex.symbol("param", f"{pname}.{b.quantity}"))
        ctx.ports.append(pname)
        ctx.port_branches.append(b)


# ----------------------------------------------------------------------------
# Potentials
# ----------------------------------------------------------------------------
def _pins(ctx: _Ctx) -> list[_Pin]:
    """The branches whose across variable is known before any potential is:
    across storages (their effort), across sources (their port value) and
    series resistors (their placeholder)."""
    pins: list[_Pin] = []
    for b in ctx.branches:
        if isinstance(b, StorageBranch) and b.kind == "across":
            i = ctx.storage_branches.index(b)
            pins.append(_Pin(b, _node(ctx, b.a), _node(ctx, b.b), ctx.effort_syms[i]))
        elif isinstance(b, SourceBranch) and b.kind == "across":
            k = ctx.port_branches.index(b)
            pins.append(_Pin(b, _node(ctx, b.a), _node(ctx, b.b), ctx.port_values[k]))
        elif isinstance(b, ResistorBranch) and b in ctx.series:
            sym, _ = ctx.series[b]
            pins.append(_Pin(b, _node(ctx, b.a), _node(ctx, b.b), sym))
    return pins


def _series_resistors(ctx: _Ctx) -> None:
    """Find resistors with an inverse law whose flow is fixed by a series
    element, and give each a placeholder for its across variable.

    The flow of a branch is known before any potential is when the branch is a
    through storage (its state), a through source (its input) or a resistor
    already found here. A resistor shares that flow when one of its nodes has
    exactly those two branches on it.
    """
    inc = _incident(ctx)
    known: dict[Branch, Expr] = {}  # branch -> through a -> b
    for b in ctx.branches:
        if isinstance(b, StorageBranch) and b.kind == "through":
            known[b] = ctx.effort_syms[ctx.storage_branches.index(b)]
        elif isinstance(b, SourceBranch) and b.kind == "through":
            known[b] = -ctx.port_values[ctx.port_branches.index(b)]
    candidates = [
        b for b in ctx.branches if isinstance(b, ResistorBranch) and b.inverse is not None
    ]
    progress = True
    while progress:
        progress = False
        for r in candidates:
            if r in known:
                continue
            for end in (r.a, r.b):
                node = _node(ctx, end)
                if node is ctx.ref or len(inc[node]) != 2:
                    continue
                (b1, _, s1), (b2, _, s2) = inc[node]
                other, s_other, s_r = (b2, s2, s1) if b1 is r else (b1, s1, s2)
                if other not in known or isinstance(other, TwoPortBranch):
                    continue
                # conservation at a two-branch node: s_r i_r + s_other i_other = 0
                i_r = -s_r * s_other * known[other]
                sym = ex.symbol("param", f"__inv.{len(ctx.series)}.{r.component.name}")
                ctx.series[r] = (sym, i_r)
                known[r] = i_r
                progress = True
                break
    for r in candidates:
        if r not in known and r.law is None:
            raise CompileError(
                f"{r.component.name} gives its across variable as a function of its "
                "flow, so its flow must be set by a series element: an inductor, "
                "spring or fluid inertance, a flow or current source, or another such "
                "element. Put one in series with it, or give it a law= of the across "
                "variable instead."
            )


def _inverse_map(ctx: _Ctx, structural: bool) -> dict[Expr, Expr]:
    """What the placeholders of series resistors stand for in each form:
    the inverse law of the flow, or a frozen secant resistance times the flow."""
    out: dict[Expr, Expr] = {}
    for k, (r, (sym, i)) in enumerate(ctx.series.items()):
        assert r.inverse is not None
        if structural:
            res = ex.symbol("param", f"__secantR.{k}.{r.component.name}")
            ctx.secants[res] = _secant_inverse(r, i)
            out[sym] = res * i
        else:
            out[sym] = r.inverse(i)
    return out


def _secant_inverse(r: ResistorBranch, i: Expr) -> Expr:
    """inverse(i) / i as a resistance: exact for a linear inverse, and at i = 0
    the slope there when finite, zero otherwise (mirror of :func:`_secant`)."""
    s = ex.symbol("param", "__i")
    assert r.inverse is not None
    law = ex.trace(r.inverse, s)
    d = law.diff(s)
    if not d.depends_on_symbol(s) and law.substitute({s: ex.const(0.0)}).is_zero():
        return d.substitute({s: i})
    try:
        at_zero: Expr = d.substitute({s: ex.const(0.0)})
        if at_zero.is_const and not math.isfinite(at_zero.value or 0.0):
            at_zero = ex.const(0.0)
    except ZeroDivisionError:
        at_zero = ex.const(0.0)
    return ex.where(abs(i) > _TINY, law.substitute({s: i}) / i, at_zero)


def _pin_potentials(ctx: _Ctx) -> list[tuple[Expr, list[_Node]]]:
    """Assign potentials. Returns the unknown symbols with their node groups."""
    pins = _pins(ctx)
    adj: dict[_Node, list[_Pin]] = defaultdict(list)
    for p in pins:
        if p.node_a is p.node_b:
            raise CompileError(
                f"{p.branch.component.name} is connected to itself at both ends "
                f"({_terminal_str(p.branch.a)} and {_terminal_str(p.branch.b)})"
            )
        adj[p.node_a].append(p)
        adj[p.node_b].append(p)

    visited: set[_Node] = set()
    unknowns: list[tuple[Expr, list[_Node]]] = []

    def bfs(root: _Node, base: Expr) -> list[_Node]:
        ctx.potentials[root] = base
        visited.add(root)
        queue = [root]
        members = [root]
        used: set[int] = set()
        while queue:
            n = queue.pop(0)
            for p in adj[n]:
                if id(p) in used:
                    continue
                used.add(id(p))
                other = p.node_b if p.node_a is n else p.node_a
                if other in visited:
                    raise CompileError(_dependent_message(p, n, other, ctx))
                sign = 1.0 if p.node_a is n else -1.0
                # potential(a) - potential(b) = across
                ctx.potentials[other] = (
                    ctx.potentials[n] - p.across
                    if sign > 0
                    else ctx.potentials[n] + p.across
                )
                visited.add(other)
                ctx.pin_parent[other] = p
                ctx.pin_order.append(other)
                queue.append(other)
                members.append(other)
        return members

    bfs(ctx.ref, ex.const(0.0))
    for n in ctx.nodes[1:]:
        if n in visited:
            continue
        sym = ex.symbol("param", f"__phi.{n.index}")
        members = bfs(n, sym)
        unknowns.append((sym, members))
    return unknowns


def _dependent_message(p: _Pin, n: _Node, other: _Node, ctx: _Ctx) -> str:
    """Name the storages and sources on the loop closed by pin ``p``."""

    def chain(node: _Node) -> list[str]:
        out: list[str] = []
        seen: set[int] = set()
        while node in ctx.pin_parent and id(node) not in seen:
            seen.add(id(node))
            pin = ctx.pin_parent[node]
            out.append(pin.branch.component.name)
            node = pin.node_b if pin.node_a is node else pin.node_a
        return out

    a, b = chain(n), chain(other)
    # drop the common tail (the part of both chains above the loop)
    while a and b and a[-1] == b[-1]:
        a.pop()
        b.pop()
    involved = [p.branch.component.name, *a, *b]
    what = ", ".join(dict.fromkeys(involved))
    return (
        f"dependent storages or sources: {what} form a loop that fixes the same "
        "potential twice. Two capacitors in parallel, two inertias on one shaft, two "
        "masses rigidly joined, a voltage source across a capacitor or a tank connected "
        "straight to a pressure source all do this. Merge the two stores into one, or "
        "put a resistor, pipe, damper or a stiff spring between them."
    )


def _across(ctx: _Ctx, b: Branch, second: bool = False) -> Expr:
    """``potential(a) - potential(b)`` of a branch (of its second side for a
    two-port when ``second``), with series-resistor placeholders substituted
    by the current ``ctx.inverse_map``."""
    if second:
        assert isinstance(b, TwoPortBranch)
        v = ctx.potentials[_node(ctx, b.a2)] - ctx.potentials[_node(ctx, b.b2)]
    else:
        v = ctx.potentials[_node(ctx, b.a)] - ctx.potentials[_node(ctx, b.b)]
    return v.substitute(ctx.inverse_map) if ctx.inverse_map else v


def _through_nonpin(ctx: _Ctx, b: Branch, structural: bool, side: int = 1) -> Expr | None:
    """Through variable (a -> b) of a branch whose through is known once the
    potentials are; None for pin branches (storage_across, source_across)."""
    if isinstance(b, StorageBranch):
        if b.kind == "across":
            return None
        return ctx.effort_syms[ctx.storage_branches.index(b)]
    if isinstance(b, SourceBranch):
        if b.kind == "across":
            return None
        return -ctx.port_values[ctx.port_branches.index(b)]
    if isinstance(b, ResistorBranch):
        if b in ctx.series:
            return None  # a pin: its through is the series flow
        if b.law is None:  # pragma: no cover - refused in _series_resistors
            raise CompileError(f"{b.component.name}: no law of the across variable")
        v = _across(ctx, b)
        if structural:
            # a frozen conductance, so that d(through)/d(effort) reads off the
            # conductance itself and not its derivative
            sym = ex.symbol("param", f"__secant.{len(ctx.secants)}.{b.component.name}")
            ctx.secants[sym] = _secant(b, v)
            return sym * v
        return b.law(v)
    if isinstance(b, TwoPortBranch):
        i1, i2 = ctx.twoport_currents[b]
        return i1 if side == 1 else i2
    if isinstance(b, HeatBranch):
        power = _heat_power(ctx, b)
        if structural:
            # frozen: heat generation is not part of J or R. It is substituted
            # back after the structure has been read off, like the secants.
            sym = ex.symbol("param", f"__heat.{len(ctx.secants)}.{b.component.name}")
            ctx.secants[sym] = -power
            return sym
        return -power
    raise CompileError(f"unknown branch type {type(b).__name__}")


def _heat_power(ctx: _Ctx, b: HeatBranch) -> Expr:
    """Sum of across * through over the resistor branches of ``b.sources``."""
    total = ex.const(0.0)
    found = False
    for r in ctx.branches:
        if isinstance(r, ResistorBranch) and r.component in b.sources:
            found = True
            v = _across(ctx, r)
            i = ctx.series[r][1] if r in ctx.series else r.law(v)  # type: ignore[misc]
            total = total + v * i
    if not found:
        names = ", ".join(c.name for c in b.sources) or "nothing"
        raise CompileError(
            f"{b.component.name}: heat sources ({names}) have no resistor or damper "
            "branch whose losses could be turned into heat"
        )
    return total


def _secant(b: ResistorBranch, v: Expr) -> Expr:
    """law(v) / v as a conductance: exact for a linear law, and at v = 0 the
    slope of the law there when that slope is finite, zero otherwise."""
    vs = ex.symbol("param", "__v")
    assert b.law is not None
    law = ex.trace(b.law, vs)
    d = law.diff(vs)
    if not d.depends_on_symbol(vs) and law.substitute({vs: ex.const(0.0)}).is_zero():
        return d.substitute({vs: v})
    try:
        at_zero: Expr = d.substitute({vs: ex.const(0.0)})
        if at_zero.is_const and not math.isfinite(at_zero.value or 0.0):
            at_zero = ex.const(0.0)
    except ZeroDivisionError:
        at_zero = ex.const(0.0)
    return ex.where(abs(v) > _TINY, law.substitute({vs: v}) / v, at_zero)


def _incident(ctx: _Ctx) -> dict[_Node, list[tuple[Branch, int, float]]]:
    """node -> [(branch, side, sign)] with sign +1 if the branch leaves the node."""
    inc: dict[_Node, list[tuple[Branch, int, float]]] = defaultdict(list)
    for b in ctx.branches:
        inc[_node(ctx, b.a)].append((b, 1, 1.0))
        inc[_node(ctx, b.b)].append((b, 1, -1.0))
        if isinstance(b, TwoPortBranch):
            inc[_node(ctx, b.a2)].append((b, 2, 1.0))
            inc[_node(ctx, b.b2)].append((b, 2, -1.0))
    return inc


def _solve_unknowns(ctx: _Ctx, unknown_groups: list[tuple[Expr, list[_Node]]]) -> None:
    """Determine the unpinned potentials and the two-port currents.

    One conservation equation per unknown node group (sum of non-pin
    throughs over its nodes) plus the across and through relations of each
    two-port form a system that must be linear in the unknowns; a nonlinear
    law there is refused as an algebraic loop. The solution is substituted
    into ``ctx.potentials`` and ``ctx.twoport_currents``.
    """
    twoports = [b for b in ctx.branches if isinstance(b, TwoPortBranch)]
    for k, b in enumerate(twoports):
        ctx.twoport_currents[b] = (
            ex.symbol("param", f"__i.{k}.1"),
            ex.symbol("param", f"__i.{k}.2"),
        )
    unknown_syms: list[Expr] = [s for s, _ in unknown_groups]
    for b in twoports:
        unknown_syms.extend(ctx.twoport_currents[b])
    if not unknown_syms:
        return

    inc = _incident(ctx)
    equations: list[tuple[Expr, str]] = []
    for _sym, members in unknown_groups:
        total = ex.const(0.0)
        for n in members:
            for b, side, sign in inc[n]:
                i = _through_nonpin(ctx, b, structural=False, side=side)
                if i is None:
                    continue  # pin branches are internal to the group
                total = total + sign * i
        names = ", ".join(n.name for n in members)
        equations.append((total, f"conservation at node(s) {names}"))
    for b in twoports:
        i1, i2 = ctx.twoport_currents[b]
        v1, v2 = _across(ctx, b), _across(ctx, b, second=True)
        if b.kind == "transformer":
            equations.append((v2 - b.ratio * v1, f"{b.component.name} across relation"))
            equations.append((i1 + b.ratio * i2, f"{b.component.name} through relation"))
        elif b.kind == "gyrator":
            equations.append((v2 - b.ratio * i1, f"{b.component.name} across relation"))
            equations.append((v1 + b.ratio * i2, f"{b.component.name} through relation"))
        else:
            raise CompileError(f"{b.component.name}: unknown two-port kind {b.kind!r}")

    # linear extraction
    n = len(unknown_syms)
    M: list[list[Expr]] = []
    rhs: list[Expr] = []
    zero_map = {s: ex.const(0.0) for s in unknown_syms}
    for eq, what in equations:
        row = []
        for s in unknown_syms:
            coef = eq.diff(s)
            if any(coef.depends_on_symbol(u) for u in unknown_syms):
                raise CompileError(
                    f"nonlinear algebraic loop: the {what} involves a nonlinear law whose "
                    "across variable is not fixed by any storage or source. Put a linear "
                    "element there, or add a storage (a small capacitance, mass or "
                    "compliance) to the node."
                )
            row.append(coef)
        M.append(row)
        rhs.append(-eq.substitute(zero_map))
    if len(M) != n:  # pragma: no cover - by construction
        raise CompileError("internal: equation count does not match unknowns")
    solution = _solve_linear(M, rhs, unknown_syms)
    mapping = dict(zip(unknown_syms, solution, strict=True))
    # substitute everywhere potentials / currents were expressed in unknowns
    for node in list(ctx.potentials):
        ctx.potentials[node] = ctx.potentials[node].substitute(mapping)
    for b in twoports:
        i1, i2 = ctx.twoport_currents[b]
        ctx.twoport_currents[b] = (mapping[i1], mapping[i2])


def _solve_linear(M: list[list[Expr]], b: list[Expr], syms: list[Expr]) -> list[Expr]:
    """Gaussian elimination over symbolic entries, constants pivoted first."""
    n = len(syms)
    A = [row[:] + [b[i]] for i, row in enumerate(M)]
    for col in range(n):
        # pick a pivot row: prefer a nonzero constant, then any nonzero
        pivot = None
        for r in range(col, n):
            e = A[r][col]
            if e.is_const and e.value != 0.0:
                pivot = r
                break
        if pivot is None:
            for r in range(col, n):
                if not A[r][col].is_zero():
                    pivot = r
                    break
        if pivot is None:
            raise CompileError(
                f"the network equations are singular: {syms[col].name.replace('__phi.', 'node ').replace('__i.', 'two-port current ')} "
                "cannot be determined. A node is connected only through current-type "
                "sources or through-storages (an inductor loop with a current source, "
                "a mass driven only by a force with no path to ground), or two "
                "constraints contradict each other."
            )
        A[col], A[pivot] = A[pivot], A[col]
        p = A[col][col]
        for r in range(n):
            if r == col or A[r][col].is_zero():
                continue
            f = A[r][col] / p
            A[r] = [A[r][c] - f * A[col][c] for c in range(n + 1)]
        A[col] = [A[col][c] / p for c in range(n + 1)]
    return [A[i][n] for i in range(n)]


# ----------------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------------
def _assemble(
    ctx: _Ctx, structural: bool
) -> tuple[list[Expr], list[Expr], dict[Component, ComponentQuantities]]:
    """Build ``dx/dt`` for every state and the conjugate output of every port.

    The through variable of each pin branch is recovered by conservation,
    peeling the pin trees from the leaves inward. An across storage's rate is
    its through, a through storage's rate is its across. With ``structural``
    the nonlinear laws are frozen secant conductances (placeholders recorded
    in ``ctx.secants``); otherwise the laws stand as written and the per-
    component quantities for :meth:`Component.extra_outputs` are collected.
    """
    inc = _incident(ctx)
    ctx.inverse_map = _inverse_map(ctx, structural)
    n_states = len(ctx.storage_branches)
    rhs: list[Expr | None] = [None] * n_states
    port_out: list[Expr | None] = [None] * len(ctx.port_branches)
    pin_through: dict[Branch, Expr] = {}

    def through(b: Branch, side: int) -> Expr:
        if b in pin_through:
            return pin_through[b]
        val = _through_nonpin(ctx, b, structural, side)
        if val is None:  # pragma: no cover - peeled before use
            raise CompileError(f"internal: through of {b.component.name} not yet known")
        return val

    # peel pin trees from the leaves inward
    for node in reversed(ctx.pin_order):
        parent_pin = ctx.pin_parent[node]
        total = ex.const(0.0)
        sign_parent = 0.0
        for b, side, sign in inc[node]:
            if b is parent_pin.branch:
                sign_parent += sign
                continue
            total = total + sign * through(b, side)
        # conservation at the node: sign_parent * i_parent + total = 0
        pin_through[parent_pin.branch] = -total if sign_parent > 0 else total

    # states
    for i, b in enumerate(ctx.storage_branches):
        if b.kind == "across":
            if b not in pin_through:  # pragma: no cover - every across storage is a pin
                raise CompileError(f"internal: {b.component.name} through unknown")
            rhs[i] = pin_through[b]
        else:
            rhs[i] = _across(ctx, b)
    # port outputs: delivered conjugate
    for k, b in enumerate(ctx.port_branches):
        if b.kind == "across":
            port_out[k] = -pin_through[b]
        else:
            port_out[k] = _across(ctx, b)

    # quantities per component (executable form)
    quantities: dict[Component, ComponentQuantities] = {}
    if not structural:
        for b in ctx.branches:
            q = quantities.setdefault(b.component, ComponentQuantities())
            label = b.label or b.component.name
            q.across[label] = _across(ctx, b)
            q.through[label] = through(b, 1)
            if isinstance(b, TwoPortBranch):
                label2 = b.label2 or f"{b.component.name}.2"
                q.across[label2] = _across(ctx, b, second=True)
                q.through[label2] = through(b, 2)
            if isinstance(b, StorageBranch):
                q.state[b.state] = ctx.state_syms[ctx.storage_branches.index(b)]
        for c in ctx.comps:
            q = quantities.setdefault(c, ComponentQuantities())
            for pname in c.parameters:
                q.params[pname] = c.symbol(pname)
    return (
        [r for r in rhs if r is not None],
        [p for p in port_out if p is not None],
        quantities,
    )


def _extract_structure(
    ctx: _Ctx, rhs: list[Expr], port_out: list[Expr]
) -> tuple[list[list[Expr]], list[list[Expr]], list[list[Expr]], list[list[Expr]]]:
    """Read ``J, R, G, D`` off the structural form by differentiation.

    ``A = d(rhs)/d(effort)`` splits into ``J = (A - A^T)/2`` and
    ``R = -(A + A^T)/2``; ``G = d(rhs)/d(port)`` and ``D = d(port_out)/d(port)``.
    Secant placeholders and efforts are substituted back afterwards.
    """
    n = len(ctx.storage_branches)
    P = len(ctx.ports)
    effort_map = dict(zip(ctx.effort_syms, ctx.grad_H, strict=True))

    def finish(e: Expr) -> Expr:
        return e.substitute(ctx.secants).substitute(effort_map)

    A = [[rhs[i].diff(ctx.effort_syms[j]) for j in range(n)] for i in range(n)]
    G = [[rhs[i].diff(ctx.port_values[k]) for k in range(P)] for i in range(n)]
    D = [[port_out[k].diff(ctx.port_values[m]) for m in range(P)] for k in range(P)]
    J = [[finish((A[i][j] - A[j][i]) / 2) for j in range(n)] for i in range(n)]
    R = [[finish(-(A[i][j] + A[j][i]) / 2) for j in range(n)] for i in range(n)]
    G = [[finish(g) for g in row] for row in G]
    D = [[finish(d) for d in row] for row in D]
    return J, R, G, D


def _outputs(
    ctx: _Ctx,
    quantities: dict[Component, ComponentQuantities],
    effort_map: dict[Expr, Expr],
) -> dict[str, OutputVar]:
    """The named outputs of the model: every state and its component's
    energy, the across, through and power of every branch (heat flow for a
    heat branch, both sides of a two-port), each component's and composite's
    ``extra_outputs``, and the total ``energy``."""
    out: dict[str, OutputVar] = {}

    def put(name: str, unit: str, e: Expr) -> None:
        out[name] = OutputVar(name, unit, e.substitute(effort_map))

    for s, e, h in zip(ctx.states, ctx.state_syms, ctx.energies, strict=True):
        put(s.name, s.unit, e)
        put(f"{s.component}.energy", "J", h)
    for b in ctx.branches:
        q = quantities[b.component]
        dom = DOMAINS.get(b.domain)
        label = b.label or b.component.name
        if isinstance(b, HeatBranch):
            # the heat delivered into the thermal port, positive when warming
            put(f"{label}.heat_flow", "W", -q.through[label])
            continue
        if dom is not None:
            put(f"{label}.{dom.across}", dom.across_unit, q.across[label])
            put(f"{label}.{dom.through}", dom.through_unit, q.through[label])
            put(f"{label}.power", "W", q.across[label] * q.through[label])
        if isinstance(b, TwoPortBranch):
            dom2 = DOMAINS.get(b.a2.domain if b.a2 is not None else b.domain)
            label2 = b.label2 or f"{b.component.name}.2"
            if dom2 is not None:
                put(f"{label2}.{dom2.across}", dom2.across_unit, q.across[label2])
                put(f"{label2}.{dom2.through}", dom2.through_unit, q.through[label2])
    for c in ctx.comps:
        for name, (unit, e) in c.extra_outputs(quantities[c]).items():
            put(f"{c.name}.{name}", unit, e)
    # composites see the quantities of all their parts, keyed by part label
    for c in ctx.composites:
        merged = ComponentQuantities()
        for part in _leaves(c):
            q = quantities.get(part)
            if q is None:
                continue
            merged.across.update(q.across)
            merged.through.update(q.through)
            merged.state.update({f"{part.name}.{k}": v for k, v in q.state.items()})
            merged.params.update({f"{part.name}.{k}": v for k, v in q.params.items()})
        for name, (unit, e) in c.extra_outputs(merged).items():
            put(f"{c.name}.{name}", unit, e)
    total = ex.const(0.0)
    for h in ctx.energies:
        total = total + h
    put("energy", "J", total)
    return out


def _physical_ir(system: System, ctx: _Ctx, name: str | None) -> PhysicalSystemIR:
    """The structural record of the system: components, nodes with their
    ports, branches with their kind and end nodes, and the variables."""
    comps = [
        ComponentRecord(
            c.name, c.type_name, c.domain, tuple(c.parameters), tuple(c.ports)
        )
        for c in ctx.comps
    ]
    nodes = [
        NodeRecord(n.name, n.domain, tuple(t.qualified for t in n.ports), n.reference)
        for n in ctx.nodes
        if n.ports or n.reference
    ]
    branches = []
    for b in ctx.branches:
        kind = type(b).__name__.replace("Branch", "").lower()
        if isinstance(b, (StorageBranch, SourceBranch)):
            kind = f"{kind}_{b.kind}"
        if isinstance(b, TwoPortBranch):
            kind = b.kind
        branches.append(
            BranchRecord(
                b.component.name, kind, _node(ctx, b.a).name, _node(ctx, b.b).name
            )
        )
    return PhysicalSystemIR(
        name=name or system.name,
        components=comps,
        nodes=nodes,
        branches=branches,
        states=list(ctx.states),
        params=list(ctx.params),
        inputs=list(ctx.inputs),
        metadata={"representation": ctx.representation},
    )


def _check_structure(ir: PHSIR) -> None:
    """Evaluate R at the initial state and warn if it is not PSD."""
    import numpy as np

    env = ir.environment(ir.initial_state())
    try:
        R = np.array([[e.evaluate(env) for e in row] for row in ir.R], dtype=float)
    except (KeyError, ZeroDivisionError, ValueError):
        return
    if R.size == 0 or not np.all(np.isfinite(R)):
        return
    eig = np.linalg.eigvalsh((R + R.T) / 2)
    scale = max(1.0, float(np.max(np.abs(R))))
    if eig.min() < -1e-9 * scale:
        warnings.warn(
            f"dissipation matrix R is not positive semidefinite at the initial state "
            f"(smallest eigenvalue {eig.min():.3e}); a resistor or damper law returns "
            "power to the system. Check the sign of the nonlinear laws.",
            StructureWarning,
            stacklevel=3,
        )


def summary_text(ir: PHSIR, solver: str | None = None, backend: str | None = None) -> str:
    """The human-readable summary printed by ``Model.summary()``."""
    lines = [f"System: {ir.name}", ""]
    if ir.physical is not None:
        lines.append("Components:")
        for c in ir.physical.components:
            lines.append(f"  {c.name:<28s} {c.type} [{c.domain}]")
        lines.append("")
    lines.append("States:")
    for s in ir.states:
        lines.append(f"  {s.name:<28s} {s.quantity} [{s.unit}]  x0 = {s.initial:g}")
    lines.append("")
    if ir.inputs:
        lines.append("Inputs:")
        for i in ir.inputs:
            lines.append(f"  {i.name:<28s} {i.quantity} [{i.unit}]")
        lines.append("")
    consts = [p for p in ir.ports if p not in ir.input_names()]
    if consts:
        lines.append("Constant sources:")
        for p in consts:
            lines.append(f"  {p}")
        lines.append("")
    lines.append("Parameters:")
    for p in ir.params:
        lines.append(f"  {p.name:<28s} {p.value:<12g} {p.unit}")
    lines.append("")
    lines.append(f"Outputs: {len(ir.outputs)} named quantities (model.outputs())")
    lines.append(f"Representation: {ir.representation}")
    if solver:
        lines.append(f"Solver: {solver}")
    if backend:
        lines.append(f"Backend: {backend}")
    return "\n".join(lines)
