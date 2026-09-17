"""Schematics in the style of Spring.png (python assets/draw_schematics.py): black strokes, one blue element,
italic math labels, white background."""

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle

plt.rcParams.update({"mathtext.fontset": "cm", "font.size": 30})
BLUE = "#4a4af0"
LW = 6


def new(w=11, h=10):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def line(ax, pts, lw=LW, color="k", **kw):
    p = np.asarray(pts)
    ax.plot(
        p[:, 0],
        p[:, 1],
        color=color,
        lw=lw,
        solid_capstyle="round",
        solid_joinstyle="round",
        **kw,
    )


def label(ax, x, y, s, **kw):
    kw.setdefault("fontsize", 34)
    ax.text(x, y, s, ha=kw.pop("ha", "center"), va=kw.pop("va", "center"), **kw)


def arrow(ax, p0, p1, lw=3, ms=30):
    ax.add_patch(
        FancyArrowPatch(
            p0,
            p1,
            arrowstyle="-|>",
            mutation_scale=ms,
            lw=lw,
            color="k",
            shrinkA=0,
            shrinkB=0,
        )
    )


def resistor(ax, x0, x1, y, amp=0.28, n=6, vertical=False):
    """Zigzag between (x0,y) and (x1,y) (or vertical between y0=x0,y1=x1 at x=y)."""
    t = np.linspace(0, 1, 2 * n + 2)
    z = np.zeros_like(t)
    z[1:-1] = amp * np.where(np.arange(2 * n) % 2 == 0, 1, -1)
    if not vertical:
        xs = x0 + (x1 - x0) * t
        ys = y + z
    else:
        ys = x0 + (x1 - x0) * t
        xs = y + z
    line(ax, np.c_[xs, ys])


def capacitor(ax, x, y, gap=0.22, plate=0.7, vertical=False):
    if vertical:
        line(ax, [(x - plate / 2, y + gap / 2), (x + plate / 2, y + gap / 2)])
        line(ax, [(x - plate / 2, y - gap / 2), (x + plate / 2, y - gap / 2)])
    else:
        line(ax, [(x - gap / 2, y - plate / 2), (x - gap / 2, y + plate / 2)])
        line(ax, [(x + gap / 2, y - plate / 2), (x + gap / 2, y + plate / 2)])


def source_circle(ax, x, y, r=0.6, fill=False):
    ax.add_patch(Circle((x, y), r, fc=BLUE if fill else "white", ec="k", lw=LW, zorder=3))


def dot(ax, x, y):
    ax.add_patch(Circle((x, y), 0.11, fc="k", ec="k", zorder=4))


def ground(ax, x, y):
    line(ax, [(x, y), (x, y - 0.5)])
    for i, w in enumerate((1.0, 0.65, 0.3)):
        line(ax, [(x - w / 2, y - 0.5 - 0.3 * i), (x + w / 2, y - 0.5 - 0.3 * i)])


def hatch_wall(ax, x0, x1, y, n=14, up=True):
    line(ax, [(x0, y), (x1, y)], lw=8)
    for x in np.linspace(x0 + 0.4, x1 - 0.1, n):
        d = 0.45 if up else -0.45
        line(ax, [(x, y), (x - 0.45, y + d)], lw=2.5)


