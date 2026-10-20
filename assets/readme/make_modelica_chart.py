"""README image for the Modelica example: runs examples/modelica_fmu_chlorine.py and draws day 21.

Needs Dahlquist.fmu in examples/ (see that script).
"""

import os
import runpy
from pathlib import Path

import numpy as np
from style import GREY, INK, PINK, RED, clean, header, plt

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parents[1] / "examples"

os.chdir(EXAMPLES)
g = runpy.run_path("modelica_fmu_chlorine.py")
reading, truth, band, fmu_forecast, now = (
    g["reading"],
    g["truth"],
    g["band"],
    g["fmu_forecast"],
    g["now"],
)

forecast = fmu_forecast(reading[:now], 17)
lower, upper = band.apply(forecast)
hours_past = np.arange(now - 30, now + 1)
hours_fc = np.arange(now + 1, now + 18)
clock = lambda h: h - 20 * 24  # hours since midnight of day 21

fig = plt.figure(figsize=(11, 4.9), dpi=100, facecolor="white")
ax = fig.add_axes([0.07, 0.26, 0.62, 0.55])
header(
    fig,
    "A Modelica model, checked with Otwin",
    "Chlorine in a storage tank, dosed once a day. The model comes from a Modelica tool as an FMU.",
)
ax.fill_between(
    clock(hours_fc),
    lower,
    upper,
    color=PINK,
    lw=0,
    label="Otwin's 90 % range, calibrated on 20 past days",
)
ax.plot(
    clock(hours_fc),
    forecast,
    color=INK,
    lw=2,
    ls=(0, (6, 3)),
    label="Modelica model alone",
)
ax.plot(
    clock(hours_past),
    reading[hours_past],
    "o",
    color=GREY,
    ms=3.5,
    label="sensor readings",
)
ax.plot(
    clock(hours_fc),
    truth[hours_fc],
    color=GREY,
    lw=1.5,
    label="what the tank actually did",
)
ax.axhline(0.20, color=RED, lw=1.4)
ax.text(
    clock(now) - 29.5,
    0.205,
    "minimum allowed: 0.20 mg/L",
    color=RED,
    fontsize=10,
    va="bottom",
)
ax.axvline(clock(now), color=GREY, lw=0.8, ls=":")
ax.text(clock(now) + 0.4, 1.04, "now, 06:00", color=GREY, fontsize=9.5, va="top")
ax.set_xlim(clock(now) - 30, clock(now) + 18)
ax.set_ylim(0.1, 1.05)
ax.set_xticks(
    [-24, -12, 0, 6, 12, 18, 23],
    ["00:00\nday 20", "12:00", "00:00\nday 21", "06:00", "12:00", "18:00", "23:00"],
)
ax.set_ylabel("free chlorine [mg/L]", color=INK, fontsize=10)
clean(ax)
ax.legend(loc="upper left", bbox_to_anchor=(0, -0.2), frameon=False, fontsize=9.5, ncol=2)

side = fig.add_axes([0.73, 0.26, 0.26, 0.55])
side.axis("off")
rows = [
    ("Modelica model alone", f"{forecast.min():.2f} mg/L", INK),
    ("Otwin's range, lower edge", f"{lower.min():.2f} mg/L", RED),
    ("What the tank reached", f"{truth[hours_fc].min():.2f} mg/L", GREY),
]
side.text(
    0,
    0.98,
    "Lowest chlorine before the next dose",
    fontsize=11.5,
    weight="bold",
    color=INK,
    va="top",
)
for k, (label, value, colour) in enumerate(rows):
    y = 0.80 - 0.2 * k
    side.text(0, y, label, fontsize=10.5, color=GREY, va="top")
    side.text(0, y - 0.075, value, fontsize=16, weight="bold", color=colour, va="top")
side.text(
    0,
    0.08,
    "The range held 91 % of the time\non 10 days it never saw.",
    fontsize=10.5,
    color=INK,
    va="top",
)
fig.savefig(HERE / "otwin-modelica-chlorine.png", dpi=100)
print("saved")
