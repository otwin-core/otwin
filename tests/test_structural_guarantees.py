"""The guarantee, tested where it actually has to hold.

A structural claim imposed by a *penalty term* holds approximately, wherever
the optimiser happened to stop. A claim imposed by the *parameterisation* holds
at every point in weight space — before training, at a bad initialisation, and
after a diverging update.

This file tests the second claim, which is the one PortHamiltonianNN makes:
``J`` is built as ``A - Aᵀ`` and ``R`` as ``L Lᵀ``, so no gradient step can
break either.

Why this file exists at all
---------------------------

These guarantees had **never been executed**. PyTorch could not be installed in
the environment where the package was assembled, so the implementation was
complete, reviewed, and entirely unverified — the project's own STATUS file said
so. An untested guarantee is a comment.
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from otwin.model import PortHamiltonianNN  # noqa: E402

SEEDS = [0, 1, 7, 42]
STATES = [1, 2, 3, 5]


def _dtype(model):
    """Use the network's own dtype.

    PortHamiltonianNN is float64. Forcing float32 tensors at it does not merely
    lose precision — it changes the arithmetic under the structural identities
    and makes an exact guarantee look approximate. Always ask the model.
    """
    return model.parameters()[0].dtype


def _sample_states(n_states: int, rng, n: int = 12, scale: float = 5.0):
    """Include the origin and points far outside any plausible training range."""
    pts = [np.zeros(n_states)]
    pts += [rng.normal(0.0, scale, n_states) for _ in range(n)]
    pts += [np.full(n_states, 1e3), np.full(n_states, -1e3)]
    return pts


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n_states", STATES)
def test_J_is_skew_at_untrained_weights(seed, n_states):
    """The guarantee must hold *before any training at all*."""
    model = PortHamiltonianNN(n_states=n_states, n_inputs=1, hidden=16, seed=seed)
    rng = np.random.default_rng(seed)
    for x in _sample_states(n_states, rng):
        xt = torch.tensor(x, dtype=_dtype(model))
        J = np.atleast_2d(model._J(xt.unsqueeze(0)).detach().numpy().squeeze())
        violation = np.abs(J + J.T).max()
        assert violation == 0.0, (
            f"J is not skew at x={x[:3]}...: max|J+Jᵀ| = {violation:.3e}. "
            f"J = A - Aᵀ is skew *identically*, so anything but exactly zero "
            f"means the construction changed."
        )


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n_states", STATES)
def test_R_is_psd_at_untrained_weights(seed, n_states):
    model = PortHamiltonianNN(n_states=n_states, n_inputs=1, hidden=16, seed=seed)
    rng = np.random.default_rng(seed)
    for x in _sample_states(n_states, rng):
        xt = torch.tensor(x, dtype=_dtype(model))
        R = np.atleast_2d(model._R(xt.unsqueeze(0)).detach().numpy().squeeze())
        eig = np.linalg.eigvalsh(0.5 * (R + R.T))
        # R = L Lᵀ is PSD identically; the only slack is eigensolver round-off,
        # which scales with the magnitude of R.
        tol = 1e-12 * max(1.0, float(np.abs(R).max()))
        assert eig.min() >= -tol, (
            f"R is not PSD at x={x[:3]}...: min eig = {eig.min():.3e}, tol = {tol:.3e}"
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_the_guarantee_survives_deliberately_corrupted_weights(seed):
    """The real test: break the weights and check the structure still holds.

    A penalty-based model fails this instantly. A structurally parameterised one
    cannot fail it, because skewness and PSD-ness are properties of the *form*
    ``A - Aᵀ`` and ``L Lᵀ``, not of the values in ``A`` and ``L``.
    """
    model = PortHamiltonianNN(n_states=3, n_inputs=1, hidden=16, seed=seed)
    rng = np.random.default_rng(seed)

    with torch.no_grad():
        for p in model.parameters():
            p.add_(torch.randn_like(p) * 50.0)  # far outside any trained regime

    for x in _sample_states(3, rng, n=8):
        xt = torch.tensor(x, dtype=_dtype(model)).unsqueeze(0)
        J = np.atleast_2d(model._J(xt).detach().numpy().squeeze())
        R = np.atleast_2d(model._R(xt).detach().numpy().squeeze())
        if not np.all(np.isfinite(J)) or not np.all(np.isfinite(R)):
            continue  # corrupted weights may overflow; that is not a structure failure
        assert np.abs(J + J.T).max() == 0.0, "skewness must survive any weights"
        eig = np.linalg.eigvalsh(0.5 * (R + R.T))
        assert eig.min() >= -1e-12 * max(1.0, float(np.abs(R).max()))


def test_the_guarantee_survives_a_diverging_optimisation():
    """Train with an absurd learning rate and confirm the structure holds after."""
    model = PortHamiltonianNN(n_states=2, n_inputs=0, hidden=16, seed=3)
    opt = torch.optim.SGD(model.parameters(), lr=5.0)  # deliberately unstable

    x = torch.randn(32, 2, dtype=_dtype(model))
    for _ in range(25):
        opt.zero_grad()
        loss = (model.dynamics_tensor(x) ** 2).mean()
        loss.backward()
        opt.step()

    xt = torch.zeros(1, 2, dtype=_dtype(model))
    J = np.atleast_2d(model._J(xt).detach().numpy().squeeze())
    R = np.atleast_2d(model._R(xt).detach().numpy().squeeze())
    if np.all(np.isfinite(J)):
        assert np.abs(J + J.T).max() == 0.0
    if np.all(np.isfinite(R)):
        eig = np.linalg.eigvalsh(0.5 * (R + R.T))
        assert eig.min() >= -1e-12 * max(1.0, float(np.abs(R).max()))


@pytest.mark.parametrize("seed", SEEDS)
def test_check_structure_agrees_with_direct_inspection(seed):
    model = PortHamiltonianNN(n_states=3, n_inputs=1, hidden=16, seed=seed)
    result = model.check_structure(np.zeros(3))
    assert isinstance(result, dict)
    for value in result.values():
        ok = value[0] if isinstance(value, tuple) else value
        assert bool(ok), f"check_structure reported a violation at the origin: {result}"


def test_energy_is_scalar_and_finite_everywhere_sampled():
    model = PortHamiltonianNN(n_states=2, n_inputs=0, hidden=16, seed=0)
    rng = np.random.default_rng(0)
    for x in _sample_states(2, rng, n=10):
        e = model.energy(x)
        assert isinstance(e, float)
        assert np.isfinite(e) or np.abs(x).max() > 1e2
