"""Core protocols — the Otwin contract.

This module defines *what a twin is*. It contains no algorithms: no
integrators, no solvers, no estimators, no metrics. Every Otwin tool package
implements one or more of these protocols, and every binding in another
language mirrors them.

If you are writing a new tool for the Otwin ecosystem, this file is the only
thing you must read.

Two rules about using these protocols
-------------------------------------

**Do not inherit from them.** They exist for :func:`isinstance` checks and for
static typing. Subclassing gives you concrete methods whose bodies raise
:class:`NotImplementedError`, and — worse — makes :func:`isinstance` pass
unconditionally because Python short-circuits on the nominal subclass check.
Write a plain class with the right methods; structural typing does the rest.

**:func:`isinstance` checks names, not signatures or behaviour.** A class with
a method called ``rhs`` that takes no arguments and returns a string will pass.
``isinstance`` is a smoke test. Real conformance is
`otwin-spec <https://github.com/otwin-core/otwin-spec>`_, which runs golden
fixtures against analytic answers.

Note also that :func:`issubclass` raises ``TypeError`` on most of these
protocols, because they have non-method members (``n_states``,
``preserves_structure``, ...). This is a Python language rule, not something we
can fix. **Check instances, never classes.**
"""

from __future__ import annotations

from typing import Any, Protocol, TypeAlias, runtime_checkable

import numpy as np
import numpy.typing as npt

#: Floating-point array — states, trajectories, energies, bounds.
Array: TypeAlias = npt.NDArray[np.floating]

#: Integer array — sample indices, forecast horizons, step counts.
#:
#: Kept distinct from :data:`Array` because indices are not floats, and typing
#: them as such forces every contributor writing a splitter either to cast
#: (corrupting the indices) or to silence the type checker.
IndexArray: TypeAlias = npt.NDArray[np.integer]

__all__ = [
    "Array",
    "IndexArray",
    "TwinModel",
    "PortHamiltonianModel",
    "HasEnergyGradient",
    "IrreversibleModel",
    "EmpiricalLawModel",
    "Integrator",
    "Estimator",
    "UncertaintyModel",
    "Baseline",
    "EvaluationProtocol",
    "Splitter",
]

_NO_INHERIT = (
    "Otwin protocols are for isinstance checks and static typing, not for "
    "inheritance. Write a plain class with the required methods — structural "
    "typing will recognise it. See the module docstring in otwin.interfaces.protocols."
)


