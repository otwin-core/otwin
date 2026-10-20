"""README image: where Otwin sits between a model and a decision."""

from pathlib import Path

import matplotlib.image as mpimg
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from style import GREY, INK, LIGHT, RED, plt

HERE = Path(__file__).resolve().parent

fig = plt.figure(figsize=(11, 4.2), dpi=100, facecolor="white")
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 110)
ax.set_ylim(0, 42)
ax.axis("off")

ax.text(
    2,
    39,
    "Bring a model from anywhere. Otwin tells you whether to trust it.",
    fontsize=18,
    weight="bold",
    color=INK,
    va="top",
)

sources = [
    ("Modelica", "Dymola, OpenModelica, SystemModeler\nas an FMU"),
    ("Julia", "ModelingToolkit, SciML, Dyad\ncalled from Python"),
    ("Otwin components", "tanks, pipes, pumps, cells, inertias\ncompiled by Otwin"),
]
for k, (title, sub) in enumerate(sources):
    y = 25 - 9.5 * k
    ax.add_patch(
        FancyBboxPatch(
            (2, y),
            27,
            7.2,
            boxstyle="round,pad=0.3,rounding_size=0.8",
            fc="white",
            ec=INK,
            lw=1.3,
        )
    )
    ax.text(3.5, y + 5.6, title, fontsize=12.5, weight="bold", color=INK, va="center")
    ax.text(3.5, y + 2.2, sub, fontsize=9.3, color=GREY, va="center", linespacing=1.3)
    ax.add_patch(
        FancyArrowPatch(
            (29.8, y + 3.6),
            (39.2, 18.6),
            arrowstyle="-|>",
            mutation_scale=14,
            color=GREY,
            lw=1.2,
            connectionstyle="arc3,rad=0",
        )
    )

ax.add_patch(
    FancyBboxPatch(
        (40, 11), 17, 15, boxstyle="round,pad=0.3,rounding_size=1.0", fc=INK, ec=INK
    )
)
mark = mpimg.imread(HERE.parent / "brand" / "otwin-mark-1a-square.png")
ax.imshow(mark, extent=(43.2, 49.2, 17.6, 23.6), zorder=3)
ax.text(50.0, 20.6, "otwin", fontsize=17, weight="bold", color="white", va="center")
ax.text(
    48.5,
    14.6,
    "with the machine's\nown measurements",
    fontsize=9.3,
    color=LIGHT,
    ha="center",
    va="center",
    linespacing=1.3,
)

answers = [
    ("How wrong has it been?", "measured on data it never saw"),
    ("Is it better than a trivial guess?", "scored against the hardest baseline"),
    ("Does its 90 % range hold 90 %?", "coverage measured, not assumed"),
    ("When should someone act?", "or: not enough evidence yet"),
]
for k, (q, a) in enumerate(answers):
    y = 27.5 - 7.4 * k
    ax.add_patch(
        FancyArrowPatch(
            (57.8, 18.6),
            (66.2, y + 2.6),
            arrowstyle="-|>",
            mutation_scale=14,
            color=RED,
            lw=1.2,
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (67, y),
            41,
            5.4,
            boxstyle="round,pad=0.25,rounding_size=0.8",
            fc="white",
            ec=RED,
            lw=1.3,
        )
    )
    ax.text(68.4, y + 3.75, q, fontsize=12, weight="bold", color=INK, va="center")
    ax.text(68.4, y + 1.35, a, fontsize=9.5, color=GREY, va="center")
fig.savefig(HERE / "otwin-what-it-adds.png", dpi=100)
print("saved")
