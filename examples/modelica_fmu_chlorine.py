"""A Modelica model checked with Otwin: chlorine in a storage tank.

The model is an FMU exported from a Modelica tool. Here it is the Reference FMU
`Dahlquist.fmu` (dx/dt = -k x) published by the Modelica Association, so the
example runs anywhere. Run it from this folder after:

    pip install "otwin[engine]" fmpy
    curl -LO https://github.com/modelica/Reference-FMUs/releases/download/v0.0.39/Reference-FMUs-0.0.39.zip
    unzip -j Reference-FMUs-0.0.39.zip 3.0/Dahlquist.fmu
"""

import numpy as np
from fmpy import extract, simulate_fmu
from otwin.forecast import horizon_conformal, picp, rolling_origin_residuals

FMU = extract("Dahlquist.fmu")  # dx/dt = -k x, exported by a Modelica tool
K_LAB, DOSE = 0.05, 1.0  # bottle-test decay [1/h], residual after each daily dose [mg/L]


def fmu_forecast(history, horizon):
    """The Modelica model run forward from the last reading, redosed every 24 h."""
    t, x, out = len(history) - 1, float(history[-1]), []
    while len(out) < horizon:
        if (t + 1) % 24 == 0:  # the daily dose
            t, x = t + 1, DOSE
            out.append(DOSE)
            continue
        steps = min(horizon - len(out), 23 - t % 24)
        r = simulate_fmu(
            FMU, stop_time=steps, output_interval=1, start_values={"x": x, "k": K_LAB}
        )
        out += list(r["x"][1 : steps + 1])
        t, x = t + steps, out[-1]
    return np.array(out)


# the real tank: walls take chlorine too (k = 0.065 1/h), sensor noise 2 %
rng = np.random.default_rng(0)
hours = np.arange(30 * 24)
truth = DOSE * np.exp(-0.065 * (hours % 24))
reading = truth * (1 + rng.normal(0, 0.02, hours.size))

train, test = reading[: 20 * 24], reading[20 * 24 :]
res, h = rolling_origin_residuals(
    fmu_forecast, train, step=6, min_train=24, max_horizon=24
)
band = horizon_conformal(res, h, level=0.9, max_horizon=24)

ys, lo, up = [], [], []
for k in range(20 * 24, 30 * 24 - 24, 6):
    lower, upper = band.apply(fmu_forecast(reading[:k], 24))
    ys.append(reading[k : k + 24])
    lo.append(lower)
    up.append(upper)
print(f"{res.size} out-of-sample errors from the Modelica model")
coverage = picp(np.concatenate(ys), np.concatenate(lo), np.concatenate(up))
print(f"coverage of the 90 % band on 10 unseen days: {coverage:.0%}")
now = 20 * 24 + 6  # day 21, 06:00
forecast = fmu_forecast(reading[:now], 17)  # until 23:00
lower, _ = band.apply(forecast)
print(
    f"lowest chlorine before the next dose, Modelica model alone: {forecast.min():.3f} mg/L"
)
print(
    f"lowest chlorine before the next dose, lower edge of the band: {lower.min():.3f} mg/L"
)
print(
    f"what the tank actually reached: {truth[now + 1 : now + 18].min():.3f} mg/L (limit 0.20)"
)
