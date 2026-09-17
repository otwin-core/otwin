"""Intermediate representations: what the compiler produces.

Two levels.

:class:`PhysicalSystemIR` is the *resolved description*: components, nodes,
branches, states, parameters and inputs, with every name unique and every
connection checked. It says what the system is. It carries no equations.

:class:`PHSIR` is the *mathematical form* the runtime executes. It is a
port-Hamiltonian system with every entry a symbolic :class:`~otwin.expr.Expr`::

    dx/dt = (J(x) - R(x)) grad_H(x) + G(x) u
        y = G(x)^T grad_H(x) + D(x) u

plus the right-hand side already multiplied out (``rhs``), the Jacobian of
that right-hand side, and the named outputs a user can record. Both levels
serialise to JSON, and :meth:`PHSIR.lower` produces the flat table the Rust
engine loads.

Neither class is something a user writes by hand. Read them through
``model.ir()`` when a compiled model does something you did not expect.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from . import expr as ex
from .expr import Expr

__all__ = [
    "StateVar",
    "ParamVar",
    "InputVar",
    "OutputVar",
    "ComponentRecord",
    "NodeRecord",
    "BranchRecord",
    "PhysicalSystemIR",
    "PHSIR",
]

IR_VERSION = "1"


@dataclass(frozen=True)
class StateVar:
    """One entry of the state vector."""

    name: str
    unit: str
    component: str
    quantity: str
    initial: float
    kind: str  # "across" (state is the integral of a through) or "through"


@dataclass(frozen=True)
class ParamVar:
    """A physical parameter. Stays symbolic through compilation, so it can be
    changed on the compiled model and estimated from data."""

    name: str
    value: float
    unit: str
    component: str
    quantity: str


@dataclass(frozen=True)
class InputVar:
    """An external input: the value of a source left open by the user."""

    name: str
    unit: str
    component: str
    quantity: str


@dataclass(frozen=True)
class OutputVar:
    """A named quantity that can be recorded from a trajectory."""

    name: str
    unit: str
    expr: Expr


@dataclass(frozen=True)
class ComponentRecord:
    name: str
    type: str
    domain: str
    parameters: tuple[str, ...]
    ports: tuple[str, ...]


@dataclass(frozen=True)
class NodeRecord:
    name: str
    domain: str
    ports: tuple[str, ...]  # "component.port"
    reference: bool


@dataclass(frozen=True)
class BranchRecord:
    component: str
    kind: str
    node_a: str
    node_b: str


@dataclass
class PhysicalSystemIR:
    """The resolved physical description. What the user built, checked."""

    name: str
    components: list[ComponentRecord]
    nodes: list[NodeRecord]
    branches: list[BranchRecord]
    states: list[StateVar]
    params: list[ParamVar]
    inputs: list[InputVar]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ir_version": IR_VERSION,
            "level": "physical",
            "name": self.name,
            "components": [asdict(c) for c in self.components],
            "nodes": [asdict(n) for n in self.nodes],
            "branches": [asdict(b) for b in self.branches],
            "states": [asdict(s) for s in self.states],
            "params": [asdict(p) for p in self.params],
            "inputs": [asdict(i) for i in self.inputs],
            "metadata": self.metadata,
        }

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), **kw)


@dataclass
class PHSIR:
    """The port-Hamiltonian form with symbolic entries. Executed by the runtime."""

    name: str
    states: list[StateVar]
    params: list[ParamVar]
    inputs: list[InputVar]
    energy: Expr
    grad_H: list[Expr]
    J: list[list[Expr]]
    R: list[list[Expr]]
    ports: list[str]  # one per source, inputs first
    port_values: list[Expr]  # the u of each port: an input symbol or a constant parameter
    G: list[list[Expr]]  # n x P
    D: list[list[Expr]]  # P x P
    rhs: list[Expr]
    port_outputs: list[Expr]  # y, length P: the conjugate of each port's u
    outputs: dict[str, OutputVar]
    jacobian: list[list[Expr]] | None = None
    representation: str = "port-hamiltonian"
    physical: PhysicalSystemIR | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- shape
    @property
    def n_states(self) -> int:
        return len(self.states)

    @property
    def n_inputs(self) -> int:
        return len(self.inputs)

    @property
    def n_params(self) -> int:
        return len(self.params)

    @property
    def n_ports(self) -> int:
        return len(self.ports)

    def state_names(self) -> list[str]:
        return [s.name for s in self.states]

    def input_names(self) -> list[str]:
        return [i.name for i in self.inputs]

    def param_names(self) -> list[str]:
        return [p.name for p in self.params]

    def param_values(self) -> list[float]:
        return [p.value for p in self.params]

    def initial_state(self) -> list[float]:
        return [s.initial for s in self.states]

    # ------------------------------------------------------------- symbols
    def symbol_order(self) -> dict[str, int]:
        """Flat engine table: states, inputs, params, time."""
        order: dict[str, int] = {}
        for s in self.states:
            order[f"state:{s.name}"] = len(order)
        for i in self.inputs:
            order[f"input:{i.name}"] = len(order)
        for p in self.params:
            order[f"param:{p.name}"] = len(order)
        order["time:t"] = len(order)
        return order

    def environment(
        self, x: Any, u: Any = None, params: Any = None, t: float = 0.0
    ) -> dict[str, float]:
        """Build an evaluation environment for :meth:`Expr.evaluate`."""
        env: dict[str, float] = {}
        for s, v in zip(self.states, x, strict=True):
            env[f"state:{s.name}"] = float(v)
        uu = [0.0] * self.n_inputs if u is None else list(u)
        for i, v in zip(self.inputs, uu, strict=True):
            env[f"input:{i.name}"] = float(v)
        pp = self.param_values() if params is None else list(params)
        for p, v in zip(self.params, pp, strict=True):
            env[f"param:{p.name}"] = float(v)
        env["time:t"] = float(t)
        return env

    # --------------------------------------------------------- serialisation
    def to_dict(self) -> dict[str, Any]:
        def mat(m: list[list[Expr]]) -> list[list[Any]]:
            return [[e.to_json() for e in row] for row in m]

        d: dict[str, Any] = {
            "ir_version": IR_VERSION,
            "level": "phs",
            "name": self.name,
            "representation": self.representation,
            "states": [asdict(s) for s in self.states],
            "params": [asdict(p) for p in self.params],
            "inputs": [asdict(i) for i in self.inputs],
            "energy": self.energy.to_json(),
            "grad_H": [e.to_json() for e in self.grad_H],
            "J": mat(self.J),
            "R": mat(self.R),
            "ports": list(self.ports),
            "port_values": [e.to_json() for e in self.port_values],
            "G": mat(self.G),
            "D": mat(self.D),
            "rhs": [e.to_json() for e in self.rhs],
            "port_outputs": [e.to_json() for e in self.port_outputs],
            "outputs": {
                k: {"unit": o.unit, "expr": o.expr.to_json()}
                for k, o in self.outputs.items()
            },
            "jacobian": mat(self.jacobian) if self.jacobian is not None else None,
            "metadata": self.metadata,
        }
        if self.physical is not None:
            d["physical"] = self.physical.to_dict()
        return d

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), **kw)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PHSIR:
        def mat(m: list[list[Any]]) -> list[list[Expr]]:
            return [[ex.from_json(e) for e in row] for row in m]

        phys = None
        if "physical" in d:
            p = d["physical"]
            phys = PhysicalSystemIR(
                name=p["name"],
                components=[ComponentRecord(**c) for c in p["components"]],
                nodes=[NodeRecord(**n) for n in p["nodes"]],
                branches=[BranchRecord(**b) for b in p["branches"]],
                states=[StateVar(**s) for s in p["states"]],
                params=[ParamVar(**q) for q in p["params"]],
                inputs=[InputVar(**i) for i in p["inputs"]],
                metadata=p.get("metadata", {}),
            )
        return cls(
            name=d["name"],
            states=[StateVar(**s) for s in d["states"]],
            params=[ParamVar(**p) for p in d["params"]],
            inputs=[InputVar(**i) for i in d["inputs"]],
            energy=ex.from_json(d["energy"]),
            grad_H=[ex.from_json(e) for e in d["grad_H"]],
            J=mat(d["J"]),
            R=mat(d["R"]),
            ports=list(d["ports"]),
            port_values=[ex.from_json(e) for e in d["port_values"]],
            G=mat(d["G"]),
            D=mat(d["D"]),
            rhs=[ex.from_json(e) for e in d["rhs"]],
            port_outputs=[ex.from_json(e) for e in d["port_outputs"]],
            outputs={
                k: OutputVar(k, o["unit"], ex.from_json(o["expr"]))
                for k, o in d["outputs"].items()
            },
            jacobian=mat(d["jacobian"]) if d.get("jacobian") is not None else None,
            representation=d.get("representation", "port-hamiltonian"),
            physical=phys,
            metadata=d.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, s: str) -> PHSIR:
        return cls.from_dict(json.loads(s))

    def lower(self) -> dict[str, Any]:
        """The table the engine loads: symbols by index, expressions flattened."""
        order = self.symbol_order()
        n = self.n_states
        out_names = list(self.outputs)
        return {
            "n_states": n,
            "n_inputs": self.n_inputs,
            "n_params": self.n_params,
            "param_values": self.param_values(),
            "rhs": ex.lower(self.rhs, order),
            "jacobian": (
                ex.lower([e for row in self.jacobian for e in row], order)
                if self.jacobian is not None
                else None
            ),
            "energy": ex.lower([self.energy], order)[0],
            "grad_H": ex.lower(self.grad_H, order),
            "port_outputs": ex.lower(self.port_outputs, order),
            "port_values": ex.lower(self.port_values, order),
            "output_names": out_names,
            "outputs": ex.lower([self.outputs[k].expr for k in out_names], order),
        }
