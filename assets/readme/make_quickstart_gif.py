"""Draw the README quick-start GIF from the quick-start model itself.

Every number in the animation comes from the same Otwin model the README
prints: q(t), the static equilibrium, and the energy account.
"""

from pathlib import Path

import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.patches import Ellipse, FancyArrowPatch, Polygon
from style import GREY, INK, LIGHT, RED, plt

import otwin
from otwin.components.mechanical import Damper, Fixed, ForceSource, Mass, Spring

HERE = Path(__file__).resolve().parent

# ---- the quick-start model, unchanged
M, K, C = 1.0, 20.0, 0.3
mass = Mass(M, name="mass")
spring = Spring(K, name="spring")
damper = Damper(C, name="damper")
weight = ForceSource(1.0 * 9.81, name="weight")
ceiling = Fixed(name="ceiling")
system = mass >> spring >> ceiling
system.connect(mass.flange, damper.a, weight.flange)
system.connect(damper.b, ceiling.port)
run = otwin.compile(system).simulate(t_span=(0, 20), dt=0.05)

t = np.asarray(run["t"])
q = np.asarray(run["spring.extension"])
stored = np.asarray(run["energy"])
# energy over each step at the step midpoint, the way the implicit midpoint integrator accounts for it
v = np.asarray(run["mass.velocity"])
v_mid, dt = (v[1:] + v[:-1]) / 2, np.diff(t)
supplied = np.concatenate([[0.0], np.cumsum(M * 9.81 * v_mid * dt)])
dissipated = np.concatenate([[0.0], np.cumsum(C * v_mid**2 * dt)])
assert np.max(np.abs(stored - stored[0] - (supplied - dissipated))) < 1e-9
q_star = weight.force / spring.stiffness
violation = run.energy_balance()["max_violation"]

# ---- figure
fig = plt.figure(figsize=(11, 5.0), dpi=100, facecolor="white")
ax = fig.add_axes([0.02, 0.03, 0.36, 0.82])
axq = fig.add_axes([0.46, 0.36, 0.51, 0.47])
axe = fig.add_axes([0.46, 0.05, 0.51, 0.18])
fig.text(
    0.02,
    0.93,
    "Describe the parts. Otwin writes the equations.",
    fontsize=19,
    weight="bold",
    color=INK,
)
fig.text(
    0.02,
    0.885,
    "A mass on a spring and a damper, under gravity: the quick start below, simulated by the Rust engine.",
    fontsize=10.5,
    color=GREY,
)

L0, XS, XD, W, H, DX, DY = 1.0, -0.42, 0.42, 1.25, 0.42, 0.20, 0.13


def spring_path(y_top, y_bot, xc, turns=9, r=0.13):
    s = np.linspace(0, 1, 600)
    lead = 0.08
    y = y_top - (y_top - y_bot) * s
    theta = 2 * np.pi * turns * np.clip((s - lead) / (1 - 2 * lead), 0, 1)
    x = xc + r * np.sin(theta) * ((s > lead) & (s < 1 - lead))
    front = np.cos(theta) >= 0
    return x, y, front


