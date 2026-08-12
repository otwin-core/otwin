"""A grid-scale battery bank, from register read to refusal.

Runs the whole ISO 13374 chain against a simulated SunSpec device, so it needs
no hardware, no network and no optional dependencies:

    DA  otwin.io        read SunSpec models 802 and 713 off the wire
    DM  otwin.signal    put irregular samples on a grid without inventing data
    SD  otwin.estimate  correct the state, without the filter creating energy
    HA  otwin.model     the energy-based model of the bank
    PA  otwin.forecast  forecast, scored against a reference that is hard to beat
    AG  otwin.advise    answer, or refuse and say why

Run it:

    python examples/bess_end_to_end.py
"""

import numpy as np

from otwin.advise import Envelope
from otwin.estimate import EnergyConsistentObserver
from otwin.forecast import evaluate
from otwin.interfaces import Provenance, TwinManifest
from otwin.io import SunSpecSimulator, SunSpecSource, to_si
from otwin.model import PortHamiltonianSystem
from otwin.signal import coverage, resample, sort_samples

RULE = "─" * 74


def banner(block: str, title: str) -> None:
    print(f"\n{RULE}\n  {block}  {title}\n{RULE}")


# ---------------------------------------------------------------- DA
banner("DA", "Data Acquisition — SunSpec Modbus")

# The simulator is a *transport*: it serves a real register image, and the
# same SunSpecSource that talks to hardware decodes it. Nothing is bypassed.
wire = SunSpecSimulator(soc=0.82, capacity_wh=40e6)
device = SunSpecSource(transport=wire, name="bess-bank-01")
sample = device.read()

print(f"  device            {sample.source}")
print(f"  models found      {sorted(m.model_id for m in device.models)}")
print(f"  tags discovered   {len(sample.values)}")
for tag in list(sample.values)[:5]:
    print(f"    {tag:<28} {sample.values[tag]:>12.4g}  [{sample.quality[tag]}]")
print(f"  state of charge   {device.soc(sample):.3f}  (model 713 / 802)")
print(f"  1 kW in SI        {to_si(1.0, 'kW'):.0f} W   — units are not optional")

# The connector degrades rather than crashing. A plant network drops packets.
wire.inject_timeout_for_model(802)
degraded = device.read()
states = {q for q in degraded.quality.values() if q != "good"}
bad = [t for t, q in degraded.quality.items() if q != "good"]
print(
    f"  after a timeout   {len(bad)} tag(s) -> {states or {'good'}}, no exception raised"
)
print(f"  last error        {device.last_error}")
wire.clear_faults()

# ---------------------------------------------------------------- DM
banner("DM", "Data Manipulation — conditioning")

rng = np.random.default_rng(0)
n = 400
t_raw = np.cumsum(rng.uniform(0.6, 1.4, n))  # irregular arrival
soc_raw = 0.9 - 2.2e-4 * t_raw + rng.normal(0, 0.004, n)
t_raw[120:] += 180.0  # a three-minute outage
order = rng.permutation(n)  # arrived out of order
t_raw, soc_raw = sort_samples(t_raw[order], soc_raw[order])

t_grid, soc_grid, gaps = resample(t_raw, soc_raw, dt=1.0, max_gap=5.0)
print(f"  raw samples       {n} irregular, unsorted")
print(f"  grid              {len(t_grid)} points at dt = 1.0 s")
print(
    f"  gaps found        {len(gaps)}  ({gaps[0].duration:.0f} s, {gaps[0].n_missing} points left NaN)"
)
print(f"  coverage          {coverage(soc_grid):.1%} of the window was measured")
print("  the outage is not interpolated across. A model must not learn the interpolator.")

# ---------------------------------------------------------------- HA
banner("HA", "Health Assessment — the energy-based model")

# One store (charge), one dissipative path (self-discharge), one port (current).
bank = PortHamiltonianSystem(
    H=lambda x: 0.5 * 40.0 * float(x[0]) ** 2,  # 40 MWh at full charge
    grad_H=lambda x: np.array([40.0 * x[0]]),
    J=lambda x: np.zeros((1, 1)),  # nothing circulates in 1-D
    R=lambda x: np.array([[1.9e-10]]),  # self-discharge, ~2%/month
    g=lambda x: np.array([[1.0]]),  # the terminals
    n_states=1,
    n_inputs=1,
)
struct = bank.check_structure(np.array([0.82]))
for name, (ok, violation) in struct.items():
    print(
        f"  {name:<18} {'ok' if ok else 'VIOLATED':<10} (|violation| = {violation:.2e})"
    )

t_sim = np.linspace(0, 1800, 600)
sol = bank.forecast(np.array([0.82]), t_sim, np.zeros((600, 1)))
E = np.array([bank.energy(x) for x in sol["x"]])
print(f"  solver            {sol['method']}")
print(f"  worst energy gain {max(0.0, float(np.max(np.diff(E)))):.2e} MWh over 600 steps")
print("  energy cannot increase with the terminals open. Algebra, not fitting.")

# ---------------------------------------------------------------- SD
banner("SD", "State Detection — an estimator that cannot cheat")

n_obs = 200
t_obs = t_sim[:n_obs]
truth = sol["x"][:n_obs, :]

# What is actually measured is the port output y = g^T grad_H -- the effort
# variable at the terminals, not the state itself. Feeding a filter the state
# when the model reports the effort is a units error that no exception catches;
# building the measurement through `observe` makes it impossible.
meas = np.array([bank.observe(x, np.zeros(1), 0.0) for x in truth])
meas = meas + rng.normal(0, 0.4, meas.shape)