# ------------------------------------------------------------- 1. battery
fig, ax = new(12, 9.5)
yt, yb = 6.0, 0.0  # top rail, bottom rail
# OCV source (blue, the store)
source_circle(ax, 0.0, 3.0, r=0.75, fill=True)
label(ax, 0.0, 3.32, "+", color="white", fontsize=30)
label(ax, 0.0, 2.62, "−", color="white", fontsize=30)
label(ax, -1.25, 3.0, r"$V_{oc}(q)$", ha="right")
line(ax, [(0, 3.75), (0, yt)])
line(ax, [(0, 2.25), (0, yb)])
# R0
line(ax, [(0, yt), (1.0, yt)])
resistor(ax, 1.0, 3.0, yt)
label(ax, 2.0, yt + 0.8, r"$R_0$")
# RC pair 1
x1, x2 = 3.6, 5.6
line(ax, [(3.0, yt), (x1, yt)])
dot(ax, x1, yt)
line(ax, [(x1, yt), (x1, yt + 1.0), (x1, yt + 1.0)])
resistor(ax, x1, x2, yt + 1.0)
line(ax, [(x2, yt + 1.0), (x2, yt)])
line(ax, [(x1, yt), (x1, yt - 1.0), (x2 / 2 + x1 / 2 - 0.11, yt - 1.0)])
capacitor(ax, (x1 + x2) / 2, yt - 1.0)
line(ax, [((x1 + x2) / 2 + 0.11, yt - 1.0), (x2, yt - 1.0), (x2, yt)])
dot(ax, x2, yt)
label(ax, (x1 + x2) / 2, yt + 1.75, r"$R_1$")
label(ax, (x1 + x2) / 2, yt - 1.95, r"$C_1$")
# RC pair 2
x3, x4 = 6.2, 8.2
line(ax, [(x2, yt), (x3, yt)])
dot(ax, x3, yt)
line(ax, [(x3, yt), (x3, yt + 1.0)])
resistor(ax, x3, x4, yt + 1.0)
line(ax, [(x4, yt + 1.0), (x4, yt)])
line(ax, [(x3, yt), (x3, yt - 1.0), ((x3 + x4) / 2 - 0.11, yt - 1.0)])
capacitor(ax, (x3 + x4) / 2, yt - 1.0)
line(ax, [((x3 + x4) / 2 + 0.11, yt - 1.0), (x4, yt - 1.0), (x4, yt)])
dot(ax, x4, yt)
label(ax, (x3 + x4) / 2, yt + 1.75, r"$R_2$")
label(ax, (x3 + x4) / 2, yt - 1.95, r"$C_2$")
# terminals and load (current source)
xl = 10.0
line(ax, [(x4, yt), (xl, yt), (xl, 3.75)])
dot(ax, xl, yt)
label(ax, xl + 0.45, yt + 0.5, r"$p$")
source_circle(ax, xl, 3.0, r=0.75)
arrow(ax, (xl, 2.45), (xl, 3.6), lw=4, ms=28)
label(ax, xl + 1.05, 3.0, r"$I$", ha="left")
line(ax, [(xl, 2.25), (xl, yb), (0, yb)])
dot(ax, xl, yb)
label(ax, xl + 0.45, yb - 0.55, r"$n$")
ground(ax, 7.5, yb)
# heat: losses -> thermal mass -> convection -> ambient
xt = 5.0
yth = -3.2
ax.add_patch(Rectangle((xt - 1.6, yth - 0.7), 3.2, 1.4, fc=BLUE, ec="k", lw=LW, zorder=3))
label(ax, xt, yth, r"$C_{th},\ T$", color="white")
arrow(ax, (0.2, yth), (xt - 1.75, yth), lw=3.5, ms=28)
label(ax, 1.3, yth + 1.0, r"$\dot Q = \sum I^2 R$")
# convection resistor to ambient
resistor(ax, xt + 1.6, xt + 4.0, yth, amp=0.25, n=5)
label(ax, xt + 2.8, yth + 0.8, r"$hA$")
line(ax, [(xt + 4.0, yth - 1.0), (xt + 4.0, yth + 1.0)], lw=8)
for yy in np.linspace(yth - 0.9, yth + 0.9, 6):
    line(ax, [(xt + 4.0, yy), (xt + 4.45, yy + 0.4)], lw=2.5)
label(ax, xt + 4.75, yth, r"$T_{amb}$", ha="left")
ax.set_xlim(-2.6, 12.6)
ax.set_ylim(-4.6, 8.4)
fig.savefig("assets/Battery.png", dpi=180, bbox_inches="tight", facecolor="white")
plt.close(fig)

# ------------------------------------------------------------- 2. pump line
fig, ax = new(13, 8)
# reservoir (open tank) with water
tx0, tx1, ty0 = 0.0, 4.0, 0.0
line(ax, [(tx0, 4.0), (tx0, ty0), (tx1, ty0), (tx1, 4.0)])
ax.add_patch(
    Rectangle(
        (tx0 + 0.05, ty0 + 0.05), tx1 - tx0 - 0.1, 3.0, fc=BLUE, ec="none", zorder=1
    )
)
label(ax, 2.0, 1.6, r"$A$", color="white")
# level dimension
arrow(ax, (-0.8, ty0), (-0.8, 3.05), lw=2.5, ms=22)
arrow(ax, (-0.8, 3.05), (-0.8, ty0), lw=2.5, ms=22)
label(ax, -1.3, 1.55, r"$h$", ha="right")
line(ax, [(-1.1, 3.05), (tx0, 3.05)], lw=2)
line(ax, [(-1.1, ty0), (tx0, ty0)], lw=2)
# suction pipe from tank base to pump
yp = -1.6
line(ax, [(tx1 * 0.5, ty0), (tx1 * 0.5, yp), (6.0, yp)])
label(ax, 4.3, yp - 0.75, r"$R_s$")
# pump: circle with impeller triangle
px = 7.0
source_circle(ax, px, yp, r=1.0)
ax.add_patch(
    Polygon(
        [(px - 0.55, yp - 0.55), (px + 0.65, yp), (px - 0.55, yp + 0.55)],
        closed=True,
        fc="k",
        ec="k",
        zorder=4,
    )
)
label(ax, px, yp + 1.75, r"$\Delta p(Q)$")
line(ax, [(px + 1.0, yp), (9.5, yp)])
# flow arrow
arrow(ax, (8.4, yp + 0.9), (9.4, yp + 0.9), lw=3, ms=26)
label(ax, 8.9, yp + 1.5, r"$Q$")
# filter: box with hatching
fx0, fx1 = 9.5, 11.7
ax.add_patch(
    Rectangle((fx0, yp - 0.75), fx1 - fx0, 1.5, fc="white", ec="k", lw=LW, zorder=3)
)
for x in np.linspace(fx0 + 0.15, fx1 - 0.65, 6):
    ax.plot([x, x + 0.5], [yp - 0.75, yp + 0.75], color="k", lw=3, zorder=5)