@runtime_checkable
class TwinModel(Protocol):
    """Anything that can be forecast.

    This is the root of the type hierarchy. A ``TwinModel`` says how the state
    changes and what is observed; it says nothing about *why*.

    Attributes:
        n_states: Dimension of the state vector ``x``.
        n_inputs: Dimension of the input vector ``u``. May be 0.

    Example:
        >>> import numpy as np
        >>> class Decay:
        ...     n_states = 1
        ...     n_inputs = 0
        ...     def rhs(self, x, u, t):
        ...         return -0.5 * x
        ...     def observe(self, x, u, t):
        ...         return x
        >>> isinstance(Decay(), TwinModel)
        True
    """

    n_states: int
    n_inputs: int

    def rhs(self, x: Array, u: Array, t: float) -> Array:
        """Right-hand side of the dynamics: return ``dx/dt``.

        Args:
            x: State, shape ``(n_states,)``.
            u: Input, shape ``(n_inputs,)``. May be empty.
            t: Time.

        Returns:
            ``dx/dt``, shape ``(n_states,)``.
        """
        raise NotImplementedError(_NO_INHERIT)

    def observe(self, x: Array, u: Array, t: float) -> Array:
        """Observation map: return ``y``.

        Args:
            x: State, shape ``(n_states,)``.
            u: Input, shape ``(n_inputs,)``.
            t: Time.

        Returns:
            Observation ``y``.
        """
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class PortHamiltonianModel(TwinModel, Protocol):
    """A model that additionally exposes its energy structure.

    Satisfying this protocol is a claim with teeth: it asserts that the
    dynamics can be written

    .. math::

        \\dot{x} = (J(x) - R(x))\\,\\nabla H(x) + g(x)\\,u,
        \\qquad y = g(x)^{\\top}\\nabla H(x)

    with ``J`` skew-symmetric and ``R`` positive semidefinite. Those two
    properties are what make the power balance

    .. math::

        \\frac{dH}{dt} = -\\nabla H^{\\top} R \\nabla H + y^{\\top}u
        \\;\\leq\\; y^{\\top}u

    hold *by construction* rather than by fitting. The conformance suite in
    ``otwin-spec`` verifies both, so a model that claims this protocol and
    violates it will fail CI rather than fail silently in production.

    If you can also supply an analytic energy gradient, implement
    :class:`HasEnergyGradient` as well — structure-preserving integrators are
    both faster and more accurate with it.
    """

    def H(self, x: Array) -> float:
        """Energy (Hamiltonian) stored in state ``x``."""
        raise NotImplementedError(_NO_INHERIT)

    def J(self, x: Array) -> Array:
        """Interconnection matrix, shape ``(n, n)``. Must satisfy ``J = -Jᵀ``."""
        raise NotImplementedError(_NO_INHERIT)

    def R(self, x: Array) -> Array:
        """Dissipation matrix, shape ``(n, n)``. Must be positive semidefinite."""
        raise NotImplementedError(_NO_INHERIT)

    def g(self, x: Array) -> Array:
        """Input/port map, shape ``(n_states, n_inputs)``."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class HasEnergyGradient(Protocol):
    """A model that supplies an analytic energy gradient ``∇H``.

    Separate from :class:`PortHamiltonianModel` so that tools can branch on it:

    .. code-block:: python

        if isinstance(model, HasEnergyGradient):
            grad = model.grad_H(x)
        else:
            grad = numerical_gradient(model.H, x)   # slower, less accurate

    The name and the return shape are normative. Without this protocol, one
    tool would call it ``grad_H``, another ``dH``, and the Julia binding
    ``∇H`` — and none of them would interoperate.
    """

    def grad_H(self, x: Array) -> Array:
        """Gradient of the energy, ``∂H/∂x``, shape ``(n_states,)``."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class IrreversibleModel(PortHamiltonianModel, Protocol):
    """A port-Hamiltonian model with explicit entropy production.

    Irreversible port-Hamiltonian systems (Ramírez, Maschke & Sbarbaro, 2013)
    extend the PHS structure to thermodynamic systems where entropy is created
    rather than merely dissipated. The additional obligation is the second law:

    .. math:: \\sigma(x) \\geq 0 \\quad \\text{for all reachable } x

    Implementations must enforce this, not document it. The conformance suite
    checks it on sampled states.
    """

    def entropy_production(self, x: Array, u: Array, t: float) -> float:
        """Entropy production rate ``σ`` at ``x``. Must be ``>= 0``."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class EmpiricalLawModel(Protocol):
    """A model whose structure is a trend law rather than an energy balance.

    Some systems only degrade — capacity fade, wear, fatigue, corrosion. There
    is no energy function to conserve and no port through which power flows.
    Forcing such a system into a port-Hamiltonian frame is the most common
    conceptual error in this field.

    For these, the model structure is a transparent trend law with estimated
    parameters, plus a bounded residual. The workflow after that point is
    identical to the port-Hamiltonian case: estimate, quantify uncertainty,
    validate without leakage.

    Note:
        This protocol deliberately does **not** extend :class:`TwinModel`. A
        fade law has no state derivative, and requiring a stub ``rhs`` that
        returns zeros would be exactly the conceptual error described above.

    Example:
        Battery State-of-Health under the Wang throughput power law
        ``SoH(n) = 1 - c·n^z``, where ``z ≈ 0.5`` indicates diffusion-limited
        SEI growth and ``z ≈ 1`` indicates linear wear.
    """

    def law(self, t: Array, params: dict[str, float]) -> Array:
        """Evaluate the trend law at times ``t``."""
        raise NotImplementedError(_NO_INHERIT)

    @property
    def param_names(self) -> tuple[str, ...]:
        """Names of the estimated parameters, in a stable order."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class Integrator(Protocol):
    """Advances a :class:`TwinModel` through time.

    An integrator is *structure-preserving* if it maintains the model's
    invariants discretely — for a port-Hamiltonian model, that means energy
    cannot increase with ``u = 0``, at any step size. Implementations should
    declare this honestly via :attr:`preserves_structure`, because tools and
    the conformance suite branch on it.
    """

    preserves_structure: bool

    def step(self, model: TwinModel, x: Array, u: Array, t: float, dt: float) -> Array:
        """Advance the state by one step of size ``dt``."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class Estimator(Protocol):
    """Fits the unknown parts of a model structure to data.

    This is the protocol that *creates grey-box twins*. A white-box model has
    every parameter from first principles; a grey-box model has some estimated
    here. The list of names this returns becomes ``TwinManifest.estimated``,
    which is what the whole ecosystem branches on to decide whether a twin can
    be validated against a closed-form answer or must be validated against
    held-out data.

    Implementations range from least-squares curve fitting to gradient descent
    on a neural network with enforced structure. The contract is only about
    what goes in and what comes out.

    Example:
        >>> import numpy as np
        >>> class MeanFit:
        ...     @property
        ...     def estimated_names(self):
        ...         return ("level",)
        ...     def fit(self, model, data, t=None, u=None):
        ...         return {"level": float(np.mean(data))}
        >>> isinstance(MeanFit(), Estimator)
        True
    """

    @property
    def estimated_names(self) -> tuple[str, ...]:
        """Names of the parameters this estimator sets, in a stable order.

        These names must match keys in the resulting
        :attr:`~otwin.interfaces.TwinManifest.parameters`, and are recorded in
        :attr:`~otwin.interfaces.TwinManifest.estimated`.
        """
        raise NotImplementedError(_NO_INHERIT)

    def fit(
        self,
        model: Any,
        data: Array,
        t: Array | None = None,
        u: Array | None = None,
    ) -> dict[str, float]:
        """Estimate parameters from data.

        Args:
            model: The model structure whose unknowns are being estimated.
            data: Observations, shape ``(n_samples, n_features)``.
            t: Time grid, if the data is not evenly spaced.
            u: Inputs, if the system is forced.

        Returns:
            A mapping from parameter name to fitted value. Keys must be exactly
            :attr:`estimated_names`.
        """
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class UncertaintyModel(Protocol):
    """Attaches calibrated intervals to a point forecast.

    The contract is deliberately about *coverage*, not about method. Deep
    ensembles, Gaussian processes, conformal prediction and Bayesian posteriors
    all satisfy it, and all are judged the same way: a stated 90% interval must
    contain the truth about 90% of the time on held-out data.

    Uncertainty is validated for coverage, never assumed.
    """

    def calibrate(self, residuals: Array, horizons: IndexArray) -> None:
        """Fit the uncertainty model on held-out residuals."""
        raise NotImplementedError(_NO_INHERIT)

    def interval(
        self, mean: Array, horizons: IndexArray, level: float = 0.9
    ) -> tuple[Array, Array]:
        """Return ``(lower, upper)`` bounds at the requested coverage level."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class Baseline(Protocol):
    """A reference forecaster that a model must beat to be worth anything.

    Otwin makes baselines mandatory rather than optional. A model reported
    without one is not evaluated, it is merely described.
    """

    name: str

    def forecast(self, history: Array, horizon: int) -> Array:
        """Forecast ``horizon`` steps ahead from ``history``."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class Splitter(Protocol):
    """Divides a series into train/test folds without leaking the future.

    Random splits measure interpolation. Forecasting requires temporal splits.
    Implementations that shuffle must set :attr:`leakage_free` to ``False``, and
    every report derived from them says so on its first line.
    """

    leakage_free: bool

    def split(self, n_samples: int) -> list[tuple[IndexArray, IndexArray]]:
        """Return a list of ``(train_idx, test_idx)`` index pairs."""
        raise NotImplementedError(_NO_INHERIT)


@runtime_checkable
class EvaluationProtocol(Protocol):
    """A complete evaluation procedure: splitter + baselines + metrics."""

    name: str
    splitter: Splitter
    baselines: tuple[Baseline, ...]

    def run(self, model: TwinModel, data: Array, **kwargs: Any) -> Any:
        """Execute the protocol and return a :class:`~otwin.interfaces.Report`."""
        raise NotImplementedError(_NO_INHERIT)