# The prior starts slightly over-energetic, which is the configuration the
# docstring recommends for an autonomous system: with u = 0 the energy budget
# is zero, so any *upward* correction has to be clamped. Corrections that
# remove energy pass through untouched; measurement noise occasionally pushes
# the other way, and those are the steps the clamp catches.
obs = EnergyConsistentObserver(
    bank,
    Q=np.array([[1e-8]]),  # the model is good, but not perfect
    R_meas=np.array([[0.16]]),  # sigma = 0.4 on the terminal measurement
    P0=np.array([[4e-4]]),
    x0=np.array([0.84]),  # the prior is 0.02 too high
)
res = obs.filter(meas, np.zeros((n_obs, 1)), t_obs)
H_est = np.array([bank.energy(x) for x in res.x])
clamped = int(np.sum(res.alpha < 1.0 - 1e-12))
rmse_est = float(np.sqrt(np.mean((res.x[:, 0] - truth[:, 0]) ** 2)))
rmse_open = float(np.sqrt(np.mean((0.84 - truth[:, 0]) ** 2)))

print(f"  steps             {n_obs}")
print(f"  worst energy gain {max(0.0, float(np.max(np.diff(H_est)))):.2e} MWh")
print(f"  state rmse        {rmse_est:.5f}  vs {rmse_open:.5f} open loop")
print(
    f"  clamped           {clamped} / {n_obs} corrections  (min alpha = {float(np.min(res.alpha)):.3f})"
)
print(f"  a plain EKF would have injected {obs.energy_injected:.3e} MWh of energy")
print("  the filter may correct the state. It may not supply power the ports did not.")
print()
print("  KNOWN LIMITATION, stated rather than tuned around: with the terminals")
print("  open the energy budget is zero, so *every* upward revision is clamped --")
print("  even one that is just the filter learning the prior was too low. That")
print("  makes the estimate one-way. Start the prior over-energetic (as here) or")
print("  model the disturbance as a real port. See EnergyConsistentObserver.")

# ---------------------------------------------------------------- PA
banner("PA", "Prognostic Assessment — scored against something hard to beat")


class WangFadeLaw:
    """SoH(n) = 1 - c*n^z, fitted in log space where the power law is linear.

    Fitting the raw curve over a short window is badly conditioned: c and z
    trade off almost freely and least squares wanders to whichever bound you
    set. In log space it is a straight line.

    It sees history and an integer horizon. It never sees the answer.
    """

    def forecast(self, history, horizon):
        y = np.asarray(history, dtype=float).ravel()
        n = np.arange(1, len(y) + 1, dtype=float)
        loss = np.clip(1.0 - y, 1e-9, None)
        z, log_c = np.polyfit(np.log(n), np.log(loss), 1)
        z = float(np.clip(z, 0.3, 1.5))  # a physical prior, doing real work
        future = np.arange(len(y) + 1, len(y) + horizon + 1, dtype=float)
        return (1.0 - np.exp(log_c) * future**z).reshape(-1, 1)


# Capacity fade over cycles -- the question the twin actually exists to answer.
cycles = np.arange(1, 601, dtype=float)
soh = 1.0 - 0.0031 * cycles**0.53 + rng.normal(0, 0.0015, cycles.size)
series = soh.reshape(-1, 1)
report = evaluate(WangFadeLaw(), series, protocol="rolling_origin", n_folds=4, horizon=20)
skill = report.point_metrics["rmse"] / report.baseline_metrics["rmse"]
print(f"  protocol          {report.split_protocol}, {report.n_folds} folds")
print(f"  reference         {report.baseline_name}")
print(f"  series            state of health over {len(series)} cycles")
print(f"  rmse              {report.point_metrics['rmse']:.5f}")
print(
    f"  skill             {skill:.3f}   ({'beats' if skill < 1 else 'LOSES TO'} the reference)"
)
print("  the model was handed history and an integer horizon. Never the answer.")

# ---------------------------------------------------------------- AG
banner("AG", "Advisory Generation — the twin can say no")

twin = TwinManifest(
    name="bess-bank-01",
    model_class="port_hamiltonian",
    model_kind="single_store_bank",
    n_states=1,
    n_inputs=1,
    parameters={"capacity_mwh": 40.0, "self_discharge": 2.0e-5},
    estimated=["self_discharge"],
    validation={
        "protocol": "rolling_origin",
        "leakage_free": True,
        "skill": float(skill),
        "horizon": 500,
    },
    provenance=Provenance.now("0.2.0", script="bess_end_to_end.py", seed=0),
)
envelope = Envelope(state_bounds=[(0.15, 0.95)], max_horizon=500)

for label, kw in [
    ("inside the envelope", dict(state=[0.82], horizon=200)),
    ("horizon too long", dict(state=[0.82], horizon=900)),
    ("operating point never seen", dict(state=[0.04], horizon=200)),
    (
        "asking for an unvalidated band",
        dict(state=[0.82], horizon=200, wants_interval=True),
    ),
]:
    verdict = envelope.check(manifest=twin, **kw)
    mark = "ANSWER " if verdict else "REFUSE "
    print(f"\n  [{mark}] {label}")
    for line in verdict.explain().splitlines():
        if line.strip():
            print(f"      {line}")

print(f"\n{RULE}")
print("  A model that always returns a number is not being careful. It is being polite.")
print(RULE)