label(ax, (fx0 + fx1) / 2, yp - 1.55, r"$R_f\,(1+\varphi)$")
# outfall: open discharge to atmosphere
line(ax, [(fx1, yp), (13.2, yp), (13.2, yp - 0.6)])
arrow(ax, (13.2, yp - 0.6), (13.2, yp - 1.7), lw=5, ms=34)
label(ax, 13.2, yp + 0.75, r"$p_{atm}$")
ax.set_xlim(-2.4, 14.2)
ax.set_ylim(-4.2, 4.8)
fig.savefig("assets/Pump_line.png", dpi=180, bbox_inches="tight", facecolor="white")
plt.close(fig)

# ------------------------------------------------------------- 3. dc motor drive
fig, ax = new(16, 6.2)
yt, yb = 4.0, 0.0
# supply
source_circle(ax, 0.0, 2.0, r=0.75)
label(ax, 0.0, 2.32, "+", fontsize=30)
label(ax, 0.0, 1.62, "−", fontsize=30)
label(ax, -1.2, 2.0, r"$V$", ha="right")
line(ax, [(0, 2.75), (0, yt), (1.0, yt)])
line(ax, [(0, 1.25), (0, yb)])
# R
resistor(ax, 1.0, 3.0, yt)
label(ax, 2.0, yt + 0.8, r"$R$")
# L: coil bumps
line(ax, [(3.0, yt), (3.5, yt)])
for i in range(4):
    th = np.linspace(np.pi, 0, 30)
    cx = 3.5 + 0.45 + i * 0.9
    line(ax, np.c_[cx + 0.45 * np.cos(th), yt + 0.45 * np.sin(th)])
line(ax, [(3.5 + 3.6, yt), (7.6, yt)])
label(ax, 5.3, yt + 1.05, r"$L$")
# electromechanical coupling: the machine, a circle marked k
xc = 9.6
ax.add_patch(Circle((xc, 2.0), 1.0, fc="white", ec="k", lw=LW, zorder=3))
line(ax, [(7.6, yt), (xc, yt), (xc, 3.0)])
line(ax, [(xc, 1.0), (xc, yb), (0, yb)])
label(ax, xc, 2.0, r"$k$")
arrow(ax, (1.3, yt - 0.8), (2.5, yt - 0.8), lw=3, ms=24)
label(ax, 1.9, yt - 1.35, r"$i$")
label(ax, xc + 1.3, 3.55, r"$e = k\,\omega$", ha="left")
ground(ax, 4.8, yb)
# shaft to the right
line(ax, [(xc + 1.0, 2.0), (17.2, 2.0)], lw=8)
label(ax, 12.8, 1.15, r"$\omega,\ \tau = k\,i$")
# rotor inertia: blue disk
ax.add_patch(Circle((15.2, 2.0), 0.9, fc=BLUE, ec="k", lw=LW, zorder=3))
label(ax, 15.2, 2.0, r"$J$", color="white")
# fan / friction load: damper to housing
xd = 17.2
line(ax, [(xd, 2.0), (xd, 0.9)])
ax.add_patch(Rectangle((xd - 0.5, -0.2), 1.0, 1.1, fc="white", ec="k", lw=LW, zorder=3))
line(ax, [(xd - 0.25, 0.35), (xd + 0.25, 0.35)], lw=5)
line(ax, [(xd, -0.2), (xd, -0.9)])
hatch_wall(ax, xd - 1.0, xd + 1.0, -0.9, n=6, up=False)
label(ax, xd + 0.8, 0.55, r"$b\,\omega|\omega|$", ha="left")
ax.set_xlim(-2.2, 20.8)
ax.set_ylim(-2.2, 5.6)
fig.savefig("assets/Motor_drive.png", dpi=180, bbox_inches="tight", facecolor="white")
plt.close(fig)
print("ok")
