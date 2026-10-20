"""README image for the ModelingToolkit example: runs examples/julia_mtk_tank.py.

Needs juliacall with ModelingToolkit and OrdinaryDiffEq (see that script).
"""

import os
import runpy
from pathlib import Path

import numpy as np
from style import GREY, INK, RED, clean, header, plt

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parents[1] / "examples"

os.chdir(EXAMPLES)
g = runpy.run_path("julia_mtk_tank.py")  # prints the evaluation report
reading, level, JuliaTank = g["reading"], g["level"], g["JuliaTank"]
report = g["report"]
rmse_model = report.point_metrics["rmse"]
rmse_base = report.baseline_metrics["rmse"]

origin = 28 * 24  # midnight, day 29
model = np.ravel(JuliaTank().forecast(reading[: origin + 1], 24))
yesterday = reading[origin + 1 - 24 : origin + 1]
hours_past = np.arange(origin - 47, origin + 1)
hours_fc = np.arange(origin + 1, origin + 25)

fig = plt.figure(figsize=(11, 4.9), dpi=100, facecolor="white")
ax = fig.add_axes([0.07, 0.26, 0.62, 0.55])
header(
    fig,
    "A ModelingToolkit model, checked with Otwin",
    "Water level in a town's storage tank. The model is written in Julia and called from Python.",
)
ax.plot(
    hours_past - origin,
    reading[hours_past],
    "o",
    color=GREY,
    ms=3,
    label="sensor readings",
)
ax.plot(
    hours_fc - origin,
    level[hours_fc],
    color=GREY,
    lw=1.5,
    label="what the tank actually did",
)
ax.plot(
    hours_fc - origin,
    model,
    color=INK,
    lw=2,
    ls=(0, (6, 3)),
    label="ModelingToolkit model, design demand profile",
)
ax.plot(
    hours_fc - origin,
    yesterday,
    color=RED,
    lw=1.6,
    label="trivial forecast: same as yesterday",
)
ax.axvline(0, color=GREY, lw=0.8, ls=":")
ax.text(0.4, ax.get_ylim()[1], "now, 00:00", color=GREY, fontsize=9.5, va="top")
ax.set_xlim(-48, 24)
ax.set_xticks(
    [-48, -36, -24, -12, 0, 6, 12, 18, 24],
    ["00:00", "12:00", "00:00", "12:00", "00:00", "06:00", "12:00", "18:00", "24:00"],
)
ax.set_ylabel("level [m]", color=INK, fontsize=10)
clean(ax)
ax.legend(
    loc="upper left", bbox_to_anchor=(0, -0.13), frameon=False, fontsize=9.5, ncol=2
)

side = fig.add_axes([0.73, 0.26, 0.26, 0.55])
side.axis("off")
side.text(
    0,
    0.98,
    "Error on 24 h forecasts it\nhad not seen (5 windows)",
    fontsize=11.5,
    weight="bold",
    color=INK,
    va="top",
)
side.text(0, 0.70, "ModelingToolkit model", fontsize=10.5, color=GREY, va="top")
side.text(
    0,
    0.625,
    f"{rmse_model * 100:.1f} cm",
    fontsize=16,
    weight="bold",
    color=INK,
    va="top",
)
side.text(0, 0.45, "Same as yesterday", fontsize=10.5, color=GREY, va="top")
side.text(
    0, 0.375, f"{rmse_base * 100:.1f} cm", fontsize=16, weight="bold", color=RED, va="top"
)
side.text(
    0,
    0.17,
    "Correct equations, wrong demand profile.\nFit the profile before using the twin.",
    fontsize=10.5,
    color=INK,
    va="top",
)
fig.savefig(HERE / "otwin-julia-tank.png", dpi=100)
print("rmse model", rmse_model, "baseline", rmse_base)
