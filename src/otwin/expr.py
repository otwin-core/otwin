"""Symbolic expressions: the language the compiler speaks.

Every constitutive law, energy term, control law and output the compiler
handles is an :class:`Expr`, a small immutable tree of arithmetic over
symbols. The engine evaluates, differentiates and serialises these trees
without calling back into Python, which is what keeps the numerical inner
loop out of the interpreter.

Users normally never build an ``Expr`` by hand. Components do it for them.
The one place the type surfaces is a nonlinear law::

    >>> from otwin.expr import symbol, sqrt
    >>> h = symbol("state", "tank.volume")
    >>> law = 0.6 * 0.1 * sqrt(2 * 9.81 * h)
    >>> law.diff(h)
    0.5886 / sqrt(19.62 * state:tank.volume)
    >>> round(law.evaluate({"state:tank.volume": 2.0}), 3)
    0.376

Symbols carry a *kind* (``state``, ``param``, ``input`` or ``time``) and a
name. Structural equality is by value, so ``a - a`` folds to ``0`` even when
``a`` is a subtree, and the compiler's J/R split comes out exact.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

__all__ = [
    "Expr",
    "symbol",
    "const",
    "as_expr",
    "sqrt",
    "exp",
    "log",
    "abs_",
    "tanh",
    "sin",
    "cos",
    "sign",
    "maximum",
    "minimum",
    "where",
    "piecewise",
    "interp",
    "interp_integral",
    "from_json",
]

_UNARY = {"neg", "sqrt", "exp", "log", "abs", "tanh", "sin", "cos", "sign"}
_BINARY = {"add", "sub", "mul", "div", "pow", "max", "min", "gt"}
_TERNARY = {"where"}
_SYMBOL_KINDS = ("state", "param", "input", "time")


class Expr:
    """An immutable expression tree. Build it with operators, not the constructor."""

    __slots__ = ("op", "args", "value", "kind", "name", "_hash")

    def __init__(
        self,
        op: str,
        args: tuple[Expr, ...] = (),
        value: float | None = None,
        kind: str | None = None,
        name: str | None = None,
    ) -> None:
        self.op = op
        self.args = args
        self.value = value
        self.kind = kind
        self.name = name
        self._hash = hash((op, args, value, kind, name))

    # ------------------------------------------------------------------ basics
    @property
    def is_const(self) -> bool:
        """True for a constant leaf; its number is in ``value``."""
        return self.op == "const"

    @property
    def is_symbol(self) -> bool:
        """True for a symbol leaf; ``kind`` and ``name`` identify it."""
        return self.op == "sym"

    @property
    def key(self) -> str:
        """``kind:name`` for a symbol. The evaluation environment is keyed on it."""
        if not self.is_symbol:
            raise TypeError("only symbols have a key")
        return f"{self.kind}:{self.name}"

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Expr):
            return NotImplemented
        return (
            self.op == other.op
            and self.value == other.value
            and self.kind == other.kind
            and self.name == other.name
            and self.args == other.args
        )

    def __repr__(self) -> str:
        return _fmt(self, 0)

    def __bool__(self) -> bool:
        raise TypeError("an Expr has no truth value; use is_zero() or evaluate() instead")

    def is_zero(self) -> bool:
        """True for the constant ``0``; a subtree that folds to zero already is one."""
        return self.is_const and self.value == 0.0

    def is_one(self) -> bool:
        """True for the constant ``1``."""
        return self.is_const and self.value == 1.0

    # --------------------------------------------------------------- operators
    def __add__(self, other: Any) -> Expr:
        return add(self, as_expr(other))

    def __radd__(self, other: Any) -> Expr:
        return add(as_expr(other), self)

    def __sub__(self, other: Any) -> Expr:
        return sub(self, as_expr(other))

    def __rsub__(self, other: Any) -> Expr:
        return sub(as_expr(other), self)

    def __mul__(self, other: Any) -> Expr:
        return mul(self, as_expr(other))

    def __rmul__(self, other: Any) -> Expr:
        return mul(as_expr(other), self)

    def __truediv__(self, other: Any) -> Expr:
        return div(self, as_expr(other))

    def __rtruediv__(self, other: Any) -> Expr:
        return div(as_expr(other), self)

    def __pow__(self, other: Any) -> Expr:
        return power(self, as_expr(other))

    def __rpow__(self, other: Any) -> Expr:
        return power(as_expr(other), self)

    def __neg__(self) -> Expr:
        return neg(self)

    def __pos__(self) -> Expr:
        return self

    def __abs__(self) -> Expr:
        return abs_(self)

    def __gt__(self, other: Any) -> Expr:
        return _binary("gt", self, as_expr(other))

    def __lt__(self, other: Any) -> Expr:
        return _binary("gt", as_expr(other), self)

    # Comparisons evaluate to 1.0 or 0.0, so "a >= b" is "not (b > a)".
    def __ge__(self, other: Any) -> Expr:
        return _binary("sub", as_expr(1.0), _binary("gt", as_expr(other), self))

    def __le__(self, other: Any) -> Expr:
        return _binary("sub", as_expr(1.0), _binary("gt", self, as_expr(other)))

    # ------------------------------------------------------------- analysis
    def symbols(self) -> set[Expr]:
        """Every symbol that appears in the tree."""
        out: set[Expr] = set()
        stack = [self]
        while stack:
            e = stack.pop()
            if e.is_symbol:
                out.add(e)
            stack.extend(e.args)
        return out

    def depends_on(self, kind: str) -> bool:
        """True if any symbol of the given kind (``state``, ``param``, ``input``,
        ``time``) appears in the tree."""
        return any(s.kind == kind for s in self.symbols())

    def depends_on_symbol(self, sym: Expr) -> bool:
        """True if the symbol ``sym`` appears in the tree."""
        return sym in self.symbols()

    def substitute(self, mapping: dict[Expr, Expr]) -> Expr:
        """Replace symbols (or whole subtrees) according to ``mapping``."""
        if self in mapping:
            return mapping[self]
        if not self.args:
            return self
        new_args = tuple(a.substitute(mapping) for a in self.args)
        if new_args == self.args:
            return self
        return _rebuild(self.op, new_args, self.value)

    def diff(self, sym: Expr) -> Expr:
        """Partial derivative with respect to a symbol."""
        if not sym.is_symbol:
            raise TypeError("differentiate with respect to a symbol")
        return _diff(self, sym)

    def evaluate(self, env: dict[str, float]) -> float:
        """Evaluate with a ``{"kind:name": value}`` environment. Reference only."""
        return _eval(self, env)

    def to_json(self) -> Any:
        """A nested-list form: ``["mul", ["const", 2.0], ["sym", "state", "q"]]``."""
        if self.is_const:
            return ["const", self.value]
        if self.is_symbol:
            return ["sym", self.kind, self.name]
        if self.op == "pw":
            knots, coefs = self.value  # type: ignore[misc]
            return ["pw", self.args[0].to_json(), list(knots), [list(c) for c in coefs]]
        return [self.op, *[a.to_json() for a in self.args]]

    def count_nodes(self) -> int:
        """Number of nodes in the tree, leaves included: a size measure."""
        return 1 + sum(a.count_nodes() for a in self.args)


# ------------------------------------------------------------------ constructors
def const(value: float) -> Expr:
    """A constant leaf. ``-0.0`` is folded to ``0.0`` so it compares equal to zero."""
    v = float(value)
    if v == 0.0:
        v = 0.0  # fold -0.0
    return Expr("const", value=v)


_ZERO = const(0.0)
_ONE = const(1.0)


def symbol(kind: str, name: str) -> Expr:
    """A symbol leaf of kind ``state``, ``param``, ``input`` or ``time``."""
    if kind not in _SYMBOL_KINDS:
        raise ValueError(f"symbol kind must be one of {_SYMBOL_KINDS}, got {kind!r}")
    return Expr("sym", kind=kind, name=name)


def as_expr(x: Any) -> Expr:
    """Coerce a number (or a bool, as ``1``/``0``) to a constant; an ``Expr`` passes through."""
    if isinstance(x, Expr):
        return x
    if isinstance(x, bool):
        return const(1.0 if x else 0.0)
    if isinstance(x, (int, float)):
        return const(x)
    try:
        return const(float(x))
    except (TypeError, ValueError):
        raise TypeError(f"cannot convert {type(x).__name__} to an Expr") from None


_SMART_UNARY: dict[str, Callable[[Expr], Expr]] = {}
_SMART_BINARY: dict[str, Callable[[Expr, Expr], Expr]] = {}


def _rebuild(op: str, args: tuple[Expr, ...], value: Any = None) -> Expr:
    """Rebuild a node through the simplifying constructors."""
    if op == "pw":
        return piecewise(args[0], value[0], value[1])
    if op in _UNARY:
        return _SMART_UNARY[op](args[0])
    if op in _BINARY:
        return _SMART_BINARY[op](args[0], args[1])
    if op in _TERNARY:
        return where(args[0], args[1], args[2])
    raise ValueError(op)


def _unary(op: str, a: Expr) -> Expr:
    """Build a unary node, folding constants and pushing ``neg`` into
    products, quotients and differences."""
    if a.is_const:
        return const(_apply_unary(op, a.value))
    if op == "neg":
        if a.op == "neg":
            return a.args[0]
        if a.op == "mul" and a.args[0].is_const:
            return mul(const(-a.args[0].value), a.args[1])
        if a.op == "div" and a.args[0].is_const:
            return div(const(-a.args[0].value), a.args[1])
        if a.op == "sub":
            return sub(a.args[1], a.args[0])
    return Expr(op, (a,))


def _binary(op: str, a: Expr, b: Expr) -> Expr:
    """Build a binary node, folding it to a constant when both operands are."""
    if a.is_const and b.is_const:
        return const(_apply_binary(op, a.value, b.value))
    return Expr(op, (a, b))


def add(a: Expr, b: Expr) -> Expr:
    """``a + b`` with simplification: zeros dropped, ``a + a = 2 a``, constants
    moved first, like terms over a common denominator or factor merged."""
    if a.is_zero():
        return b
    if b.is_zero():
        return a
    if a == b:
        return mul(const(2.0), a)
    if b.op == "neg":
        return sub(a, b.args[0])
    if a.op == "neg":
        return sub(b, a.args[0])
    if b.is_const and not a.is_const:
        a, b = b, a  # constants first, for canonical form
    if b.is_const and b.value < 0:
        return sub(a, const(-b.value))
    if a.op == "div" and b.op == "div" and a.args[1] == b.args[1]:
        return div(add(a.args[0], b.args[0]), a.args[1])
    if (
        a.op == "mul"
        and b.op == "mul"
        and a.args[0].is_const
        and b.args[0].is_const
        and a.args[1] == b.args[1]
    ):
        return mul(const(a.args[0].value + b.args[0].value), a.args[1])
    return _binary("add", a, b)


def sub(a: Expr, b: Expr) -> Expr:
    """``a - b`` with simplification: ``a - a`` folds to ``0`` by structural
    equality, negative constants turn into additions, like terms merge."""
    if b.is_zero():
        return a
    if a.is_zero():
        return neg(b)
    if a == b:
        return _ZERO
    if b.op == "neg":
        return add(a, b.args[0])
    if b.is_const and b.value < 0:
        return add(a, const(-b.value))
    if a.op == "div" and b.op == "div" and a.args[1] == b.args[1]:
        return div(sub(a.args[0], b.args[0]), a.args[1])
    if (
        a.op == "mul"
        and b.op == "mul"
        and a.args[0].is_const
        and b.args[0].is_const
        and a.args[1] == b.args[1]
    ):
        return mul(const(a.args[0].value - b.args[0].value), a.args[1])
    return _binary("sub", a, b)


def mul(a: Expr, b: Expr) -> Expr:
    """``a * b`` with simplification: zero and one absorbed, constants moved
    first and combined, ``a * (c / a)`` cancelled."""
    if a.is_zero() or b.is_zero():
        return _ZERO
    if a.is_one():
        return b
    if b.is_one():
        return a
    if b.is_const and not a.is_const:
        a, b = b, a
    if a.is_const:
        if a.value == -1.0:
            return neg(b)
        if b.op == "mul" and b.args[0].is_const:  # c1 * (c2 * x)
            return mul(const(a.value * b.args[0].value), b.args[1])
        if b.op == "neg":
            return mul(const(-a.value), b.args[0])
        if b.op == "div" and b.args[0].is_const:  # c1 * (c2 / x)
            return div(const(a.value * b.args[0].value), b.args[1])
    if a.op == "neg" and b.op == "neg":
        return mul(a.args[0], b.args[0])
    if b.op == "div" and b.args[0].is_const and not a.is_const:  # a * (c / d)
        return mul(b.args[0], div(a, b.args[1]))
    if a.op == "div" and a.args[0].is_const and not b.is_const:
        return mul(a.args[0], div(b, a.args[1]))
    if b.op == "div" and b.args[1] == a:  # a * (c / a) = c
        return b.args[0]
    if a.op == "div" and a.args[1] == b:
        return a.args[0]
    return _binary("mul", a, b)


def div(a: Expr, b: Expr) -> Expr:
    """``a / b`` with simplification: a constant divisor becomes a factor
    ``1/c``, ``a / a`` folds to ``1``, nested quotients are flattened and common
    factors cancelled. Raises ``ZeroDivisionError`` for a constant zero divisor."""
    if b.is_zero():
        raise ZeroDivisionError("division by a constant zero in an expression")
    if a.is_zero():
        return _ZERO
    if b.is_one():
        return a
    if a == b:
        return _ONE
    if b.is_const:
        return mul(const(1.0 / b.value), a)
    if a.op == "neg" and b.op == "neg":
        return div(a.args[0], b.args[0])
    if b.op == "neg":
        return neg(div(a, b.args[0]))
    if b.op == "div":  # a / (c / d) = a d / c
        return div(mul(a, b.args[1]), b.args[0])
    if a.op == "mul" and b.op == "mul" and a.args[0].is_const and b.args[0].is_const:
        return mul(const(a.args[0].value / b.args[0].value), div(a.args[1], b.args[1]))
    if a.op == "mul" and a.args[0].is_const and b.op == "mul" and a.args[1] == b.args[1]:
        return div(a.args[0], b.args[0])
    if b.op == "mul" and b.args[0].is_const:  # a / (c b) = (1/c) (a / b)
        return mul(const(1.0 / b.args[0].value), div(a, b.args[1]))
    if a.op == "mul" and a.args[0].is_const:  # (c a) / b = c (a / b)
        return mul(a.args[0], div(a.args[1], b))
    if a.op == "mul" and a.args[1] == b:
        return a.args[0]
    if a.op == "mul" and a.args[0] == b:
        return a.args[1]
    return _binary("div", a, b)


def power(a: Expr, b: Expr) -> Expr:
    """``a ** b``, folding the exponents ``0`` and ``1`` and the bases ``0`` and ``1``."""
    if b.is_zero():
        return _ONE
    if b.is_one():
        return a
    if a.is_zero():
        return _ZERO
    if a.is_one():
        return _ONE
    if b.is_const and b.value == 2.0:
        return _binary("pow", a, b)
    return _binary("pow", a, b)


def neg(a: Expr) -> Expr:
    """``-a``; a double negation cancels."""
    return _unary("neg", a)


def sqrt(a: Any) -> Expr:
    """Square root; evaluates to NaN for a negative argument."""
    return _unary("sqrt", as_expr(a))


def exp(a: Any) -> Expr:
    """Exponential; overflow evaluates to ``inf``."""
    return _unary("exp", as_expr(a))


def log(a: Any) -> Expr:
    """Natural logarithm; ``-inf`` at zero, NaN for a negative argument."""
    return _unary("log", as_expr(a))


def abs_(a: Any) -> Expr:
    """Absolute value (``abs(expr)`` also works); ``abs(abs(a))`` folds to one node."""
    a = as_expr(a)
    if a.op == "abs":
        return a
    return _unary("abs", a)


def tanh(a: Any) -> Expr:
    """Hyperbolic tangent, the usual smooth stand-in for ``sign``."""
    return _unary("tanh", as_expr(a))


def sin(a: Any) -> Expr:
    """Sine."""
    return _unary("sin", as_expr(a))


def cos(a: Any) -> Expr:
    """Cosine."""
    return _unary("cos", as_expr(a))


def sign(a: Any) -> Expr:
    """``-1``, ``0`` or ``1``; its derivative is taken as zero."""
    return _unary("sign", as_expr(a))


def maximum(a: Any, b: Any) -> Expr:
    """The larger of two expressions; differentiates through whichever is active."""
    return _binary("max", as_expr(a), as_expr(b))


def minimum(a: Any, b: Any) -> Expr:
    """The smaller of two expressions; differentiates through whichever is active."""
    return _binary("min", as_expr(a), as_expr(b))


def where(cond: Any, a: Any, b: Any) -> Expr:
    """``a`` where ``cond`` is nonzero, else ``b``. Comparisons such as
    ``x > 0`` are expressions evaluating to ``1`` or ``0``, so they serve as
    ``cond``. Folds when ``cond`` is constant or both branches are equal."""
    cond, a, b = as_expr(cond), as_expr(a), as_expr(b)
    if cond.is_const:
        return a if cond.value != 0.0 else b
    if a == b:
        return a
    return Expr("where", (cond, a, b))


def piecewise(x: Any, knots: Sequence[float], coefs: Sequence[Sequence[float]]) -> Expr:
    """A piecewise polynomial of degree <= 2 in ``x``, given by a table.

    Segment ``i`` covers ``knots[i] <= x < knots[i+1]`` and evaluates
    ``c0 + c1 (x - knots[i]) + c2 (x - knots[i])**2`` with
    ``(c0, c1, c2) = coefs[i]``. Below the first knot the first segment is
    used, at or above the last knot the last segment: the ends extrapolate.
    ``len(coefs) == len(knots) - 1``. Differentiable; closed under ``diff``.
    """
    x = as_expr(x)
    ks = tuple(float(k) for k in knots)
    cs = tuple(tuple(float(v) for v in c) for c in coefs)
    if len(ks) < 2 or len(cs) != len(ks) - 1 or any(len(c) != 3 for c in cs):
        raise ValueError("piecewise needs n+1 knots and n triples (c0, c1, c2)")
    if any(b <= a for a, b in zip(ks[:-1], ks[1:], strict=True)):
        raise ValueError("piecewise knots must be strictly increasing")
    if x.is_const:
        return const(_eval_pw((ks, cs), x.value))  # type: ignore[arg-type]
    return Expr("pw", (x,), value=(ks, cs))


def interp(x: Any, xs: Sequence[float], ys: Sequence[float]) -> Expr:
    """Linear interpolation of a table ``(xs, ys)`` at ``x``, extrapolating at
    the ends. This is how a measured curve (an open-circuit voltage, a pump
    head) enters a law."""
    xs_ = [float(v) for v in xs]
    ys_ = [float(v) for v in ys]
    if len(xs_) != len(ys_) or len(xs_) < 2:
        raise ValueError("interp needs two equally long tables with at least 2 points")
    coefs = []
    for i in range(len(xs_) - 1):
        slope = (ys_[i + 1] - ys_[i]) / (xs_[i + 1] - xs_[i])
        coefs.append((ys_[i], slope, 0.0))
    return piecewise(x, xs_, coefs)


def interp_integral(
    x: Any, xs: Sequence[float], ys: Sequence[float], y0: float = 0.0
) -> Expr:
    """The exact integral of :func:`interp` from ``xs[0]`` to ``x``, plus ``y0``.

    Its derivative is ``interp(x, xs, ys)``. Use it as a storage's energy when
    the *effort* (voltage, pressure) is what you measured as a function of the
    stored quantity: ``energy = interp_integral(q, charge, ocv)``.
    """
    xs_ = [float(v) for v in xs]
    ys_ = [float(v) for v in ys]
    if len(xs_) != len(ys_) or len(xs_) < 2:
        raise ValueError("interp_integral needs two equally long tables")
    coefs = []
    acc = float(y0)
    for i in range(len(xs_) - 1):
        h = xs_[i + 1] - xs_[i]
        slope = (ys_[i + 1] - ys_[i]) / h
        coefs.append((acc, ys_[i], slope / 2.0))
        acc += ys_[i] * h + slope * h * h / 2.0
    return piecewise(x, xs_, coefs)


# ----------------------------------------------------------------- evaluation
def _apply_unary(op: str, v: float) -> float:
    """Apply a unary operator to a number, returning NaN or ``inf`` instead
    of raising outside the domain."""
    if op == "neg":
        return -v
    if op == "sqrt":
        return math.sqrt(v) if v >= 0 else math.nan
    if op == "exp":
        try:
            return math.exp(v)
        except OverflowError:
            return math.inf
    if op == "log":
        return math.log(v) if v > 0 else (-math.inf if v == 0 else math.nan)
    if op == "abs":
        return abs(v)
    if op == "tanh":
        return math.tanh(v)
    if op == "sin":
        return math.sin(v)
    if op == "cos":
        return math.cos(v)
    if op == "sign":
        return 0.0 if v == 0 else math.copysign(1.0, v)
    raise ValueError(op)


def _apply_binary(op: str, a: float, b: float) -> float:
    """Apply a binary operator to two numbers; ``gt`` gives ``1.0`` or ``0.0``,
    division by zero gives a signed ``inf`` or NaN."""
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "mul":
        return a * b
    if op == "div":
        return a / b if b != 0 else (math.copysign(math.inf, a) if a != 0 else math.nan)
    if op == "pow":
        try:
            return math.pow(a, b)
        except (ValueError, OverflowError):
            return math.nan
    if op == "max":
        return a if a >= b else b
    if op == "min":
        return a if a <= b else b
    if op == "gt":
        return 1.0 if a > b else 0.0
    raise ValueError(op)


def _eval(e: Expr, env: dict[str, float]) -> float:
    """Recursive evaluation of ``e`` with symbols looked up by ``key`` in ``env``."""
    if e.is_const:
        return e.value  # type: ignore[return-value]
    if e.is_symbol:
        try:
            return float(env[e.key])
        except KeyError:
            raise KeyError(f"no value for symbol {e.key}") from None
    if e.op in _UNARY:
        return _apply_unary(e.op, _eval(e.args[0], env))
    if e.op in _BINARY:
        return _apply_binary(e.op, _eval(e.args[0], env), _eval(e.args[1], env))
    if e.op == "where":
        c = _eval(e.args[0], env)
        return _eval(e.args[1], env) if c != 0.0 else _eval(e.args[2], env)
    if e.op == "pw":
        return _eval_pw(e.value, _eval(e.args[0], env))  # type: ignore[arg-type]
    raise ValueError(e.op)


def _eval_pw(table: tuple[Any, Any], x: float) -> float:
    """Evaluate a :func:`piecewise` table at ``x``: binary search for the
    segment, then the quadratic in ``x - knots[i]``; the end segments extrapolate."""
    knots, coefs = table
    # segment i covers [knots[i], knots[i+1]); the end segments extrapolate
    lo, hi = 0, len(coefs) - 1
    if x >= knots[hi]:
        i = hi
    elif x < knots[1]:
        i = 0
    else:
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if knots[mid] <= x:
                lo = mid
            else:
                hi = mid - 1
        i = lo
    d = x - knots[i]
    c0, c1, c2 = coefs[i]
    return c0 + d * (c1 + d * c2)


# ------------------------------------------------------------ differentiation
def _diff(e: Expr, s: Expr) -> Expr:
    """Partial derivative of ``e`` with respect to the symbol ``s``, built
    through the simplifying constructors. ``sign`` and ``gt`` differentiate
    to zero; ``max``, ``min`` and ``where`` differentiate the active branch."""
    if e.is_const:
        return _ZERO
    if e.is_symbol:
        return _ONE if e == s else _ZERO
    op = e.op
    if op == "neg":
        return neg(_diff(e.args[0], s))
    if op == "add":
        return add(_diff(e.args[0], s), _diff(e.args[1], s))
    if op == "sub":
        return sub(_diff(e.args[0], s), _diff(e.args[1], s))
    if op == "mul":
        a, b = e.args
        return add(mul(_diff(a, s), b), mul(a, _diff(b, s)))
    if op == "div":
        a, b = e.args
        da, db = _diff(a, s), _diff(b, s)
        if db.is_zero():
            return div(da, b)
        return div(sub(mul(da, b), mul(a, db)), power(b, const(2.0)))
    if op == "pow":
        a, b = e.args
        da = _diff(a, s)
        if b.is_const:
            if da.is_zero():
                return _ZERO
            return mul(mul(b, power(a, const(b.value - 1.0))), da)
        db = _diff(b, s)
        # general: a^b (db log a + b da / a)
        return mul(e, add(mul(db, log(a)), div(mul(b, da), a)))
    if op == "sqrt":
        a = e.args[0]
        da = _diff(a, s)
        if da.is_zero():
            return _ZERO
        return div(da, mul(const(2.0), e))
    if op == "exp":
        return mul(e, _diff(e.args[0], s))
    if op == "log":
        return div(_diff(e.args[0], s), e.args[0])
    if op == "abs":
        return mul(sign(e.args[0]), _diff(e.args[0], s))
    if op == "tanh":
        return mul(sub(_ONE, power(e, const(2.0))), _diff(e.args[0], s))
    if op == "sin":
        return mul(cos(e.args[0]), _diff(e.args[0], s))
    if op == "cos":
        return neg(mul(sin(e.args[0]), _diff(e.args[0], s)))
    if op == "sign":
        return _ZERO
    if op == "max":
        a, b = e.args
        return where(_binary("gt", a, b), _diff(a, s), _diff(b, s))
    if op == "min":
        a, b = e.args
        return where(_binary("gt", a, b), _diff(b, s), _diff(a, s))
    if op == "gt":
        return _ZERO
    if op == "where":
        c, a, b = e.args
        return where(c, _diff(a, s), _diff(b, s))
    if op == "pw":
        knots, coefs = e.value  # type: ignore[misc]
        dcoefs = tuple((c1, 2.0 * c2, 0.0) for (_c0, c1, c2) in coefs)
        inner = _diff(e.args[0], s)
        if inner.is_zero():
            return _ZERO
        return _binary("mul", piecewise(e.args[0], knots, dcoefs), inner)
    raise ValueError(op)


_SMART_UNARY.update(
    {
        "neg": neg,
        "sqrt": sqrt,
        "exp": exp,
        "log": log,
        "abs": abs_,
        "tanh": tanh,
        "sin": sin,
        "cos": cos,
        "sign": sign,
    }
)
_SMART_BINARY.update(
    {
        "add": add,
        "sub": sub,
        "mul": mul,
        "div": div,
        "pow": power,
        "max": maximum,
        "min": minimum,
        "gt": lambda a, b: _binary("gt", a, b),
    }
)


# --------------------------------------------------------------- formatting
_PREC = {"add": 1, "sub": 1, "mul": 2, "div": 2, "neg": 3, "pow": 4}


def _fmt(e: Expr, parent: int) -> str:
    """Infix rendering for ``repr``, parenthesised only where the operator
    binds more loosely than ``parent``; symbols print as ``kind:name``."""
    if e.is_const:
        v = e.value
        return repr(int(v)) if float(v).is_integer() and abs(v) < 1e15 else repr(v)
    if e.is_symbol:
        return f"{e.kind}:{e.name}"
    op = e.op
    if op in ("add", "sub", "mul", "div", "pow"):
        p = _PREC[op]
        sym = {"add": " + ", "sub": " - ", "mul": " * ", "div": " / ", "pow": "**"}[op]
        left = _fmt(e.args[0], p)
        right = _fmt(e.args[1], p + 1)
        s = f"{left}{sym}{right}"
        return f"({s})" if p < parent else s
    if op == "neg":
        s = f"-{_fmt(e.args[0], 3)}"
        return f"({s})" if parent > 3 else s
    if op == "pw":
        return f"pw({_fmt(e.args[0], 0)}; {len(e.value[1])} segments)"  # type: ignore[index]
    return f"{op}({', '.join(_fmt(a, 0) for a in e.args)})"


# ------------------------------------------------------------- serialisation
def from_json(data: Any) -> Expr:
    """Inverse of :meth:`Expr.to_json`."""
    if not isinstance(data, list) or not data:
        raise ValueError(f"malformed expression: {data!r}")
    op = data[0]
    if op == "const":
        return const(data[1])
    if op == "sym":
        return symbol(data[1], data[2])
    if op == "pw":
        return piecewise(from_json(data[1]), data[2], data[3])
    args = tuple(from_json(a) for a in data[1:])
    return _rebuild(op, args)


def trace(fn: Callable[..., Any], *symbols_: Expr) -> Expr:
    """Call a plain Python function on symbols and return the traced expression.

    This is how a user-supplied law such as ``lambda v: 0.02 + 2e-6 * v**2``
    becomes an :class:`Expr` the engine can run.
    """
    out = fn(*symbols_)
    try:
        return as_expr(out)
    except TypeError:
        raise TypeError(
            "a law must be built from its arguments with ordinary arithmetic and "
            "the functions in otwin.expr (sqrt, exp, log, abs, tanh, maximum, "
            "minimum, where); numpy functions and Python conditionals cannot be "
            "traced"
        ) from None


def lower(exprs: Iterable[Expr], order: dict[str, int]) -> list[Any]:
    """Serialise expressions with symbols replaced by ``["ref", index]``.

    ``order`` maps ``"kind:name"`` to a slot in the engine's flat symbol table.
    This is the form the Rust engine loads.
    """

    def go(e: Expr) -> Any:
        if e.is_const:
            return ["const", e.value]
        if e.is_symbol:
            try:
                return ["ref", order[e.key]]
            except KeyError:
                raise KeyError(f"symbol {e.key} is not in the engine table") from None
        if e.op == "pw":
            knots, coefs = e.value  # type: ignore[misc]
            return ["pw", go(e.args[0]), list(knots), [list(c) for c in coefs]]
        return [e.op, *[go(a) for a in e.args]]

    return [go(e) for e in exprs]