def draw(i):
    ax.clear()
    ax.set_xlim(-1.25, 1.45)
    ax.set_ylim(-2.85, 0.32)
    ax.set_aspect("equal")
    ax.axis("off")
    qi = q[i]
    y_top = -(L0 + qi)

    # ceiling slab with hatching
    ax.add_patch(
        Polygon(
            [[-1.0, 0], [1.0, 0], [1.0 + DX, DY], [-1.0 + DX, DY]],
            closed=True,
            fc=LIGHT,
            ec=INK,
            lw=1.2,
        )
    )
    ax.plot([-1.0, 1.0], [0, 0], color=INK, lw=1.6)
    for xh in np.arange(-0.95, 1.0, 0.11):
        ax.plot([xh, xh + 0.09], [0.0, 0.1], color=INK, lw=0.6)

    # spring: back of each turn in grey, front in ink
    x, y, front = spring_path(0, y_top, XS)
    ax.plot(np.where(~front, x, np.nan), y, color=GREY, lw=1.0)
    ax.plot(np.where(front, x, np.nan), y, color=INK, lw=1.6)
    ax.text(
        XS - 0.30,
        y_top / 2,
        f"k = {K:g} N/m",
        ha="right",
        va="center",
        fontsize=10,
        color=INK,
    )

    # damper: cylinder hanging from the ceiling, rod down to the mass
    cy0, cy1, cw = -0.12, -0.80, 0.30
    ax.plot([XD, XD], [0, cy0], color=INK, lw=1.6)
    ax.add_patch(
        Polygon(
            [
                [XD - cw / 2, cy0],
                [XD + cw / 2, cy0],
                [XD + cw / 2, cy1],
                [XD - cw / 2, cy1],
            ],
            fc="white",
            ec=INK,
            lw=1.4,
        )
    )
    ax.add_patch(Ellipse((XD, cy0), cw, 0.07, fc=LIGHT, ec=INK, lw=1.2))
    ax.add_patch(Ellipse((XD, cy1), cw, 0.07, fc="white", ec=INK, lw=1.2))
    piston = max(cy1 + 0.06, min(cy0 - 0.06, y_top + 0.62))
    ax.plot([XD - cw / 2 + 0.03, XD + cw / 2 - 0.03], [piston, piston], color=INK, lw=2.4)
    ax.plot([XD, XD], [piston, y_top], color=INK, lw=2.0)
    ax.text(
        XD + 0.27,
        (cy0 + cy1) / 2,
        f"c = {C:g}\nN·s/m",
        ha="left",
        va="center",
        fontsize=10,
        color=INK,
    )

    # mass as a block
    x0, x1, yb = -W / 2, W / 2, y_top - H
    ax.add_patch(
        Polygon(
            [[x0, y_top], [x1, y_top], [x1 + DX, y_top + DY], [x0 + DX, y_top + DY]],
            fc=LIGHT,
            ec=INK,
            lw=1.3,
        )
    )
    ax.add_patch(
        Polygon(
            [[x1, y_top], [x1 + DX, y_top + DY], [x1 + DX, yb + DY], [x1, yb]],
            fc="#D6D2D1",
            ec=INK,
            lw=1.3,
        )
    )
    ax.add_patch(
        Polygon(
            [[x0, y_top], [x1, y_top], [x1, yb], [x0, yb]],
            fc="white",
            ec=INK,
            lw=1.6,
            zorder=2,
        )
    )
    ax.text(
        0,
        y_top - H / 2,
        f"m = {M:g} kg",
        ha="center",
        va="center",
        fontsize=11,
        color=INK,
        weight="bold",
        zorder=3,
    )

    # weight
    ax.add_patch(
        FancyArrowPatch(
            (0, yb - 0.02),
            (0, yb - 0.42),
            arrowstyle="-|>",
            mutation_scale=16,
            color=RED,
            lw=2,
        )
    )
    ax.text(0.08, yb - 0.28, "m g", color=RED, fontsize=11, va="center")

    # equilibrium the compiler derived
    ye = -(L0 + q_star)
    ax.plot([-1.15, 1.35], [ye, ye], color=RED, lw=1.0, ls=(0, (5, 4)), zorder=0)
    ax.text(
        1.35, ye - 0.05, "q* = m g / k", color=RED, fontsize=9.5, va="top", ha="right"
    )

    # extension dimension
    xd = -1.08
    ax.annotate(
        "",
        xy=(xd, y_top),
        xytext=(xd, -L0),
        arrowprops=dict(arrowstyle="<->", color=INK, lw=0.9),
    )
    ax.plot([xd - 0.05, XS], [-L0, -L0], color=GREY, lw=0.6, ls=":")
    ax.text(
        xd - 0.04,
        (y_top - L0) / 2 - 0.02,
        "q",
        ha="right",
        va="center",
        fontsize=11,
        style="italic",
        color=INK,
    )

    # q(t)
    axq.clear()
    axq.plot(t[: i + 1], q[: i + 1], color=INK, lw=1.8)
    axq.plot(t[i], q[i], "o", color=INK, ms=5)
    axq.axhline(q_star, color=RED, lw=1.0, ls=(0, (5, 4)))
    axq.text(
        19.8,
        0.72,
        f"q* = {q_star:.3f} m, derived by the compiler",
        color=RED,
        ha="right",
        va="bottom",
        fontsize=10,
    )
    axq.set_xlim(0, 20)
    axq.set_ylim(0, 1.0)
    axq.set_xlabel("time [s]", color=INK, fontsize=10)
    axq.set_ylabel("extension q [m]", color=INK, fontsize=10)
    axq.set_title("Position", loc="left", fontsize=11.5, color=INK, weight="bold")

    # energy account: what gravity supplied = what is stored + what the damper turned into heat
    axe.clear()
    sup, sto, dis = supplied[i], stored[i] - stored[0], dissipated[i]
    axe.barh([1], [sup], color=RED, height=0.55)
    axe.barh([0], [sto], color=INK, height=0.55)
    axe.barh([0], [dis], left=[sto], color=GREY, height=0.55)
    axe.set_xlim(0, 8.6)
    axe.set_ylim(-0.5, 1.5)
    axe.set_yticks(
        [1, 0], ["supplied by gravity", "stored + dissipated"], fontsize=10, color=INK
    )
    axe.text(sup + 0.08, 1, f"{sup:.2f} J", va="center", fontsize=10, color=RED)
    axe.text(
        sto + dis + 0.08,
        0,
        f"{sto:.2f} J stored + {dis:.2f} J heat",
        va="center",
        fontsize=10,
        color=INK,
    )
    axe.set_title(
        f"Energy account, closed at every step (largest error {violation:.1e} J)",
        loc="left",
        fontsize=11.5,
        color=INK,
        weight="bold",
    )
    axe.set_xticks([])
    for a in (axq, axe):
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            a.spines[s].set_color(GREY)
        a.tick_params(colors=GREY, labelsize=9)
    axe.spines["bottom"].set_visible(False)


frames = list(range(0, len(t), 5)) + [len(t) - 1] * 15
anim = FuncAnimation(fig, draw, frames=frames)
anim.save(HERE / "otwin-quickstart.gif", writer=PillowWriter(fps=12))
draw(len(t) - 1)
print(
    "q* =",
    round(q_star, 3),
    "max q =",
    round(q.max(), 3),
    "final q =",
    round(q[-1], 3),
    "violation",
    violation,
)
