"""The artwork of the tutorials: a hero illustration and a process diagram each.

Every image is drawn here, from code, in one style: an engineering drawing
sheet with a title block, isometric shaded views for the hero images, and
process diagrams with ISA-5.1 symbols (vessels, pumps, valves, instrument
bubbles) or IEC 60617 symbols (resistor, capacitor, inductor, sources,
transformer) as the domain requires. Run::

    python assets/tutorials/make_art.py

and the files land in ``tutorials/images/``. The README header is drawn here too.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import (  # noqa: E402
    Circle,
    Ellipse,
    FancyBboxPatch,
    Polygon,
    Rectangle,
)
from matplotlib.transforms import Affine2D  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "tutorials" / "images"

INK, RED, GREY, LIGHT, PAPER = "#1d1d1f", "#7a2ffc", "#6e6e73", "#ececf0", "#ffffff"
STEEL = ("#babac0", "#8f8f96", "#6a6a71")  # top, light side, dark side
CONCRETE = ("#d6d6db", "#b2b2b8", "#8e8e95")
WATER = ("#d8c6ff", "#b795ff", "#9065e8")
RUST = ("#a07bff", "#7a2ffc", "#6319e0")
DARK = ("#5e5e65", "#3f3f46", "#27272c")
for name in ("Helvetica Neue", "Helvetica", "Arial", "Liberation Sans", "DejaVu Sans"):
    if any(name == f.name for f in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break

# ----------------------------------------------------------------- the sheet


def sheet(title: str, subtitle: str, number: str, w: float = 16, h: float = 7) -> tuple:
    """A drawing sheet: paper, double border, and a title block bottom right."""
    fig = plt.figure(figsize=(w, h), dpi=110)
    fig.patch.set_facecolor(PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    ax.add_patch(Rectangle((0.25, 0.25), w - 0.5, h - 0.5, fill=False, lw=1.6, ec=INK))
    ax.add_patch(Rectangle((0.33, 0.33), w - 0.66, h - 0.66, fill=False, lw=0.5, ec=GREY))
    # faint grid, like a drafting sheet
    for x in np.arange(0.5, w - 0.4, 0.5):
        ax.plot([x, x], [0.33, h - 0.33], color=LIGHT, lw=0.35, zorder=0)
    for y in np.arange(0.5, h - 0.4, 0.5):
        ax.plot([0.33, w - 0.33], [y, y], color=LIGHT, lw=0.35, zorder=0)
    # title block
    bw, bh = 6.6, 1.15
    x0, y0 = w - 0.33 - bw, 0.33
    ax.add_patch(Rectangle((x0, y0), bw, bh, fc=PAPER, ec=INK, lw=1.2, zorder=5))
    ax.plot([x0, x0 + bw], [y0 + bh * 0.52, y0 + bh * 0.52], color=INK, lw=0.8, zorder=6)
    ax.plot([x0 + bw * 0.68, x0 + bw * 0.68], [y0, y0 + bh], color=INK, lw=0.8, zorder=6)
    fs = 11.5 if len(title) <= 34 else 9.5 if len(title) <= 46 else 8.2
    ax.text(
        x0 + 0.12,
        y0 + bh * 0.74,
        title.upper(),
        fontsize=fs,
        weight="bold",
        color=INK,
        va="center",
        zorder=7,
    )
    ax.text(
        x0 + 0.12,
        y0 + bh * 0.26,
        subtitle,
        fontsize=8.2,
        color=GREY,
        va="center",
        zorder=7,
    )
    ax.text(
        x0 + bw * 0.84,
        y0 + bh * 0.74,
        "OTWIN",
        fontsize=10,
        weight="bold",
        color=RED,
        ha="center",
        va="center",
        zorder=7,
    )
    ax.text(
        x0 + bw * 0.84,
        y0 + bh * 0.26,
        number,
        fontsize=8.5,
        color=INK,
        ha="center",
        va="center",
        zorder=7,
    )
    return fig, ax


def save(fig: plt.Figure, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=110, facecolor=PAPER)
    plt.close(fig)
    print("wrote", OUT / name)


# ---------------------------------------------------------- isometric helpers

C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))
_REC: list[tuple[float, float]] | None = None


def iso(
    x: float, y: float, z: float, ox: float = 0.0, oy: float = 0.0, s: float = 1.0
) -> tuple[float, float]:
    """Isometric projection of a point, with an origin offset and a scale."""
    pt = (ox + s * (x - y) * C30, oy + s * ((x + y) * S30 + z))
    if _REC is not None:
        _REC.append(pt)
    return pt


def fit_scene(ax, scene, box=(0.6, 1.75, 15.4, 6.55), pad=0.35):
    """Draw ``scene(ax, ox, oy, s)`` scaled and placed to fill ``box`` on the sheet.

    The scene is first drawn on a scratch axes with every projected point
    recorded, so its extent is known; it is then redrawn at the scale and
    offset that fit the box. Nothing is clipped by the sheet or the title block.
    """
    global _REC
    scratch = plt.figure().add_subplot()
    _REC = []
    scene(scratch, 0.0, 0.0, 1.0)
    pts = np.array(_REC)
    _REC = None
    plt.close(scratch.figure)
    x0, y0, x1, y1 = box
    (px0, py0), (px1, py1) = pts.min(axis=0), pts.max(axis=0)
    s = min((x1 - x0 - 2 * pad) / (px1 - px0), (y1 - y0 - 2 * pad) / (py1 - py0))
    ox = (x0 + x1) / 2 - s * (px0 + px1) / 2
    oy = (y0 + y1) / 2 - s * (py0 + py1) / 2
    scene(ax, ox, oy, s)


def box(
    ax,
    x,
    y,
    z,
    dx,
    dy,
    dz,
    shades=STEEL,
    ox=0.0,
    oy=0.0,
    s=1.0,
    lw=0.6,
    zorder=3,
    ec=None,
):
    """A shaded isometric box: top, left (x face) and right (y face) visible."""
    p = lambda a, b, c: iso(a, b, c, ox, oy, s)  # noqa: E731
    ec = ec or INK
    top = [
        p(x, y, z + dz),
        p(x + dx, y, z + dz),
        p(x + dx, y + dy, z + dz),
        p(x, y + dy, z + dz),
    ]
    left = [p(x, y, z), p(x + dx, y, z), p(x + dx, y, z + dz), p(x, y, z + dz)]
    right = [
        p(x + dx, y, z),
        p(x + dx, y + dy, z),
        p(x + dx, y + dy, z + dz),
        p(x + dx, y, z + dz),
    ]
    for poly, col in ((right, shades[2]), (left, shades[1]), (top, shades[0])):
        ax.add_patch(Polygon(poly, closed=True, fc=col, ec=ec, lw=lw, zorder=zorder))


def cylinder(
    ax, x, y, z, r, h, shades=STEEL, ox=0.0, oy=0.0, s=1.0, zorder=3, lw=0.6, n=48
):
    """A shaded vertical isometric cylinder with a lid."""
    th = np.linspace(0, 2 * np.pi, n)
    ring = lambda zz: [
        iso(x + r * np.cos(t), y + r * np.sin(t), zz, ox, oy, s) for t in th
    ]  # noqa: E731
    bottom, top = ring(z), ring(z + h)
    # side as vertical strips with a lighting gradient
    for i in range(n - 1):
        ang = (th[i] + th[i + 1]) / 2
        light = 0.5 + 0.5 * np.cos(ang - np.radians(225))
        col = _mix(shades[2], shades[0], light)
        quad = [bottom[i], bottom[i + 1], top[i + 1], top[i]]
        ax.add_patch(Polygon(quad, closed=True, fc=col, ec=col, lw=0.3, zorder=zorder))
    ax.add_patch(
        Polygon(top, closed=True, fc=shades[0], ec=INK, lw=lw, zorder=zorder + 0.1)
    )
    # silhouette
    pts = np.array(bottom)
    ax.plot(pts[:, 0], pts[:, 1], color=INK, lw=lw * 0.8, zorder=zorder + 0.1)


def _mix(c1: str, c2: str, t: float) -> str:
    a, b = np.array(matplotlib.colors.to_rgb(c1)), np.array(matplotlib.colors.to_rgb(c2))
    return matplotlib.colors.to_hex((1 - t) * a + t * b)


def pipe(ax, pts, width=7, color=STEEL[1], ox=0.0, oy=0.0, s=1.0, zorder=4):
    """A pipe along isometric 3-D points, drawn as a thick line with a highlight."""
    q = np.array([iso(*p, ox, oy, s) for p in pts])
    ax.plot(
        q[:, 0], q[:, 1], color=INK, lw=width + 1.6, solid_capstyle="round", zorder=zorder
    )
    ax.plot(
        q[:, 0],
        q[:, 1],
        color=color,
        lw=width,
        solid_capstyle="round",
        zorder=zorder + 0.1,
    )
    ax.plot(
        q[:, 0] - 0.02,
        q[:, 1] + 0.04,
        color=_mix(color, "#FFFFFF", 0.55),
        lw=width * 0.3,
        solid_capstyle="round",
        zorder=zorder + 0.2,
    )


def ground_plane(ax, ox, oy, s, size=8.0, shade="#e4e4e8"):
    p = [
        iso(0, 0, 0, ox, oy, s),
        iso(size, 0, 0, ox, oy, s),
        iso(size, size, 0, ox, oy, s),
        iso(0, size, 0, ox, oy, s),
    ]
    ax.add_patch(Polygon(p, closed=True, fc=shade, ec=GREY, lw=0.6, zorder=1))
    for k in np.arange(0, size + 0.01, 1.0):
        a, b = iso(k, 0, 0, ox, oy, s), iso(k, size, 0, ox, oy, s)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#d2d2d7", lw=0.4, zorder=1.1)
        a, b = iso(0, k, 0, ox, oy, s), iso(size, k, 0, ox, oy, s)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#d2d2d7", lw=0.4, zorder=1.1)


def callout(ax, xy, text, dxy=(1.2, 0.8)):
    x, y = xy
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(x + dxy[0], y + dxy[1]),
        fontsize=8.5,
        color=INK,
        arrowprops=dict(arrowstyle="-", color=INK, lw=0.7, shrinkA=0, shrinkB=2),
        zorder=9,
        bbox=dict(boxstyle="square,pad=0.25", fc=PAPER, ec=INK, lw=0.6),
    )


def water_surface(ax, x, y, z, r, ox, oy, s, n=48):
    th = np.linspace(0, 2 * np.pi, n)
    ring = [iso(x + r * np.cos(t), y + r * np.sin(t), z, ox, oy, s) for t in th]
    ax.add_patch(Polygon(ring, closed=True, fc=WATER[0], ec=WATER[2], lw=0.5, zorder=3.3))


# ---------------------------------------------------------------- hero scenes


def wheel(ax, cx, cy, r, ox, oy, s, zorder=4):
    """A wheel seen in the isometric plane: tyre, rim, hub."""
    ax.add_patch(
        Ellipse(
            (cx, cy),
            2 * r * 0.75,
            2 * r,
            angle=-30,
            fc=DARK[2],
            ec=INK,
            lw=0.7,
            zorder=zorder,
        )
    )
    ax.add_patch(
        Ellipse(
            (cx, cy),
            2 * r * 0.45,
            2 * r * 0.6,
            angle=-30,
            fc=STEEL[0],
            ec=INK,
            lw=0.5,
            zorder=zorder + 0.1,
        )
    )
    ax.add_patch(
        Ellipse(
            (cx, cy),
            2 * r * 0.12,
            2 * r * 0.16,
            angle=-30,
            fc=INK,
            ec=INK,
            lw=0.5,
            zorder=zorder + 0.2,
        )
    )


def zigzag(ax, p0, p1, n=7, amp=0.12, color=INK, lw=1.4, zorder=5):
    p0, p1 = np.array(p0), np.array(p1)
    d = p1 - p0
    L = np.hypot(*d)
    u, v = d / L, np.array([-d[1], d[0]]) / L
    pts = [p0]
    for i in range(1, 2 * n):
        pts.append(p0 + u * (L * i / (2 * n)) + v * amp * (1 if i % 2 else -1))
    pts.append(p1)
    pts = np.array(pts)
    ax.plot(
        pts[:, 0], pts[:, 1], color=color, lw=lw, zorder=zorder, solid_joinstyle="round"
    )


def readme_header():
    fig = plt.figure(figsize=(16, 5.2), dpi=120)
    fig.patch.set_facecolor(PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 5.2)
    ax.axis("off")
    ax.add_patch(Rectangle((0.2, 0.2), 15.6, 4.8, fill=False, lw=1.5, ec=INK))
    for x in np.arange(0.5, 15.6, 0.5):
        ax.plot([x, x], [0.25, 4.95], color=LIGHT, lw=0.3, zorder=0)
    for y in np.arange(0.5, 4.95, 0.5):
        ax.plot([0.25, 15.75], [y, y], color=LIGHT, lw=0.3, zorder=0)

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 10, shade="#ebebef")
        box(
            ax,
            0.5,
            1.0,
            0,
            3.6,
            1.5,
            1.8,
            shades=("#d8d8dc", "#c2c2c7", "#a0a0a6"),
            ox=ox,
            oy=oy,
            s=s,
        )  # BESS
        box(ax, 1.0, 1.3, 1.8, 0.9, 1.0, 0.5, shades=STEEL, ox=ox, oy=oy, s=s, zorder=3.5)
        cylinder(
            ax, 6.5, 1.5, 0, 1.0, 1.3, shades=CONCRETE, ox=ox, oy=oy, s=s
        )  # reservoir
        water_surface(ax, 6.5, 1.5, 1.2, 0.95, ox, oy, s)
        pipe(
            ax,
            [(7.5, 1.5, 0.3), (8.8, 1.5, 0.3), (8.8, 5.0, 0.3), (8.8, 5.0, 3.0)],
            width=3.5,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        for lx, ly in ((8.5, 4.7), (9.1, 4.7), (8.5, 5.3), (9.1, 5.3)):
            box(
                ax,
                lx,
                ly,
                0,
                0.12,
                0.12,
                3.0,
                shades=STEEL,
                ox=ox,
                oy=oy,
                s=s,
                zorder=3.4,
            )
        cylinder(
            ax,
            8.8,
            5.0,
            3.0,
            0.8,
            0.9,
            shades=("#f1eaff", "#c4c4ca", "#93939a"),
            ox=ox,
            oy=oy,
            s=s,
            zorder=4,
        )
        cylinder(
            ax,
            3.5,
            6.5,
            0,
            0.3,
            4.5,
            shades=("#e6e6e9", "#cfcfd4", "#9f9fa6"),
            ox=ox,
            oy=oy,
            s=s,
        )  # turbine
        hub = iso(3.3, 6.5, 4.8, ox, oy, s)
        ax.add_patch(Circle(hub, 0.2 * s, fc=STEEL[0], ec=INK, lw=0.6, zorder=6))
        for ang in (90, 210, 330):
            a = math.radians(ang)
            tip = (hub[0] + 2.2 * s * math.cos(a), hub[1] + 2.2 * s * math.sin(a))
            w = 0.14 * s
            n = (-math.sin(a) * w, math.cos(a) * w)
            ax.add_patch(
                Polygon(
                    [(hub[0] + n[0], hub[1] + n[1]), (hub[0] - n[0], hub[1] - n[1]), tip],
                    closed=True,
                    fc="#f2f2f4",
                    ec=INK,
                    lw=0.6,
                    zorder=5.9,
                )
            )
        for k in range(3):
            box(
                ax,
                5.5,
                4.0 + k * 1.0,
                0,
                3.0,
                0.85,
                0.8,
                shades=CONCRETE,
                ox=ox,
                oy=oy,
                s=s,
            )  # basins
            top = [
                iso(5.6, 4.05 + k, 0.7, ox, oy, s),
                iso(8.4, 4.05 + k, 0.7, ox, oy, s),
                iso(8.4, 4.8 + k, 0.7, ox, oy, s),
                iso(5.6, 4.8 + k, 0.7, ox, oy, s),
            ]
            ax.add_patch(
                Polygon(top, closed=True, fc=WATER[0], ec=WATER[2], lw=0.4, zorder=3.3)
            )

    fit_scene(ax, scene, box=(8.4, 0.45, 15.5, 4.95), pad=0.25)
    ax.text(0.7, 4.1, "otwin", fontsize=46, weight="bold", color=INK, va="center")
    ax.text(
        0.78, 3.2, "Digital twins of real equipment", fontsize=17, color=INK, va="center"
    )
    ax.text(
        0.78,
        2.55,
        "Build the model from components, or bring it from Modelica or Julia.",
        fontsize=11.5,
        color=GREY,
        va="center",
    )
    ax.text(
        0.78,
        2.15,
        "Fit it to the machine, forecast with a range that has been measured,",
        fontsize=11.5,
        color=GREY,
        va="center",
    )
    ax.text(
        0.78,
        1.75,
        "and audit what the model promised against what the machine did.",
        fontsize=11.5,
        color=GREY,
        va="center",
    )
    ax.plot([0.78, 2.4], [1.25, 1.25], color=RED, lw=3)
    ax.text(
        0.78,
        0.85,
        'pip install "otwin[engine]"',
        fontsize=11,
        color=INK,
        family="monospace",
        va="center",
    )
    (OUT.parent.parent / "assets" / "readme").mkdir(parents=True, exist_ok=True)
    fig.savefig(
        OUT.parent.parent / "assets" / "readme" / "otwin-header.png",
        dpi=120,
        facecolor=PAPER,
    )
    plt.close(fig)
    print("wrote assets/readme/otwin-header.png")


# --------------------------------------------------------- process diagrams
# ISA-5.1 and IEC 60617 style symbols on a sheet. Coordinates in sheet units.


VIOLET = "#7a2ffc"
HATCHC = "#9a9aa1"
RAISED = "#f5f5f7"
LIGHT = "#ebebef"
DASHDOT = (0, (7, 2, 1.5, 2))
plt.rcParams["hatch.linewidth"] = 0.5

# ------------------------------------------------------ drafting toolkit


def cl(ax, x0, y0, x1, y1, transform=None):
    kw = dict(color=GREY, lw=0.65, ls=DASHDOT, zorder=2)
    if transform is not None:
        kw["transform"] = transform
    ax.plot([x0, x1], [y0, y1], **kw)


def srect(ax, x, y, w, h, fc=RAISED, lw=1.3, hatch="///", zorder=4):
    """A rectangle cut by the section plane: filled and hatched."""
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=INK, lw=lw, zorder=zorder))
    if hatch:
        ax.add_patch(
            Rectangle(
                (x, y), w, h, fc="none", ec=HATCHC, lw=0, hatch=hatch, zorder=zorder
            )
        )


def dim_h(ax, x0, x1, y, text, ey0, ey1, fs=8.5):
    for xx in (x0, x1):
        ax.plot([xx, xx], [ey0, ey1], color=GREY, lw=0.55, zorder=3)
    ax.annotate(
        "",
        (x0, y),
        (x1, y),
        arrowprops=dict(arrowstyle="<->", color=INK, lw=0.8, shrinkA=0, shrinkB=0),
    )
    ax.text(
        (x0 + x1) / 2, y + 0.09, text, fontsize=fs, color=INK, ha="center", va="bottom"
    )


def dim_v(ax, y0, y1, x, text, ex0, ex1, fs=8.5):
    for yy in (y0, y1):
        ax.plot([ex0, ex1], [yy, yy], color=GREY, lw=0.55, zorder=3)
    ax.annotate(
        "",
        (x, y0),
        (x, y1),
        arrowprops=dict(arrowstyle="<->", color=INK, lw=0.8, shrinkA=0, shrinkB=0),
    )
    ax.text(
        x + 0.09,
        (y0 + y1) / 2,
        text,
        fontsize=fs,
        color=INK,
        rotation=90,
        va="center",
        ha="left",
    )


def lead(ax, px, py, tx, ty, text, ha="left", fs=9.0, color=INK):
    ax.plot([px, tx], [py, ty], color=GREY, lw=0.6, zorder=8)
    ax.add_patch(Circle((px, py), 0.028, fc=GREY, ec="none", zorder=8))
    ax.text(
        tx + (0.08 if ha == "left" else -0.08),
        ty,
        text,
        fontsize=fs,
        color=color,
        ha=ha,
        va="center",
        zorder=9,
    )


def tag_bubble(ax, x, y, top, bot, px, py, note=None):
    """ISA instrument tag, the one violet element of a sheet."""
    ax.plot([x, px], [y, py], color=VIOLET, lw=0.7, ls=(0, (4, 2.5)), zorder=9)
    ax.add_patch(Circle((x, y), 0.21, fc="#ffffff", ec=VIOLET, lw=1.4, zorder=9))
    ax.plot([x - 0.21, x + 0.21], [y, y], color=VIOLET, lw=0.8, zorder=10)
    ax.text(
        x,
        y + 0.075,
        top,
        fontsize=7.0,
        color=VIOLET,
        ha="center",
        va="center",
        weight="bold",
        zorder=10,
    )
    ax.text(
        x, y - 0.075, bot, fontsize=6.5, color=VIOLET, ha="center", va="center", zorder=10
    )
    if note:
        ax.text(
            x, y - 0.36, note, fontsize=7.6, color=GREY, ha="center", va="top", zorder=9
        )


def ground(ax, x0, x1, y, step=0.17):
    ax.plot([x0, x1], [y, y], color=INK, lw=1.5, zorder=3)
    for gx in np.arange(x0 + 0.1, x1 - 0.02, step):
        ax.plot([gx, gx - 0.11], [y, y - 0.11], color=GREY, lw=0.6, zorder=3)


def brk(ax, x, y, angle=90, s=0.14):
    """A drafting break: double zigzag across a run at (x, y)."""
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)  # across the run
    for off in (-0.045, 0.045):
        ox, oy = -uy * off, ux * off
        zx = [
            x + ox - ux * s,
            x + ox - ux * s * 0.25 + uy * s * 0.6,
            x + ox + ux * s * 0.25 - uy * s * 0.6,
            x + ox + ux * s,
        ]
        zy = [
            y + oy - uy * s,
            y + oy - uy * s * 0.25 - ux * s * 0.6,
            y + oy + uy * s * 0.25 + ux * s * 0.6,
            y + oy + uy * s,
        ]
        ax.plot(zx, zy, color=INK, lw=0.9, zorder=6)


# ----------------------------------------------------------------- T01


def hero_bess():
    fig, ax = sheet(
        "Battery energy storage container",
        "2 MWh LFP, HVAC on the roof, MV transformer",
        "T01",
    )
    GY = 1.8
    # container, in section: 12 192 x 2 896
    CX0, CX1, CY0, CY1 = 2.0, 8.6, GY, GY + 1.57
    ax.add_patch(
        Rectangle(
            (CX0, CY0), CX1 - CX0, CY1 - CY0, fc="#ffffff", ec=INK, lw=1.5, zorder=4
        )
    )
    ax.add_patch(
        Rectangle(
            (CX0 + 0.06, CY0 + 0.06),
            CX1 - CX0 - 0.12,
            CY1 - CY0 - 0.12,
            fc="none",
            ec=INK,
            lw=0.7,
            zorder=4,
        )
    )
    # racks: six cabinets, four module shelves each
    for i in range(6):
        rx = CX0 + 0.42 + i * 1.0
        ax.add_patch(
            Rectangle((rx, CY0 + 0.12), 0.64, 1.18, fc=LIGHT, ec=INK, lw=1.0, zorder=5)
        )
        for j in range(4):
            yy = CY0 + 0.12 + 0.236 * (j + 1)
            ax.plot([rx, rx + 0.64], [yy, yy], color=INK, lw=0.6, zorder=6)
    # HVAC on the roof: two units with louvres and a drop into the roof
    for ux in (2.9, 6.1):
        ax.add_patch(
            Rectangle((ux, CY1), 1.05, 0.46, fc="#ffffff", ec=INK, lw=1.2, zorder=5)
        )
        for k in range(4):
            lx = ux + 0.18 + k * 0.19
            ax.plot([lx, lx], [CY1 + 0.08, CY1 + 0.38], color=INK, lw=0.6, zorder=6)
        ax.plot([ux + 0.86, ux + 0.86], [CY1, CY1 + 0.46], color=INK, lw=0.7, zorder=6)
    # MV transformer on a pad: tank, radiator fins, two bushings
    ax.add_patch(Rectangle((9.55, GY), 2.0, 0.14, fc=RAISED, ec=INK, lw=1.1, zorder=4))
    ax.add_patch(
        Rectangle(
            (9.55, GY), 2.0, 0.14, fc="none", ec=HATCHC, lw=0, hatch="///", zorder=4
        )
    )
    ax.add_patch(
        Rectangle((9.95, GY + 0.14), 1.3, 1.05, fc="#ffffff", ec=INK, lw=1.4, zorder=5)
    )
    for k in range(6):
        fx = 9.68 + k * 0.047
        ax.plot([fx, fx], [GY + 0.28, GY + 1.02], color=INK, lw=0.55, zorder=5)
    ax.plot([9.66, 9.95], [GY + 0.24, GY + 0.24], color=INK, lw=0.8, zorder=5)
    ax.plot([9.66, 9.95], [GY + 1.06, GY + 1.06], color=INK, lw=0.8, zorder=5)
    for bxx in (10.35, 10.85):
        ax.plot([bxx, bxx], [GY + 1.19, GY + 1.52], color=INK, lw=1.1, zorder=5)
        for d in (0.08, 0.17, 0.26):
            ax.plot(
                [bxx - 0.07, bxx + 0.07],
                [GY + 1.19 + d, GY + 1.19 + d],
                color=INK,
                lw=0.7,
                zorder=5,
            )
    # LV cable run container -> transformer
    ax.plot([CX1, 9.95], [GY + 0.55, GY + 0.55], color=INK, lw=0.8, zorder=3)
    brk(ax, 9.25, GY + 0.55, angle=90, s=0.10)
    ground(ax, 1.5, 12.2, GY)
    # dimensions
    dim_h(ax, CX0, CX1, CY1 + 0.95, "12 192", CY1 + 0.52, CY1 + 1.02)
    dim_v(ax, CY0, CY1, CX0 - 0.42, "2 896", CX0 - 0.50, CX0 - 0.06)
    # callouts
    lead(ax, CX0 + 1.75, CY0 + 1.0, 2.6, 5.55, "battery racks: 240 LFP cells, 2 MWh")
    lead(ax, 6.6, CY1 + 0.40, 7.9, 5.55, "HVAC: the heat has to leave")
    lead(ax, 11.25, GY + 0.9, 12.15, 4.5, "MV transformer, to the park bus")
    tag_bubble(
        ax,
        9.45,
        4.55,
        "TT",
        "01",
        8.0,
        CY0 + 1.32,
        note="pack temperature and state of\ncharge: the measurements",
    )
    save(fig, "t01_hero.png")


# ----------------------------------------------------------------- T02


def hero_feeder():
    fig, ax = sheet(
        "DC distribution feeder",
        "750 V feeder, 2 km of cable, DC link and converter",
        "T02",
    )
    GY = 2.3

    def cabinet(x, label_plinth=True):
        ax.add_patch(
            Rectangle((x, GY), 1.15, 1.85, fc="#ffffff", ec=INK, lw=1.4, zorder=5)
        )
        ax.plot(
            [x + 0.575, x + 0.575], [GY + 0.1, GY + 1.75], color=INK, lw=0.6, zorder=6
        )
        for yy in (GY + 1.45, GY + 1.58):
            ax.plot([x + 0.12, x + 0.46], [yy, yy], color=INK, lw=0.5, zorder=6)
        ax.add_patch(Circle((x + 0.50, GY + 0.95), 0.03, fc=INK, ec="none", zorder=6))
        ax.add_patch(Circle((x + 0.65, GY + 0.95), 0.03, fc=INK, ec="none", zorder=6))
        if label_plinth:
            srect(ax, x - 0.08, GY - 0.16, 1.31, 0.16)

    cabinet(2.0)
    cabinet(7.9)
    # buried cable: down, along, up
    for dx in (-0.04, 0.04):
        ax.plot(
            [2.575 + dx, 2.575 + dx], [GY, 1.72 + 0.04 - dx], color=INK, lw=1.0, zorder=3
        )
    ax.plot([2.575, 8.475], [1.72, 1.72], color=INK, lw=1.0, zorder=3)
    ax.plot([2.575, 8.475], [1.64, 1.64], color=INK, lw=1.0, zorder=3)
    for dx in (-0.04, 0.04):
        ax.plot(
            [8.475 + dx, 8.475 + dx], [1.72 + 0.04 + dx, GY], color=INK, lw=1.0, zorder=3
        )
    brk(ax, 5.5, 1.68, angle=90, s=0.12)
    ground(ax, 1.5, 9.65, GY)
    # detail mark on the cable, and the enlarged section
    ax.add_patch(Circle((6.6, 1.68), 0.16, fc="none", ec=INK, lw=0.8, zorder=6))
    DC = (12.15, 4.95)
    for r, lw_, ls_ in (
        (0.98, 1.4, "-"),
        (0.80, 0.8, "-"),
        (0.62, 0.8, (0, (3, 2))),
        (0.40, 1.0, "-"),
    ):
        ax.add_patch(Circle(DC, r, fc="none", ec=INK, lw=lw_, ls=ls_, zorder=6))
    ax.add_patch(Circle(DC, 0.40, fc=LIGHT, ec=INK, lw=1.0, zorder=5))
    ax.add_patch(Circle(DC, 0.40, fc="none", ec=HATCHC, lw=0, hatch="///", zorder=5))
    ax.text(
        DC[0],
        DC[1] - 1.35,
        "DETAIL A — the cable, from the run",
        fontsize=8.5,
        color=INK,
        ha="center",
        va="top",
        weight="bold",
    )
    lead(
        ax, DC[0] - 0.12, DC[1] + 0.12, 10.0, 6.25, "conductor: series R and L", ha="left"
    )
    lead(ax, DC[0] - 0.60, DC[1] - 0.45, 10.0, 3.95, "insulation", ha="left")
    lead(ax, DC[0] + 0.52, DC[1] + 0.52, 13.3, 6.1, "screen", ha="left")
    lead(ax, DC[0] + 0.93, DC[1] - 0.30, 13.55, 4.0, "sheath", ha="left")
    ax.text(6.6, 1.38, "A", fontsize=8.5, color=INK, ha="center", va="top", weight="bold")
    # run length
    dim_h(ax, 2.575, 8.475, 5.15, "2 000 m", GY + 1.9, 5.25)
    # labels
    lead(ax, 2.575, GY + 1.87, 1.75, 5.9, "substation converter: 750 V DC")
    lead(
        ax,
        8.475,
        GY + 1.87,
        6.9,
        5.9,
        "DC/DC converter and DC link: 48 V bus",
        ha="right",
    )
    ax.annotate(
        "",
        (9.6, GY + 0.9),
        (9.05, GY + 0.9),
        arrowprops=dict(arrowstyle="->", color=INK, lw=1.0),
    )
    ax.text(9.33, GY + 1.14, "loads\n20 → 60 kW", fontsize=8.5, color=INK, ha="center")
    tag_bubble(
        ax, 8.475, 5.85, "EI", "02", 8.475, GY + 1.85, note="bus voltage: the measurement"
    )
    save(fig, "t02_hero.png")


# ----------------------------------------------------------------- T04


def hero_turbine():
    fig, ax = sheet(
        "Wind turbine drivetrain",
        "Hub, main shaft, gearbox, generator on the bedplate",
        "T04",
    )
    AX = 3.95  # shaft axis height
    # tower top, in section, with a break at the bottom
    tower = [(3.19, 1.48), (4.21, 1.48), (4.12, 2.95), (3.28, 2.95)]
    ax.add_patch(Polygon(tower, closed=True, fc=RAISED, ec=INK, lw=1.3, zorder=4))
    ax.add_patch(
        Polygon(tower, closed=True, fc="none", ec=HATCHC, lw=0, hatch="///", zorder=4)
    )
    brk(ax, 3.7, 1.48, angle=0, s=0.18)
    # bedplate on the yaw bearing
    ax.plot([3.1, 4.3], [2.95, 2.95], color=INK, lw=1.0, zorder=5)
    ax.add_patch(Rectangle((2.35, 3.0), 6.55, 0.26, fc=LIGHT, ec=INK, lw=1.3, zorder=4))
    # nacelle cover, as a phantom outline
    ax.add_patch(
        FancyBboxPatch(
            (2.5, 3.05),
            6.6,
            2.0,
            boxstyle="round,pad=0.28",
            fc="none",
            ec="#c2c2c7",
            lw=0.8,
            ls=(0, (9, 4)),
            zorder=2,
        )
    )
    # hub and spinner, one blade up with a break
    from matplotlib.patches import Ellipse

    ax.add_patch(Ellipse((1.72, AX), 0.56, 1.0, fc="#ffffff", ec=INK, lw=1.3, zorder=5))
    ax.add_patch(
        Rectangle((1.72, AX - 0.5), 0.58, 1.0, fc="#ffffff", ec=INK, lw=1.4, zorder=5)
    )
    ax.add_patch(
        Polygon(
            [(1.86, AX + 0.5), (2.16, AX + 0.5), (2.10, 5.3), (1.94, 5.3)],
            closed=True,
            fc="#ffffff",
            ec=INK,
            lw=1.2,
            zorder=4,
        )
    )
    brk(ax, 2.01, 5.05, angle=0, s=0.14)
    # main shaft and main bearing
    ax.plot([2.3, 4.75], [AX + 0.09, AX + 0.09], color=INK, lw=1.2, zorder=5)
    ax.plot([2.3, 4.75], [AX - 0.09, AX - 0.09], color=INK, lw=1.2, zorder=5)
    ax.add_patch(Rectangle((3.0, 3.26), 0.62, 0.44, fc=LIGHT, ec=INK, lw=1.2, zorder=5))
    ax.add_patch(Circle((3.31, AX), 0.22, fc="#ffffff", ec=INK, lw=1.1, zorder=6))
    ax.add_patch(Circle((3.31, AX), 0.13, fc="#ffffff", ec=INK, lw=0.8, zorder=6))
    # gearbox with the gear train as pitch circles
    ax.add_patch(
        Rectangle((4.75, 3.26), 1.5, 1.6, fc="#ffffff", ec=INK, lw=1.4, zorder=5)
    )
    ax.add_patch(Circle((5.15, AX), 0.48, fc="none", ec=INK, lw=0.9, zorder=6))
    ax.add_patch(
        Circle((5.15, AX), 0.40, fc="none", ec=GREY, lw=0.6, ls=(0, (3, 2)), zorder=6)
    )
    ax.add_patch(Circle((5.78, AX + 0.33), 0.26, fc="none", ec=INK, lw=0.9, zorder=6))
    ax.add_patch(
        Circle(
            (5.78, AX + 0.33), 0.20, fc="none", ec=GREY, lw=0.6, ls=(0, (3, 2)), zorder=6
        )
    )
    ax.add_patch(Circle((5.95, AX - 0.12), 0.15, fc="none", ec=INK, lw=0.9, zorder=6))
    # high-speed shaft and brake disc
    ax.plot([6.25, 7.1], [AX - 0.065, AX - 0.065], color=INK, lw=1.0, zorder=5)
    ax.plot([6.25, 7.1], [AX - 0.185, AX - 0.185], color=INK, lw=1.0, zorder=5)
    ax.add_patch(
        Rectangle((6.55, AX - 0.47), 0.09, 0.70, fc="#ffffff", ec=INK, lw=1.1, zorder=6)
    )
    # generator with cooling fins and feet
    ax.add_patch(
        Rectangle((7.1, 3.35), 1.55, 1.15, fc="#ffffff", ec=INK, lw=1.4, zorder=5)
    )
    for k in range(7):
        fx = 7.28 + k * 0.17
        ax.plot([fx, fx], [4.5, 4.62], color=INK, lw=0.7, zorder=5)
    ax.plot([7.22, 8.55], [4.62, 4.62], color=INK, lw=0.8, zorder=5)
    ax.add_patch(Rectangle((7.3, 3.26), 0.28, 0.09, fc=INK, ec="none", zorder=5))
    ax.add_patch(Rectangle((8.3, 3.26), 0.28, 0.09, fc=INK, ec="none", zorder=5))
    # shaft centerline
    cl(ax, 1.1, AX, 9.0, AX)
    # callouts with the model's parameters
    lead(ax, 1.72, AX - 0.52, 1.15, 2.6, "rotor and hub\nJ = 6.0×10$^6$ kg·m²")
    lead(ax, 4.2, AX + 0.10, 3.6, 5.55, "main shaft\nk = 2.4×10$^8$ N·m/rad")
    lead(ax, 5.5, 4.86, 5.3, 5.85, "gearbox 1 : 90")
    lead(ax, 8.2, 4.5, 8.9, 5.55, "generator: J = 120 kg·m²\n1 500 rpm on this side")
    tag_bubble(
        ax, 10.3, 4.35, "ST", "04", 8.65, AX, note="generator speed:\nthe measurement"
    )
    save(fig, "t04_hero.png")


# ----------------------------------------------------------------- T05


def hero_water():
    fig, ax = sheet(
        "Municipal water supply",
        "Reservoir, pump station, rising main, elevated tank",
        "T05",
    )
    GY = 1.8
    ground(ax, 1.4, 9.6, GY)
    ground(ax, 11.9, 12.6, GY)
    ax.plot([9.6, 11.9], [GY, GY], color=INK, lw=1.5, zorder=3)

    def wlevel(x, y, s=0.12):
        ax.add_patch(
            Polygon(
                [(x - s, y + s), (x + s, y + s), (x, y)],
                closed=True,
                fc="none",
                ec=INK,
                lw=0.8,
                zorder=7,
            )
        )
        ax.plot([x - s * 1.6, x + s * 1.6], [y + s, y + s], color=INK, lw=0.8, zorder=7)

    # raw-water reservoir, excavated below grade
    basin = [(1.6, GY), (1.95, 1.22), (3.45, 1.22), (3.8, GY)]
    ax.plot(*zip(*basin, strict=True), color=INK, lw=1.3, zorder=4)
    ax.add_patch(
        Polygon(
            [(1.73, 1.62), (3.67, 1.62), (3.45, 1.22), (1.95, 1.22)],
            closed=True,
            fc="#efe6ff",
            ec="none",
            zorder=3,
        )
    )
    wlevel(2.7, 1.62)
    ax.annotate(
        "", (1.72, 1.5), (1.15, 1.5), arrowprops=dict(arrowstyle="->", color=INK, lw=0.9)
    )
    # pump station with pump and filter
    ax.add_patch(Rectangle((4.3, GY), 1.25, 0.95, fc="#ffffff", ec=INK, lw=1.3, zorder=5))
    ax.plot(
        [4.2, 4.925, 5.65], [GY + 0.95, GY + 1.3, GY + 0.95], color=INK, lw=1.1, zorder=5
    )
    ax.add_patch(Circle((4.7, GY + 0.33), 0.19, fc="#ffffff", ec=INK, lw=1.1, zorder=6))
    ax.add_patch(
        Polygon(
            [(4.7, GY + 0.52), (4.56, GY + 0.33), (4.84, GY + 0.33)],
            closed=True,
            fc=INK,
            ec="none",
            zorder=7,
        )
    )
    ax.add_patch(
        Rectangle((5.08, GY + 0.14), 0.26, 0.5, fc=LIGHT, ec=INK, lw=1.0, zorder=6)
    )
    for yy in (0.27, 0.39, 0.51):
        ax.plot([5.08, 5.34], [GY + yy, GY + yy], color=HATCHC, lw=0.5, zorder=6)
    # suction from the reservoir
    ax.plot([3.45, 4.51], [1.35, GY + 0.33], color=INK, lw=0.9, zorder=4)
    # rising main: out of the station, then up to the tank
    x0, y0 = 5.55, GY + 0.45
    ax.plot([x0, 6.3], [y0, y0], color=INK, lw=1.0, zorder=4)
    ax.plot([x0, 6.3], [y0 - 0.08, y0 - 0.08], color=INK, lw=1.0, zorder=4)
    ax.plot([6.3, 10.55], [y0, 4.72], color=INK, lw=1.0, zorder=4)
    ax.plot([6.3 + 0.03, 10.58], [y0 - 0.08, 4.64], color=INK, lw=1.0, zorder=4)
    brk(ax, 8.2, 3.62, angle=127, s=0.12)
    # elevated tank on braced legs
    TX0, TX1, TY0, TY1 = 9.85, 11.75, 4.6, 5.95
    ax.add_patch(
        Rectangle(
            (TX0, TY0), TX1 - TX0, TY1 - TY0, fc="#ffffff", ec=INK, lw=1.5, zorder=5
        )
    )
    ax.plot([TX0 - 0.1, TX1 + 0.1], [TY0, TY0], color=INK, lw=1.5, zorder=5)
    ax.plot(
        [TX0 + 0.25, TX1 - 0.25],
        [5.52, 5.52],
        color=INK,
        lw=0.8,
        ls=(0, (5, 3)),
        zorder=6,
    )
    wlevel(10.45, 5.52)
    for lx in (10.12, 11.48):
        ax.plot([lx, lx], [GY, TY0], color=INK, lw=1.3, zorder=4)
    ax.plot([10.12, 11.48], [GY + 0.3, TY0 - 0.25], color=INK, lw=0.7, zorder=3)
    ax.plot([11.48, 10.12], [GY + 0.3, TY0 - 0.25], color=INK, lw=0.7, zorder=3)
    # service line down and off to the town
    ax.plot([11.3, 11.3], [TY0, 2.25], color=INK, lw=0.9, zorder=4)
    ax.annotate(
        "",
        (12.45, 2.25),
        (11.3, 2.25),
        arrowprops=dict(arrowstyle="->", color=INK, lw=0.9),
    )
    ax.text(12.42, 2.44, "to the town", fontsize=8.5, color=INK, ha="right")
    # the head, dimensioned
    dim_v(ax, GY + 0.45, 5.52, 13.3, "30 m of head", 11.95, 13.4)
    ax.text(11.88, GY + 0.40, "pump axis", fontsize=7.0, color=GREY, ha="right", va="top")
    # callouts
    lead(ax, 2.7, 1.3, 1.7, 3.3, "raw-water reservoir, river-fed")
    lead(ax, 4.925, GY + 1.28, 4.1, 4.5, "pump station: pump and filter")
    lead(ax, 8.35, 3.45, 6.7, 5.2, "rising main: 1 200 m, friction and inertia")
    lead(ax, 10.8, TY1, 9.3, 6.35, "the tank smooths pump against demand")
    tag_bubble(
        ax, 12.45, 6.15, "LT", "05", TX1, 5.52, note="tank level:\nthe measurement"
    )
    save(fig, "t05_hero.png")


# ----------------------------------------------------------------- T06


def hero_wastewater():
    fig, ax = sheet(
        "Wastewater disinfection",
        "Chlorine contact basin in plan: four cells in series",
        "T06",
    )
    X0, X1, Y0, Y1, W = 2.3, 8.9, 2.0, 5.7, 0.2
    # outer wall, in section
    outer = Rectangle(
        (X0 - W, Y0 - W),
        X1 - X0 + 2 * W,
        Y1 - Y0 + 2 * W,
        fc=RAISED,
        ec=INK,
        lw=1.5,
        zorder=3,
    )
    ax.add_patch(outer)
    ax.add_patch(
        Rectangle(
            (X0 - W, Y0 - W),
            X1 - X0 + 2 * W,
            Y1 - Y0 + 2 * W,
            fc="none",
            ec=HATCHC,
            lw=0,
            hatch="///",
            zorder=3,
        )
    )
    ax.add_patch(
        Rectangle((X0, Y0), X1 - X0, Y1 - Y0, fc="#ffffff", ec=INK, lw=1.2, zorder=4)
    )
    # three baffles -> four cells
    GAP = 0.75
    for i, bx in enumerate((3.95, 5.6, 7.25)):
        if i % 2 == 0:
            y0b, y1b = Y0, Y1 - GAP
        else:
            y0b, y1b = Y0 + GAP, Y1
        ax.add_patch(
            Rectangle(
                (bx - 0.08, y0b), 0.16, y1b - y0b, fc=RAISED, ec=INK, lw=1.1, zorder=5
            )
        )
        ax.add_patch(
            Rectangle(
                (bx - 0.08, y0b),
                0.16,
                y1b - y0b,
                fc="none",
                ec=HATCHC,
                lw=0,
                hatch="///",
                zorder=5,
            )
        )
    # the flow, as a dashed path with arrows
    path = [
        (1.45, 4.6),
        (X0 + 0.45, 4.6),
        (3.12, 5.2),
        (3.12, 2.6),
        (4.78, 2.6),
        (4.78, 5.1),
        (6.42, 5.1),
        (6.42, 2.6),
        (8.08, 2.6),
        (8.08, 4.6),
        (X1 - 0.1, 4.6),
        (9.75, 4.6),
    ]
    for p0, p1 in zip(path[:-1], path[1:], strict=True):
        ax.annotate(
            "",
            p1,
            p0,
            zorder=6,
            arrowprops=dict(
                arrowstyle="->",
                color=GREY,
                lw=1.0,
                linestyle=(0, (5, 3)),
                shrinkA=0,
                shrinkB=0,
            ),
        )
    # inlet with the dose, outlet to discharge
    ax.plot([1.45, X0 - W], [4.42, 4.42], color=INK, lw=1.0, zorder=4)
    ax.plot([1.45, X0 - W], [4.78, 4.78], color=INK, lw=1.0, zorder=4)
    ax.plot([X1 + W, 9.75], [4.42, 4.42], color=INK, lw=1.0, zorder=4)
    ax.plot([X1 + W, 9.75], [4.78, 4.78], color=INK, lw=1.0, zorder=4)
    ax.add_patch(
        Polygon(
            [(1.86, 5.35), (1.76, 5.12), (1.96, 5.12)],
            closed=True,
            fc="#ffffff",
            ec=INK,
            lw=0.9,
            zorder=6,
        )
    )
    ax.plot([1.86, 1.86], [5.35, 4.8], color=INK, lw=0.9, zorder=5)
    # cell numbers
    for i, cx in enumerate((3.12, 4.78, 6.42, 8.08)):
        ax.text(
            cx,
            3.82,
            str(i + 1),
            fontsize=11,
            color=GREY,
            ha="center",
            va="center",
            style="italic",
            zorder=6,
        )
    # callouts
    lead(ax, 1.86, 5.33, 2.6, 6.25, "chlorine dosed at the inlet")
    lead(
        ax,
        5.6,
        Y1 + W,
        5.0,
        6.35,
        "three baffles: four cells in series,\ncloser to plug flow",
    )
    lead(
        ax,
        9.3,
        4.42,
        10.6,
        3.4,
        "to discharge: the residual must leave\nabove 0.2 mg/L — the permit",
    )
    ax.text(1.42, 4.2, "inlet", fontsize=8.5, color=INK, ha="left", va="top")
    tag_bubble(
        ax,
        10.3,
        5.35,
        "AT",
        "06",
        9.6,
        4.78,
        note="residual chlorine at the outlet:\nthe measurement",
    )
    save(fig, "t06_hero.png")


# ----------------------------------------------------------------- T07


def hero_building():
    fig, ax = sheet(
        "Heated building",
        "Section: envelope, electric boiler, radiator loop",
        "T07",
    )
    GY = 1.8
    ground(ax, 1.4, 10.3, GY)
    X0, X1 = 2.5, 8.7
    WALL, INS = 0.14, 0.12
    H0, H1 = GY, 4.75
    # floor slab
    srect(ax, X0 - WALL - INS, H0, (X1 - X0) + 2 * (WALL + INS), 0.22)
    # walls: structure plus insulation, the window on the right
    for side in ("L", "R"):
        if side == "L":
            xs, xi = X0 - WALL - INS, X0 - INS
            srect(ax, xs, H0 + 0.22, WALL, H1 - H0 - 0.22)
            ax.add_patch(
                Rectangle(
                    (xi, H0 + 0.22),
                    INS,
                    H1 - H0 - 0.22,
                    fc="#ffffff",
                    ec=INK,
                    lw=0.8,
                    zorder=4,
                )
            )
            ax.add_patch(
                Rectangle(
                    (xi, H0 + 0.22),
                    INS,
                    H1 - H0 - 0.22,
                    fc="none",
                    ec=HATCHC,
                    lw=0,
                    hatch="...",
                    zorder=4,
                )
            )
        else:
            xs, xi = X1 + INS, X1
            for ya, yb in ((H0 + 0.22, 3.05), (3.95, H1)):
                srect(ax, xs, ya, WALL, yb - ya)
                ax.add_patch(
                    Rectangle(
                        (xi, ya), INS, yb - ya, fc="#ffffff", ec=INK, lw=0.8, zorder=4
                    )
                )
                ax.add_patch(
                    Rectangle(
                        (xi, ya),
                        INS,
                        yb - ya,
                        fc="none",
                        ec=HATCHC,
                        lw=0,
                        hatch="...",
                        zorder=4,
                    )
                )
    # the window: frame and double glazing
    for gx in (X1 + 0.03, X1 + 0.11):
        ax.plot([gx, gx], [3.05, 3.95], color=INK, lw=0.9, zorder=5)
    ax.plot([X1 - 0.06, X1 + WALL + INS + 0.0], [3.05, 3.05], color=INK, lw=1.1, zorder=5)
    ax.plot([X1 - 0.06, X1 + WALL + INS + 0.0], [3.95, 3.95], color=INK, lw=1.1, zorder=5)
    # roof slab
    srect(ax, X0 - WALL - INS - 0.15, H1, (X1 - X0) + 2 * (WALL + INS) + 0.3, 0.2)
    # boiler, the loop, the radiator
    ax.add_patch(
        Rectangle((2.95, H0 + 0.22), 0.7, 1.05, fc="#ffffff", ec=INK, lw=1.3, zorder=5)
    )
    ax.plot([3.05, 3.55], [H0 + 1.05, H0 + 1.05], color=INK, lw=0.6, zorder=6)
    ax.plot([3.3, 3.3], [H0 + 0.42, H0 + 0.88], color=INK, lw=0.6, zorder=6)
    ax.plot([3.65, 7.9], [H0 + 0.52, H0 + 0.52], color=INK, lw=0.8, zorder=4)
    ax.plot([3.65, 7.9], [H0 + 0.40, H0 + 0.40], color=INK, lw=0.8, zorder=4)
    ax.annotate(
        "",
        (6.1, H0 + 0.52),
        (5.9, H0 + 0.52),
        zorder=6,
        arrowprops=dict(arrowstyle="->", color=INK, lw=0.8),
    )
    rad_x = 7.9
    ax.add_patch(
        Rectangle((rad_x, H0 + 0.35), 0.5, 1.3, fc="#ffffff", ec=INK, lw=1.2, zorder=5)
    )
    for k in range(5):
        rx = rad_x + 0.09 + k * 0.085
        ax.plot([rx, rx], [H0 + 0.45, H0 + 1.55], color=INK, lw=0.55, zorder=6)
    for axx in (rad_x + 0.1, rad_x + 0.4):
        ax.annotate(
            "",
            (axx, H0 + 2.25),
            (axx, H0 + 1.75),
            zorder=6,
            arrowprops=dict(arrowstyle="->", color=GREY, lw=0.8),
        )
    # temperatures and ventilation
    ax.text(5.7, 3.6, "20 °C", fontsize=12, color=INK, ha="center", weight="bold")
    ax.text(1.55, 3.6, "0 °C", fontsize=10, color=INK, ha="center")
    ax.annotate(
        "", (2.25, 3.3), (1.45, 3.3), arrowprops=dict(arrowstyle="->", color=GREY, lw=1.0)
    )
    ax.annotate(
        "",
        (6.9, 5.75),
        (6.4, 4.98),
        zorder=6,
        arrowprops=dict(arrowstyle="->", color=GREY, lw=1.0),
    )
    ax.text(7.0, 5.8, "ventilation loss", fontsize=8.5, color=INK, ha="left")
    # callouts
    lead(ax, 3.3, H0 + 1.27, 2.95, 5.5, "electric boiler: 12 kW\nthrough a water loop")
    lead(
        ax,
        X0 - WALL - INS + 0.07,
        4.3,
        1.45,
        5.85,
        "envelope: walls and\ninsulation lose heat",
    )
    lead(ax, rad_x + 0.42, H0 + 0.55, 9.35, 2.35, "radiator under the window")
    tag_bubble(
        ax,
        9.9,
        4.6,
        "TT",
        "07",
        X1 - 0.12,
        4.15,
        note="indoor temperature:\nthe measurement",
    )
    save(fig, "t07_hero.png")


# ----------------------------------------------------------------- T08


def hero_pumpdrive():
    fig, ax = sheet(
        "Motor-driven pump set",
        "DC motor, coupling, gear pump and head tank on one baseplate",
        "T08",
    )
    GY = 1.8
    ground(ax, 1.5, 10.6, GY)
    AXY = 3.02
    # foundation and baseplate
    srect(ax, 2.2, GY, 6.4, 0.35)
    ax.add_patch(
        Rectangle((2.35, GY + 0.35), 6.1, 0.17, fc=LIGHT, ec=INK, lw=1.2, zorder=4)
    )
    for bx in (2.7, 4.4, 6.1, 8.1):
        ax.plot([bx, bx], [GY + 0.05, GY + 0.52], color=INK, lw=0.8, zorder=5)
        ax.plot(
            [bx - 0.07, bx + 0.07], [GY + 0.52, GY + 0.52], color=INK, lw=0.8, zorder=5
        )
    # DC motor: fan cowl, body, terminal box, feet
    ax.add_patch(
        Rectangle((2.52, 2.52), 0.26, 1.0, fc="#ffffff", ec=INK, lw=1.2, zorder=5)
    )
    for k in range(4):
        ax.plot(
            [2.58 + k * 0.05, 2.58 + k * 0.05], [2.6, 3.44], color=INK, lw=0.5, zorder=6
        )
    ax.add_patch(
        Rectangle((2.78, 2.42), 1.95, 1.2, fc="#ffffff", ec=INK, lw=1.4, zorder=5)
    )
    for k in range(5):
        yy = 2.56 + k * 0.19
        ax.plot([2.84, 4.67], [yy, yy], color="#c2c2c7", lw=0.5, zorder=5)
    ax.add_patch(
        Rectangle((3.45, 3.62), 0.55, 0.3, fc="#ffffff", ec=INK, lw=1.1, zorder=5)
    )
    for fx in (2.95, 4.35):
        ax.add_patch(
            Polygon(
                [
                    (fx - 0.14, GY + 0.52),
                    (fx + 0.14, GY + 0.52),
                    (fx + 0.07, 2.42),
                    (fx - 0.07, 2.42),
                ],
                closed=True,
                fc=LIGHT,
                ec=INK,
                lw=1.0,
                zorder=5,
            )
        )
    # shaft and coupling with its guard
    ax.plot([4.73, 5.5], [AXY + 0.06, AXY + 0.06], color=INK, lw=1.1, zorder=5)
    ax.plot([4.73, 5.5], [AXY - 0.06, AXY - 0.06], color=INK, lw=1.1, zorder=5)
    for cx in (4.98, 5.18):
        ax.add_patch(
            Rectangle(
                (cx, AXY - 0.24), 0.14, 0.48, fc="#ffffff", ec=INK, lw=1.1, zorder=6
            )
        )
    ax.add_patch(
        Rectangle(
            (4.88, AXY - 0.34),
            0.56,
            0.68,
            fc="none",
            ec=GREY,
            lw=0.8,
            ls=(0, (4, 2.5)),
            zorder=6,
        )
    )
    # gear pump: casing, two meshing gears, foot, flanges
    PC = (6.15, AXY)
    ax.add_patch(Circle(PC, 0.62, fc="#ffffff", ec=INK, lw=1.4, zorder=5))
    ax.add_patch(Circle(PC, 0.52, fc="none", ec=INK, lw=0.7, zorder=5))
    ax.add_patch(
        Circle(
            (PC[0], PC[1] + 0.22),
            0.215,
            fc="none",
            ec=GREY,
            lw=0.7,
            ls=(0, (3, 2)),
            zorder=6,
        )
    )
    ax.add_patch(
        Circle(
            (PC[0], PC[1] - 0.22),
            0.215,
            fc="none",
            ec=GREY,
            lw=0.7,
            ls=(0, (3, 2)),
            zorder=6,
        )
    )
    ax.add_patch(
        Polygon(
            [
                (PC[0] - 0.3, GY + 0.52),
                (PC[0] + 0.3, GY + 0.52),
                (PC[0] + 0.16, PC[1] - 0.57),
                (PC[0] - 0.16, PC[1] - 0.57),
            ],
            closed=True,
            fc=LIGHT,
            ec=INK,
            lw=1.1,
            zorder=4,
        )
    )
    # suction sump on the baseplate, to the right
    ax.plot([6.77, 7.35], [AXY, AXY], color=INK, lw=1.0, zorder=4)
    ax.plot([7.35, 7.35], [AXY, 2.72], color=INK, lw=1.0, zorder=4)
    ax.add_patch(
        Rectangle((7.05, GY + 0.52), 1.25, 0.72, fc="#ffffff", ec=INK, lw=1.2, zorder=3)
    )
    ax.plot([7.17, 8.18], [2.98, 2.98], color=INK, lw=0.7, ls=(0, (5, 3)), zorder=4)
    ax.add_patch(
        Polygon(
            [(7.56, 3.1), (7.44, 2.98), (7.68, 2.98)],
            closed=True,
            fc="none",
            ec=INK,
            lw=0.7,
            zorder=4,
        )
    )
    # discharge up to the head tank
    ax.plot(
        [PC[0] - 0.04, PC[0] - 0.04], [PC[1] + 0.62, 5.15], color=INK, lw=1.0, zorder=4
    )
    ax.plot(
        [PC[0] + 0.04, PC[0] + 0.04], [PC[1] + 0.62, 5.07], color=INK, lw=1.0, zorder=4
    )
    ax.plot([PC[0] - 0.04, 8.6], [5.15, 5.15], color=INK, lw=1.0, zorder=4)
    ax.plot([PC[0] + 0.04, 8.6], [5.07, 5.07], color=INK, lw=1.0, zorder=4)
    TK = (8.6, 4.15)
    ax.add_patch(
        Rectangle(
            (TK[0] - 0.75, TK[1]), 1.5, 1.35, fc="#ffffff", ec=INK, lw=1.3, zorder=5
        )
    )
    ax.plot(
        [TK[0] - 0.5, TK[0] + 0.5],
        [TK[1] + 0.95, TK[1] + 0.95],
        color=INK,
        lw=0.7,
        ls=(0, (5, 3)),
        zorder=6,
    )
    ax.add_patch(
        Polygon(
            [
                (TK[0] - 0.12, TK[1] + 1.07),
                (TK[0] - 0.24, TK[1] + 0.95),
                (TK[0], TK[1] + 0.95),
            ],
            closed=True,
            fc="none",
            ec=INK,
            lw=0.7,
            zorder=6,
        )
    )
    for lx in (TK[0] - 0.55, TK[0] + 0.55):
        ax.plot([lx, lx], [GY, TK[1]], color=INK, lw=1.1, zorder=3)
    cl(ax, 2.2, AXY, 7.0, AXY)
    # callouts
    lead(
        ax,
        3.75,
        3.92,
        2.6,
        5.5,
        "DC motor: armature R and L,\nrotor inertia and friction",
    )
    lead(ax, 5.16, AXY + 0.36, 4.6, 4.7, "coupling")
    lead(
        ax,
        PC[0] - 0.42,
        PC[1] - 0.48,
        4.95,
        1.28,
        "gear pump: 20 cm³ per revolution",
        ha="right",
    )
    lead(ax, TK[0] + 0.3, TK[1] + 1.33, 9.75, 6.0, "head tank", ha="left")
    lead(ax, 7.9, 2.6, 9.3, 2.55, "suction sump")
    tag_bubble(
        ax,
        5.35,
        5.72,
        "IT",
        "08",
        4.4,
        3.64,
        note="armature current at start-up:\nthe measurement",
    )
    save(fig, "t08_hero.png")


# ----------------------------------------------------------------- T09


def hero_flywheel():
    fig, ax = sheet(
        "Flywheel energy storage",
        "Vertical section: steel rotor in a vacuum housing",
        "T09",
    )
    CX = 6.0
    X0, X1, Y0, Y1, W = 4.5, 7.5, 1.9, 5.9, 0.18
    # vacuum vessel, wall in section
    srect(ax, X0, Y0, W, Y1 - Y0)
    srect(ax, X1 - W, Y0, W, Y1 - Y0)
    srect(ax, X0, Y1 - W, X1 - X0, W)
    srect(ax, X0, Y0, X1 - X0, W)
    ax.text(X0 + 0.32, Y1 - 0.42, "vacuum", fontsize=8.5, color=GREY, style="italic")
    # vacuum port with its valve
    ax.plot([X1, 8.05], [5.45, 5.45], color=INK, lw=0.9, zorder=4)
    ax.plot([X1, 8.05], [5.33, 5.33], color=INK, lw=0.9, zorder=4)
    ax.add_patch(
        Polygon(
            [(8.05, 5.51), (8.05, 5.27), (8.33, 5.39)],
            closed=True,
            fc="#ffffff",
            ec=INK,
            lw=0.9,
            zorder=5,
        )
    )
    ax.add_patch(
        Polygon(
            [(8.61, 5.51), (8.61, 5.27), (8.33, 5.39)],
            closed=True,
            fc="#ffffff",
            ec=INK,
            lw=0.9,
            zorder=5,
        )
    )
    # shaft
    ax.add_patch(
        Rectangle(
            (CX - 0.07, Y0 + W),
            0.14,
            Y1 - Y0 - 2 * W,
            fc="#ffffff",
            ec=INK,
            lw=1.1,
            zorder=5,
        )
    )
    # rotor disc, in section
    ax.add_patch(
        Rectangle((CX - 1.0, 3.3), 2.0, 0.85, fc=RAISED, ec=INK, lw=1.5, zorder=6)
    )
    ax.add_patch(
        Rectangle(
            (CX - 1.0, 3.3), 2.0, 0.85, fc="none", ec=HATCHC, lw=0, hatch="///", zorder=6
        )
    )
    # magnetic bearings, top and bottom: stator blocks with an air gap
    for by in (5.05, 2.42):
        for sx in (-1, 1):
            x = CX - 0.44 if sx < 0 else CX + 0.14
            ax.add_patch(
                Rectangle((x, by), 0.30, 0.34, fc=LIGHT, ec=INK, lw=1.1, zorder=6)
            )
    # motor-generator stator
    for sx in (CX - 0.52, CX + 0.14):
        ax.add_patch(
            Rectangle((sx, 4.38), 0.38, 0.40, fc=RAISED, ec=INK, lw=1.1, zorder=6)
        )
        ax.add_patch(
            Rectangle(
                (sx, 4.38), 0.38, 0.40, fc="none", ec=HATCHC, lw=0, hatch="///", zorder=6
            )
        )
    cl(ax, CX, Y0 - 0.35, CX, Y1 + 0.35)
    for xx in (CX - 1.0, CX + 1.0):
        ax.plot([xx, xx], [3.26, 2.85], color=GREY, lw=0.55, zorder=3)
    ax.annotate(
        "",
        (CX - 1.0, 2.95),
        (CX + 1.0, 2.95),
        arrowprops=dict(arrowstyle="<->", color=INK, lw=0.8, shrinkA=0, shrinkB=0),
    )
    ax.text(
        CX,
        3.06,
        "Ø 560",
        fontsize=8.5,
        color=INK,
        ha="center",
        va="bottom",
        bbox=dict(fc="#ffffff", ec="none", pad=1.2),
        zorder=7,
    )
    # callouts
    lead(ax, CX + 0.85, 3.9, 8.6, 3.6, "steel disc: 230 kg\nJ = 9 kg·m²")
    lead(
        ax, CX + 0.33, 5.22, 8.5, 6.15, "magnetic bearings: drag\nc = 1.0×10$^{-4}$ N·m·s"
    )
    lead(ax, CX - 0.5, 4.58, 2.6, 5.6, "motor-generator\n0.22 N·m per ampere", ha="left")
    lead(ax, CX + 0.45, 2.59, 8.6, 2.45, "18 000 to 36 000 rpm:\nthe working window")
    tag_bubble(ax, 9.9, 4.9, "ST", "09", CX + 0.53, 4.58, note="speed: the measurement")
    save(fig, "t09_hero.png")


# ----------------------------------------------------------------- T10


def hero_twin():
    fig, ax = sheet(
        "From a model to a digital twin",
        "Elevated tank with level sensor: fitted, forecast and audited",
        "T10",
    )
    GY = 1.8
    ground(ax, 1.5, 7.9, GY)

    def wlevel(x, y, s=0.12):
        ax.add_patch(
            Polygon(
                [(x - s, y + s), (x + s, y + s), (x, y)],
                closed=True,
                fc="none",
                ec=INK,
                lw=0.8,
                zorder=7,
            )
        )
        ax.plot([x - s * 1.6, x + s * 1.6], [y + s, y + s], color=INK, lw=0.8, zorder=7)

    # the tank, TK-102
    TX0, TX1, TY0, TY1 = 2.9, 6.1, 3.95, 5.85
    ax.add_patch(
        Rectangle(
            (TX0, TY0), TX1 - TX0, TY1 - TY0, fc="#ffffff", ec=INK, lw=1.5, zorder=5
        )
    )
    ax.plot([TX0 - 0.12, TX1 + 0.12], [TY0, TY0], color=INK, lw=1.5, zorder=5)
    ax.plot(
        [TX0 + 0.3, TX1 - 0.3], [5.35, 5.35], color=INK, lw=0.8, ls=(0, (5, 3)), zorder=6
    )
    wlevel(3.7, 5.35)
    ax.text(
        (TX0 + TX1) / 2,
        TY1 + 0.16,
        "TK-102 · A = 150 m²",
        fontsize=8.5,
        color=INK,
        ha="center",
        weight="bold",
    )
    for lx in (3.25, 5.75):
        ax.plot([lx, lx], [GY, TY0], color=INK, lw=1.3, zorder=4)
    ax.plot([3.25, 5.75], [GY + 0.3, TY0 - 0.25], color=INK, lw=0.7, zorder=3)
    ax.plot([5.75, 3.25], [GY + 0.3, TY0 - 0.25], color=INK, lw=0.7, zorder=3)
    # inflow from the pump station
    ax.plot([1.35, TX0], [4.9, 4.9], color=INK, lw=1.0, zorder=4)
    ax.plot([1.35, TX0], [4.82, 4.82], color=INK, lw=1.0, zorder=4)
    brk(ax, 2.0, 4.86, angle=90, s=0.11)
    ax.text(1.35, 5.1, "from the pump station", fontsize=8.5, color=INK, ha="left")
    # service line with CV-102, to the town
    ax.plot([5.55, 5.55], [TY0, 2.35], color=INK, lw=0.9, zorder=4)
    ax.plot([5.55, 6.55], [2.35, 2.35], color=INK, lw=0.9, zorder=4)
    ax.add_patch(
        Polygon(
            [(6.55, 2.49), (6.55, 2.21), (6.9, 2.35)],
            closed=True,
            fc="#ffffff",
            ec=INK,
            lw=0.9,
            zorder=5,
        )
    )
    ax.add_patch(
        Polygon(
            [(7.25, 2.49), (7.25, 2.21), (6.9, 2.35)],
            closed=True,
            fc="#ffffff",
            ec=INK,
            lw=0.9,
            zorder=5,
        )
    )
    ax.annotate(
        "",
        (7.95, 2.35),
        (7.25, 2.35),
        arrowprops=dict(arrowstyle="->", color=INK, lw=0.9),
    )
    ax.text(7.9, 2.56, "to the town", fontsize=8.5, color=INK, ha="right")
    lead(
        ax,
        6.9,
        2.22,
        4.75,
        1.25,
        "CV-102, the service valve: its coefficient is on\nno data sheet, and it drifts as the valve wears",
        ha="right",
    )
    # the level transmitter
    tag_bubble(
        ax,
        7.0,
        5.6,
        "LT",
        "102",
        TX1,
        5.35,
        note="the level, every 10 minutes:\nall the twin sees",
    )
    # the twin, as a panel: measured, forecast, band, audit
    PX0, PY0, PW, PH = 8.6, 2.9, 5.6, 3.4
    ax.add_patch(
        FancyBboxPatch(
            (PX0, PY0),
            PW,
            PH,
            boxstyle="round,pad=0.12",
            fc="#ffffff",
            ec="#d2d2d7",
            lw=1.2,
            zorder=5,
        )
    )
    ax.text(
        PX0 + 0.15,
        PY0 + PH - 0.25,
        "level · measured, forecast, 90 % range",
        fontsize=8.5,
        color=INK,
        zorder=6,
    )
    t = np.linspace(0, 1, 160)
    xm = PX0 + 0.35 + t * (PW - 2.3)
    ym = PY0 + 1.6 + 0.75 * np.sin(t * 2 * np.pi * 0.9 - 0.6)
    ax.plot(xm, ym, color=INK, lw=1.6, zorder=6)
    tf = np.linspace(0, 1, 80)
    xf = xm[-1] + tf * 1.55
    ph0 = 0.9 * 2 * np.pi - 0.6
    yf = ym[-1] + 0.72 * (np.sin(0.9 * 2 * np.pi * (1 + tf * 0.42) - 0.6) - np.sin(ph0))
    band = 0.10 + 0.34 * tf
    ax.fill_between(xf, yf - band, yf + band, color="#efe6ff", zorder=5)
    ax.plot(xf, yf, color=VIOLET, lw=1.6, ls=(0, (4, 2.5)), zorder=6)
    ax.plot(
        [PX0 + 0.3, PX0 + PW - 0.3],
        [PY0 + 0.62, PY0 + 0.62],
        color="#d2d2d7",
        lw=0.8,
        zorder=6,
    )
    ax.text(
        PX0 + 0.15,
        PY0 + 0.32,
        "coverage audit: 91 % delivered at the 90 % level",
        fontsize=7.8,
        color=GREY,
        zorder=6,
    )
    ax.plot(
        [TX1 + 0.12, PX0 - 0.12],
        [4.6, 4.6],
        color=GREY,
        lw=0.7,
        ls=(0, (4, 2.5)),
        zorder=3,
    )
    save(fig, "t10_hero.png")


# ----------------------------------------------------------------- T03


def hero_suspension():
    fig, ax = sheet(
        "Vehicle suspension",
        "Quarter-car corner, front elevation: McPherson strut",
        "T03",
    )

    DASHDOT = (0, (7, 2, 1.5, 2))

    def cl03(x0, y0, x1, y1, transform=None):
        kw = dict(color=GREY, lw=0.65, ls=DASHDOT, zorder=2)
        if transform is not None:
            kw["transform"] = transform
        ax.plot([x0, x1], [y0, y1], **kw)

    # ------------------------------------------------------------- layout
    AXLE_Y = 3.03
    GY = 1.75
    TIRE_CX = 7.73
    TW, TH, TR = 0.86, 2.56, 0.30
    tx0, ty0 = TIRE_CX - TW / 2, AXLE_Y - TH / 2  # tire left edge, bottom (= ground)

    cl03(4.3, AXLE_Y, 8.78, AXLE_Y)  # axle centerline
    cl03(TIRE_CX, GY - 0.28, TIRE_CX, ty0 + TH + 0.30)  # wheel plane centerline

    # ------------------------------------------------------------------ tire
    ax.add_patch(
        FancyBboxPatch(
            (tx0 + TR, ty0 + TR),
            TW - 2 * TR,
            TH - 2 * TR,
            boxstyle=f"round,pad={TR}",
            fc="#ffffff",
            ec=INK,
            lw=1.5,
            zorder=4,
        )
    )
    # shoulder lines and circumferential tread grooves
    for dx in (0.13, 0.31, TW - 0.31, TW - 0.13):
        lw = 0.8 if dx in (0.13, TW - 0.13) else 0.55
        ax.plot(
            [tx0 + dx, tx0 + dx],
            [ty0 + 0.17, ty0 + TH - 0.17],
            color=INK,
            lw=lw,
            zorder=4,
        )

    # hub flange and axle stub on the inboard face
    ax.add_patch(
        Rectangle(
            (tx0 - 0.16, AXLE_Y - 0.20),
            0.16,
            0.40,
            fc="#f5f5f7",
            ec=INK,
            lw=1.1,
            zorder=5,
        )
    )

    # --------------------------------------------------------------- knuckle
    BOSS = (tx0 - 0.50, AXLE_Y)  # wheel-bearing housing
    BJ = (BOSS[0] - 0.03, AXLE_Y - 0.80)  # ball joint
    SY0 = AXLE_Y + 0.82  # strut clamp height
    SX = BOSS[0] - 0.33  # strut axis x at the clamp
    LEAN = 7  # strut lean, degrees

    # axle stub: boss to hub
    ax.plot(
        [BOSS[0] + 0.28, tx0 - 0.16],
        [AXLE_Y + 0.07, AXLE_Y + 0.07],
        color=INK,
        lw=1.0,
        zorder=5,
    )
    ax.plot(
        [BOSS[0] + 0.28, tx0 - 0.16],
        [AXLE_Y - 0.07, AXLE_Y - 0.07],
        color=INK,
        lw=1.0,
        zorder=5,
    )

    # upper link: strut clamp down to the bearing boss
    ax.add_patch(
        Polygon(
            [
                (SX - 0.15, SY0 + 0.02),
                (SX + 0.15, SY0 + 0.02),
                (BOSS[0] + 0.17, AXLE_Y + 0.26),
                (BOSS[0] - 0.17, AXLE_Y + 0.26),
            ],
            closed=True,
            fc="#ebebef",
            ec=INK,
            lw=1.2,
            joinstyle="round",
            zorder=5,
        )
    )
    # lower link: boss down to the ball joint
    ax.add_patch(
        Polygon(
            [
                (BOSS[0] - 0.15, AXLE_Y - 0.26),
                (BOSS[0] + 0.15, AXLE_Y - 0.26),
                (BJ[0] + 0.10, BJ[1] + 0.07),
                (BJ[0] - 0.10, BJ[1] + 0.07),
            ],
            closed=True,
            fc="#ebebef",
            ec=INK,
            lw=1.2,
            joinstyle="round",
            zorder=5,
        )
    )
    # bearing housing
    ax.add_patch(Circle(BOSS, 0.30, fc="#ebebef", ec=INK, lw=1.3, zorder=6))
    ax.add_patch(Circle(BOSS, 0.16, fc="#ffffff", ec=INK, lw=1.0, zorder=6))
    # ball joint
    ax.add_patch(Circle(BJ, 0.09, fc="#ffffff", ec=INK, lw=1.1, zorder=6))

    # ----------------------------------------------------------------- strut
    rot = Affine2D().rotate_deg_around(SX, SY0, LEAN) + ax.transData
    S_LEN = 2.10  # clamp to top of bearing cap, local
    SY1 = SY0 + S_LEN

    def strut_rect(x0, y0, w, h, **kw):
        ax.add_patch(Rectangle((x0, y0), w, h, transform=rot, **kw))

    # clamp around the damper foot
    strut_rect(SX - 0.24, SY0 - 0.16, 0.48, 0.34, fc="#ebebef", ec=INK, lw=1.2, zorder=5)
    for by in (SY0 - 0.065, SY0 + 0.105):
        ax.add_patch(
            Circle(
                (SX - 0.185, by),
                0.035,
                fc="#ffffff",
                ec=INK,
                lw=0.8,
                transform=rot,
                zorder=6,
            )
        )
        ax.add_patch(
            Circle(
                (SX + 0.185, by),
                0.035,
                fc="#ffffff",
                ec=INK,
                lw=0.8,
                transform=rot,
                zorder=6,
            )
        )
    # damper body
    strut_rect(SX - 0.185, SY0 + 0.10, 0.37, 1.02, fc="#ffffff", ec=INK, lw=1.4, zorder=6)
    for dy in (1.045, 0.975):  # rod gland
        ax.plot(
            [SX - 0.185, SX + 0.185],
            [SY0 + dy, SY0 + dy],
            color=INK,
            lw=0.7,
            transform=rot,
            zorder=7,
        )
    # piston rod
    strut_rect(
        SX - 0.045,
        SY0 + 1.12,
        0.09,
        S_LEN - 1.12 - 0.22,
        fc="#ffffff",
        ec=INK,
        lw=1.0,
        zorder=5,
    )
    # spring seats
    strut_rect(SX - 0.52, SY0 + 1.03, 1.04, 0.06, fc="#f5f5f7", ec=INK, lw=1.0, zorder=6)
    strut_rect(SX - 0.52, SY1 - 0.33, 1.04, 0.06, fc="#f5f5f7", ec=INK, lw=1.0, zorder=6)
    # coil spring
    sy0, sy1 = SY0 + 1.09, SY1 - 0.33
    t = np.linspace(0, 1, 400)
    xs = SX + 0.47 * np.sin(2 * np.pi * 5.5 * t + np.pi / 2)
    ys = sy0 + (sy1 - sy0) * t
    ax.plot(xs, ys, color=INK, lw=1.35, transform=rot, solid_capstyle="round", zorder=7)
    # top mount and bearing cap
    strut_rect(SX - 0.44, SY1 - 0.27, 0.88, 0.16, fc="#ebebef", ec=INK, lw=1.2, zorder=6)
    strut_rect(SX - 0.15, SY1 - 0.11, 0.30, 0.11, fc="#ffffff", ec=INK, lw=1.0, zorder=6)
    # strut axis centerline
    cl03(SX, SY0 - 0.45, SX, SY1 + 0.28, transform=rot)

    # top of the strut after the lean, in data coords
    TOPY = SY0 + math.cos(math.radians(LEAN)) * S_LEN

    # ------------------------------------------------------- body (sprung mass)
    bx0, bx1 = 3.70, 7.55
    by0, by1 = TOPY, TOPY + 0.42
    ax.add_patch(
        Rectangle(
            (bx0, by0), bx1 - bx0, by1 - by0, fc="#f5f5f7", ec=INK, lw=1.4, zorder=4
        )
    )
    ax.add_patch(
        Rectangle(
            (bx0, by0),
            bx1 - bx0,
            by1 - by0,
            fc="none",
            ec=HATCHC,
            lw=0,
            hatch="///",
            zorder=4,
        )
    )

    # ------------------------------------------- lower control arm and subframe
    PIV = (4.72, BJ[1] + 0.02)
    ax.add_patch(
        Polygon(
            [
                (BJ[0] - 0.04, BJ[1] - 0.085),
                (PIV[0], PIV[1] - 0.13),
                (PIV[0], PIV[1] + 0.13),
                (BJ[0] - 0.04, BJ[1] + 0.085),
            ],
            closed=True,
            fc="#ebebef",
            ec=INK,
            lw=1.2,
            joinstyle="round",
            zorder=4,
        )
    )
    ax.add_patch(Circle(PIV, 0.19, fc="#ffffff", ec=INK, lw=1.2, zorder=5))
    ax.add_patch(Circle(PIV, 0.085, fc="#ffffff", ec=INK, lw=0.9, zorder=5))
    sub = (PIV[0] - 0.56, PIV[1] - 0.36, 0.40, 0.80)
    ax.add_patch(
        Rectangle(sub[:2], sub[2], sub[3], fc="#f5f5f7", ec=INK, lw=1.3, zorder=4)
    )
    ax.add_patch(
        Rectangle(
            sub[:2], sub[2], sub[3], fc="none", ec=HATCHC, lw=0, hatch="///", zorder=4
        )
    )

    # ------------------------------------------------------------------- road
    ax.plot([3.4, 9.3], [GY, GY], color=INK, lw=1.5, zorder=3)
    for gx in np.arange(3.5, 9.25, 0.17):
        ax.plot([gx, gx - 0.11], [GY, GY - 0.11], color=GREY, lw=0.6, zorder=3)
    bx = np.linspace(8.35, 9.05, 60)
    bz = GY + 0.17 * np.sin(np.pi * (bx - 8.35) / 0.7) ** 2
    ax.plot(bx, bz, color=INK, lw=1.0, ls=(0, (4, 2.5)), zorder=4)

    # ------------------------------------------------------------- dimensions
    def dim_v03(x, y0, y1, text, xext):
        for yy in (y0, y1):
            ax.plot([xext, x + 0.12], [yy, yy], color=GREY, lw=0.55, zorder=3)
        ax.annotate(
            "",
            (x, y0),
            (x, y1),
            arrowprops=dict(arrowstyle="<->", color=INK, lw=0.8, shrinkA=0, shrinkB=0),
        )
        ax.text(
            x + 0.10,
            (y0 + y1) / 2,
            text,
            fontsize=8.5,
            color=INK,
            rotation=90,
            va="center",
            ha="left",
        )

    dim_v03(8.68, ty0, ty0 + TH, "Ø 640", xext=TIRE_CX + 0.45)

    def leader03(tx, ty, px, py, text, ha="left", fs=9.0):
        ax.plot([px, tx], [py, ty], color=GREY, lw=0.6, zorder=8)
        ax.add_patch(Circle((px, py), 0.028, fc=GREY, ec="none", zorder=8))
        ax.text(
            tx + (0.08 if ha == "left" else -0.08),
            ty,
            text,
            fontsize=fs,
            color=INK,
            ha=ha,
            va="center",
            zorder=9,
        )

    ax.text(
        7.72,
        (by0 + by1) / 2,
        "sprung mass  m$_s$ = 300 kg\na quarter of the body",
        fontsize=9.0,
        color=INK,
        ha="left",
        va="center",
        zorder=9,
    )
    leader03(3.30, 5.28, SX - 0.50, 5.02, "coil spring  k$_s$ = 20 kN/m")
    leader03(3.30, 4.45, SX - 0.20, SY0 + 0.62, "damper  c$_s$ = 1.5 kN·s/m")
    leader03(
        8.95, 4.72, tx0 + TW - 0.06, AXLE_Y + 1.08, "tyre stiffness  k$_t$ = 180 kN/m"
    )
    leader03(
        8.95,
        2.42,
        BOSS[0] + 0.21,
        AXLE_Y - 0.21,
        "unsprung mass  m$_u$ = 40 kg\n(wheel, hub, brake)",
    )
    leader03(6.95, GY - 0.48, 8.55, GY + 0.06, "road profile w(t): the input", ha="right")

    # ------------------------------------------------- the one violet element
    ATX, ATY = 2.30, by0 + 0.21
    ax.add_patch(Circle((ATX, ATY), 0.21, fc="#ffffff", ec=VIOLET, lw=1.4, zorder=9))
    ax.plot([ATX - 0.21, ATX + 0.21], [ATY, ATY], color=VIOLET, lw=0.8, zorder=10)
    ax.text(
        ATX,
        ATY + 0.075,
        "AT",
        fontsize=7.0,
        color=VIOLET,
        ha="center",
        va="center",
        weight="bold",
        zorder=10,
    )
    ax.text(
        ATX,
        ATY - 0.075,
        "03",
        fontsize=6.5,
        color=VIOLET,
        ha="center",
        va="center",
        zorder=10,
    )
    ax.plot(
        [ATX + 0.21, bx0], [ATY, ATY], color=VIOLET, lw=0.7, ls=(0, (4, 2.5)), zorder=9
    )
    ax.text(
        ATX,
        ATY - 0.36,
        "body acceleration:\nthe measurement",
        fontsize=7.6,
        color=GREY,
        ha="center",
        va="top",
        zorder=9,
    )
    save(fig, "t03_hero.png")


def pd_sheet(title: str, subtitle: str, number: str):
    return sheet(title, subtitle, number, w=16, h=8)


def line(ax, pts, lw=1.6, color=INK, ls="-", zorder=3, arrow=False):
    pts = np.array(pts, dtype=float)
    ax.plot(
        pts[:, 0],
        pts[:, 1],
        color=color,
        lw=lw,
        ls=ls,
        zorder=zorder,
        solid_joinstyle="miter",
        solid_capstyle="butt",
    )
    if arrow:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, mutation_scale=14),
            zorder=zorder,
        )


def signal(ax, pts, color=INK, zorder=3):
    """An instrument signal line: dashed (ISA electrical signal)."""
    line(ax, pts, lw=0.9, color=color, ls=(0, (4, 3)), zorder=zorder)


def bubble(ax, x, y, tag, number, r=0.32, field=True):
    """ISA instrument bubble: tag letters over loop number; a line across for a panel instrument."""
    ax.add_patch(Circle((x, y), r, fc=PAPER, ec=INK, lw=1.1, zorder=6))
    if not field:
        ax.plot([x - r, x + r], [y, y], color=INK, lw=1.0, zorder=6.1)
    ax.text(
        x,
        y + r * 0.32,
        tag,
        ha="center",
        va="center",
        fontsize=8.5,
        weight="bold",
        color=INK,
        zorder=7,
    )
    ax.text(
        x,
        y - r * 0.4,
        number,
        ha="center",
        va="center",
        fontsize=7.5,
        color=INK,
        zorder=7,
    )


def vessel(ax, x, y, w, h, label, fill_frac=0.6, water=True, rounded=False):
    """A vessel (open tank or closed vessel) with a liquid level."""
    style = "round,pad=0,rounding_size=0.25" if rounded else "square,pad=0"
    ax.add_patch(
        FancyBboxPatch((x, y), w, h, boxstyle=style, fc=PAPER, ec=INK, lw=1.6, zorder=4)
    )
    if water and fill_frac > 0:
        ax.add_patch(
            Rectangle(
                (x + 0.03, y + 0.03),
                w - 0.06,
                (h - 0.06) * fill_frac,
                fc=WATER[0],
                ec="none",
                zorder=4.1,
            )
        )
        ax.plot(
            [x + 0.03, x + w - 0.03],
            [y + 0.03 + (h - 0.06) * fill_frac] * 2,
            color=WATER[2],
            lw=0.8,
            zorder=4.2,
        )
    ax.text(
        x + w / 2,
        y + h + 0.18,
        label,
        ha="center",
        va="bottom",
        fontsize=9,
        weight="bold",
        color=INK,
        zorder=5,
    )


def pump_sym(ax, x, y, r=0.38, label="P-101"):
    """ISA centrifugal pump: circle with a discharge triangle."""
    ax.add_patch(Circle((x, y), r, fc=PAPER, ec=INK, lw=1.6, zorder=5))
    ax.add_patch(
        Polygon(
            [(x - r * 0.9, y - r * 0.95), (x + r * 0.9, y - r * 0.95), (x, y + r * 0.05)],
            closed=True,
            fc=INK,
            ec=INK,
            zorder=5.1,
        )
    )
    ax.text(
        x, y - r - 0.15, label, ha="center", va="top", fontsize=8.5, color=INK, zorder=6
    )


def valve(ax, x, y, size=0.26, label=None, vertical=False):
    """Gate valve: two triangles point to point."""
    if vertical:
        tri1 = [(x - size, y - size), (x + size, y - size), (x, y)]
        tri2 = [(x - size, y + size), (x + size, y + size), (x, y)]
    else:
        tri1 = [(x - size, y - size), (x - size, y + size), (x, y)]
        tri2 = [(x + size, y - size), (x + size, y + size), (x, y)]
    for t in (tri1, tri2):
        ax.add_patch(Polygon(t, closed=True, fc=PAPER, ec=INK, lw=1.4, zorder=5))
    if label:
        ax.text(
            x,
            y + size + 0.12,
            label,
            ha="center",
            va="bottom",
            fontsize=8,
            color=INK,
            zorder=6,
        )


def orifice_plate(ax, x, y, label="FE"):
    ax.plot([x, x], [y - 0.32, y + 0.32], color=INK, lw=2.2, zorder=5)
    ax.plot([x - 0.14, x + 0.14], [y + 0.32, y + 0.32], color=INK, lw=1.2, zorder=5)
    ax.plot([x - 0.14, x + 0.14], [y - 0.32, y - 0.32], color=INK, lw=1.2, zorder=5)
    ax.text(x, y - 0.5, label, ha="center", va="top", fontsize=8, color=INK, zorder=6)


def filter_sym(ax, x, y, w=0.7, h=0.5, label="F-101"):
    ax.add_patch(
        Rectangle((x - w / 2, y - h / 2), w, h, fc=PAPER, ec=INK, lw=1.4, zorder=5)
    )
    for k in np.linspace(-w / 2 + 0.1, w / 2 - 0.1, 5):
        ax.plot(
            [x + k, x + k],
            [y - h / 2, y + h / 2],
            color=INK,
            lw=0.6,
            ls=(0, (2, 2)),
            zorder=5.1,
        )
    ax.text(
        x,
        y - h / 2 - 0.12,
        label,
        ha="center",
        va="top",
        fontsize=8.5,
        color=INK,
        zorder=6,
    )


def equipment(ax, x, y, w, h, label, sub=None, fc=PAPER):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=INK, lw=1.6, zorder=4))
    ax.text(
        x + w / 2,
        y + h / 2 + (0.1 if sub else 0),
        label,
        ha="center",
        va="center",
        fontsize=9,
        weight="bold",
        color=INK,
        zorder=5,
    )
    if sub:
        ax.text(
            x + w / 2,
            y + h / 2 - 0.22,
            sub,
            ha="center",
            va="center",
            fontsize=7.8,
            color=GREY,
            zorder=5,
        )


def note(ax, x, y, text, fontsize=8.5, ha="left"):
    ax.text(x, y, text, fontsize=fontsize, color=INK, ha=ha, va="center", zorder=7)


def legend_box(ax, x, y, items, title="LEGEND"):
    h = 0.32 * len(items) + 0.45
    ax.add_patch(Rectangle((x, y), 4.6, h, fc=PAPER, ec=INK, lw=0.8, zorder=6))
    ax.text(
        x + 0.12,
        y + h - 0.22,
        title,
        fontsize=8,
        weight="bold",
        color=INK,
        va="center",
        zorder=7,
    )
    for i, (sym, text) in enumerate(items):
        yy = y + h - 0.55 - 0.32 * i
        ax.text(
            x + 0.12,
            yy,
            sym,
            fontsize=8,
            color=INK,
            va="center",
            zorder=7,
            family="monospace",
        )
        ax.text(x + 1.5, yy, text, fontsize=8, color=INK, va="center", zorder=7)


# IEC electrical symbols


def resistor_sym(ax, x0, x1, y, label=None, vertical=False, w=0.26):
    """IEC 60617 resistor: a rectangle in the line."""
    if vertical:
        ax.add_patch(
            Rectangle((y - w / 2, x0), w, x1 - x0, fc=PAPER, ec=INK, lw=1.5, zorder=5)
        )
        if label:
            ax.text(
                y + w / 2 + 0.1,
                (x0 + x1) / 2,
                label,
                fontsize=8.5,
                color=INK,
                va="center",
                zorder=6,
            )
    else:
        ax.add_patch(
            Rectangle((x0, y - w / 2), x1 - x0, w, fc=PAPER, ec=INK, lw=1.5, zorder=5)
        )
        if label:
            ax.text(
                (x0 + x1) / 2,
                y + w / 2 + 0.1,
                label,
                fontsize=8.5,
                color=INK,
                ha="center",
                va="bottom",
                zorder=6,
            )


def inductor_sym(ax, x0, x1, y, label=None, n=4):
    xs = np.linspace(x0, x1, n + 1)
    for a, b in zip(xs[:-1], xs[1:], strict=True):
        th = np.linspace(0, np.pi, 20)
        ax.plot(
            (a + b) / 2 + (b - a) / 2 * np.cos(th),
            y + (b - a) / 2 * np.sin(th),
            color=INK,
            lw=1.5,
            zorder=5,
        )
    if label:
        ax.text(
            (x0 + x1) / 2,
            y + 0.32,
            label,
            fontsize=8.5,
            color=INK,
            ha="center",
            va="bottom",
            zorder=6,
        )


def capacitor_sym(ax, x, y, label=None, vertical=True, gap=0.1, plate=0.5):
    if vertical:
        ax.plot(
            [x - plate / 2, x + plate / 2],
            [y + gap, y + gap],
            color=INK,
            lw=2.0,
            zorder=5,
        )
        ax.plot(
            [x - plate / 2, x + plate / 2],
            [y - gap, y - gap],
            color=INK,
            lw=2.0,
            zorder=5,
        )
        if label:
            ax.text(
                x + plate / 2 + 0.12,
                y,
                label,
                fontsize=8.5,
                color=INK,
                va="center",
                zorder=6,
            )
    else:
        ax.plot(
            [x + gap, x + gap],
            [y - plate / 2, y + plate / 2],
            color=INK,
            lw=2.0,
            zorder=5,
        )
        ax.plot(
            [x - gap, x - gap],
            [y - plate / 2, y + plate / 2],
            color=INK,
            lw=2.0,
            zorder=5,
        )
        if label:
            ax.text(
                x,
                y + plate / 2 + 0.1,
                label,
                fontsize=8.5,
                color=INK,
                ha="center",
                va="bottom",
                zorder=6,
            )


def source_sym(ax, x, y, kind="V", label=None, r=0.36):
    ax.add_patch(Circle((x, y), r, fc=PAPER, ec=INK, lw=1.5, zorder=5))
    if kind == "V":
        ax.plot(
            [x, x], [y - r * 0.55, y + r * 0.55], color=INK, lw=1.3, zorder=5.1
        )  # IEC DC source: a line
        ax.text(
            x - r * 0.55,
            y + r * 0.1,
            "+",
            fontsize=8,
            color=INK,
            ha="center",
            va="center",
            zorder=6,
        )
    else:
        ax.annotate(
            "",
            xy=(x, y + r * 0.6),
            xytext=(x, y - r * 0.6),
            arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.3, mutation_scale=10),
            zorder=5.1,
        )
    if label:
        ax.text(x + r + 0.12, y, label, fontsize=8.5, color=INK, va="center", zorder=6)


def ground_sym(ax, x, y):
    ax.plot([x, x], [y, y - 0.25], color=INK, lw=1.4, zorder=5)
    for i, w in enumerate((0.42, 0.28, 0.14)):
        ax.plot(
            [x - w / 2, x + w / 2], [y - 0.25 - 0.1 * i] * 2, color=INK, lw=1.4, zorder=5
        )


def battery_sym(ax, x, y, label=None, cells=3):
    for i in range(cells):
        yy = y - 0.3 + i * 0.3
        ax.plot([x - 0.3, x + 0.3], [yy + 0.08, yy + 0.08], color=INK, lw=2.2, zorder=5)
        ax.plot([x - 0.14, x + 0.14], [yy - 0.06, yy - 0.06], color=INK, lw=1.2, zorder=5)
    if label:
        ax.text(x + 0.45, y, label, fontsize=8.5, color=INK, va="center", zorder=6)


def transformer_sym(ax, x, y, label=None):
    """Two coils with a core line between them."""
    for side in (-1, 1):
        xs = x + side * 0.22
        th = np.linspace(-np.pi / 2, np.pi / 2, 20)
        for k in range(4):
            yy = y - 0.45 + k * 0.3
            ax.plot(
                xs + side * 0.15 * np.cos(th),
                yy + 0.15 * np.sin(th),
                color=INK,
                lw=1.4,
                zorder=5,
            )
    ax.plot([x - 0.04, x - 0.04], [y - 0.55, y + 0.55], color=INK, lw=1.0, zorder=5)
    ax.plot([x + 0.04, x + 0.04], [y - 0.55, y + 0.55], color=INK, lw=1.0, zorder=5)
    if label:
        ax.text(x, y + 0.7, label, fontsize=8.5, color=INK, ha="center", zorder=6)


# mechanical symbols


def mass_sym(ax, x, y, w, h, label):
    ax.add_patch(Rectangle((x, y), w, h, fc="#e8e8ed", ec=INK, lw=1.6, zorder=5))
    ax.text(
        x + w / 2,
        y + h / 2,
        label,
        ha="center",
        va="center",
        fontsize=9,
        weight="bold",
        color=INK,
        zorder=6,
    )


def spring_sym(ax, x, y0, y1, label=None, n=6, amp=0.13):
    zigzag(ax, (x, y0), (x, y1), n=n, amp=amp, color=INK, lw=1.5, zorder=5)
    if label:
        ax.text(
            x - 0.25,
            (y0 + y1) / 2,
            label,
            fontsize=8.5,
            color=INK,
            ha="right",
            va="center",
            zorder=6,
        )


def damper_sym(ax, x, y0, y1, label=None):
    ym = (y0 + y1) / 2
    ax.plot([x, x], [y0, ym - 0.15], color=INK, lw=1.5, zorder=5)
    ax.plot(
        [x - 0.18, x - 0.18, x + 0.18, x + 0.18],
        [ym + 0.3, ym - 0.15, ym - 0.15, ym + 0.3],
        color=INK,
        lw=1.5,
        zorder=5,
    )
    ax.plot([x - 0.14, x + 0.14], [ym + 0.12, ym + 0.12], color=INK, lw=1.8, zorder=5)
    ax.plot([x, x], [ym + 0.12, y1], color=INK, lw=1.5, zorder=5)
    if label:
        ax.text(x + 0.3, ym, label, fontsize=8.5, color=INK, va="center", zorder=6)


def hatch(ax, x0, x1, y, up=False, n=10):
    ax.plot([x0, x1], [y, y], color=INK, lw=1.6, zorder=5)
    for xx in np.linspace(x0, x1, n):
        ax.plot(
            [xx, xx - 0.18], [y, y + (0.18 if up else -0.18)], color=INK, lw=0.9, zorder=5
        )


# ---------------------------------------------------------------- the PDs


def pd_bess():
    fig, ax = pd_sheet(
        "BESS: electrical and thermal diagram",
        "Battery, PCS load, container air, HVAC",
        "T01-PD",
    )
    # electrical loop (IEC)
    battery_sym(ax, 2.6, 4.6, label="BT-01  2 MWh")
    line(ax, [(2.6, 4.9), (2.6, 5.9), (6.4, 5.9)])
    source_sym(ax, 6.4, 5.2, kind="I", label="PCS: dispatch current (input)")
    line(ax, [(6.4, 5.56), (6.4, 5.9)])
    line(ax, [(6.4, 4.84), (6.4, 3.4), (2.6, 3.4), (2.6, 4.3)])
    ground_sym(ax, 4.5, 3.4)
    resistor_sym(ax, 3.4, 4.6, 5.9, label="R_s: ohmic", w=0.26)
    note(
        ax,
        2.0,
        2.7,
        "Electrical: an equivalent circuit the Battery component builds (OCV(SoC), R_s, one RC pair).",
    )
    # thermal part (ISA style)
    equipment(ax, 9.2, 4.6, 2.0, 1.1, "RACK", "cell mass, 1.2 MJ/K", fc="#f5f5f7")
    equipment(ax, 12.2, 4.6, 2.0, 1.1, "AIR", "container air", fc="#f5f5f7")
    line(ax, [(11.2, 5.15), (12.2, 5.15)])
    note(ax, 11.7, 5.45, "hA", fontsize=8, ha="center")
    line(ax, [(13.2, 4.6), (13.2, 3.2)], arrow=True)
    note(ax, 13.45, 3.9, "HVAC: heat removed (input)")
    line(ax, [(14.2, 5.15), (15.2, 5.15)])
    note(ax, 14.7, 5.45, "walls", fontsize=8, ha="center")
    bubble(ax, 15.2, 5.15, "TT", "02", r=0.3)
    note(ax, 15.2, 5.75, "ambient", fontsize=8, ha="center")
    bubble(ax, 10.2, 6.5, "TT", "01", r=0.3)
    signal(ax, [(10.2, 6.2), (10.2, 5.7)])
    line(ax, [(7.4, 5.15), (9.2, 5.15)], arrow=True, color=RED)
    note(ax, 8.3, 5.45, "I²R losses", fontsize=8, ha="center")
    note(
        ax,
        9.2,
        2.7,
        "Thermal: cell mass, convection to the air, HVAC extraction, wall losses to ambient.",
    )
    legend_box(
        ax,
        0.6,
        0.6,
        [
            ("—", "process / power"),
            ("- -", "instrument signal"),
            ("TT", "temperature transmitter"),
            ("BT", "battery"),
        ],
    )
    save(fig, "t01_pd.png")


def pd_feeder():
    fig, ax = pd_sheet(
        "DC feeder: single-line diagram",
        "Source, cable, DC link, converter, loads",
        "T02-PD",
    )
    y = 5.0
    source_sym(ax, 1.6, y - 1.2, kind="V", label="")
    note(ax, 1.6, y - 2.0, "U_s 750 V (input)", ha="center", fontsize=8)
    line(ax, [(1.6, y - 0.84), (1.6, y), (2.6, y)])
    resistor_sym(ax, 2.6, 3.8, y, label="R_cable 0.20 Ω")
    line(ax, [(3.8, y), (4.4, y)])
    inductor_sym(ax, 4.4, 5.8, y, label="L_cable 2 mH")
    line(ax, [(5.8, y), (7.6, y)])
    capacitor_sym(ax, 7.6, y - 1.0, label="C_dc 10 mF", vertical=True)
    line(ax, [(7.6, y), (7.6, y - 0.9)])
    line(ax, [(7.6, y - 1.1), (7.6, y - 2.4)])
    line(ax, [(7.6, y), (9.0, y)])
    transformer_sym(ax, 9.5, y - 0.4, label="DC/DC 750 V : 48 V")
    line(ax, [(9.0, y), (9.28, y)])
    line(ax, [(9.0, y - 1.3), (9.0, y - 2.4)])
    line(ax, [(9.0, y - 0.8), (9.28, y - 0.8), (9.0, y - 0.8), (9.0, y - 1.3)])
    line(ax, [(9.72, y), (11.4, y)])
    source_sym(ax, 11.4, y - 1.2, kind="I", label="I_load (input)")
    line(ax, [(11.4, y), (11.4, y - 0.84)])
    line(ax, [(11.4, y - 1.56), (11.4, y - 2.4), (9.72, y - 2.4), (9.72, y - 0.8)])
    line(ax, [(1.6, y - 1.56), (1.6, y - 2.4), (9.0, y - 2.4)])
    ground_sym(ax, 4.6, y - 2.4)
    resistor_sym(ax, 12.4, 13.6, y, label="R_leak", w=0.22)
    line(ax, [(11.4, y), (12.4, y)])
    line(ax, [(13.6, y), (14.2, y), (14.2, y - 2.4), (11.4, y - 2.4)])
    bubble(ax, 7.6, 6.4, "ET", "01", r=0.3)
    signal(ax, [(7.6, 6.1), (7.6, y + 0.05)])
    bubble(ax, 11.4, 6.4, "ET", "02", r=0.3)
    signal(ax, [(11.4, 6.1), (11.4, y + 0.05)])
    note(
        ax,
        1.0,
        1.6,
        "IEC 60617 symbols. Primary and secondary of the ideal converter share the return; the transformer carries power without loss.",
    )
    save(fig, "t02_pd.png")


def pd_suspension():
    fig, ax = pd_sheet(
        "Quarter-car suspension: mechanical schematic",
        "Two masses, two springs, one damper, a road input",
        "T03-PD",
    )
    x = 6.5
    mass_sym(ax, x - 1.2, 5.6, 2.4, 0.9, "m_s  sprung  300 kg")
    spring_sym(ax, x - 0.5, 4.2, 5.6, label="k_s 20 kN/m")
    damper_sym(ax, x + 0.5, 4.2, 5.6, label="c_s 1.5 kN s/m")
    mass_sym(ax, x - 1.2, 3.3, 2.4, 0.9, "m_u  unsprung  40 kg")
    spring_sym(ax, x, 2.0, 3.3, label="k_t tyre 180 kN/m")
    ax.plot([x - 1.2, x + 1.2], [2.0, 2.0], color=INK, lw=1.6, zorder=5)
    ax.annotate(
        "",
        xy=(x + 1.9, 2.5),
        xytext=(x + 1.9, 1.5),
        arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=1.2),
        zorder=6,
    )
    note(ax, x + 2.1, 2.0, "z_r: road velocity (input)")
    line(ax, [(x + 1.2, 6.05), (x + 2.6, 6.05)], arrow=True, color=RED)
    note(ax, x + 2.8, 6.05, "F: payload / brake force (input)")
    hatch(ax, x - 3.0, x - 1.6, 1.0, up=False)
    note(ax, x - 2.3, 0.7, "inertial frame", fontsize=8, ha="center")
    ax.plot([x - 2.3, x - 2.3], [1.0, 1.6], color=INK, lw=1.0, ls=(0, (3, 3)), zorder=5)
    bubble(ax, 2.4, 6.0, "ZT", "01", r=0.3)
    signal(ax, [(2.7, 6.0), (x - 1.2, 6.0)])
    bubble(ax, 2.4, 3.7, "ZT", "02", r=0.3)
    signal(ax, [(2.7, 3.7), (x - 1.2, 3.7)])
    note(
        ax,
        1.0,
        1.6,
        "Velocity is the across variable, force the through variable; a VelocitySource drives the tyre contact, a Fixed port is the frame.",
    )
    save(fig, "t03_pd.png")


def pd_turbine():
    fig, ax = pd_sheet(
        "Wind turbine drivetrain: rotational schematic",
        "Rotor inertia, shaft torsion, gearbox, generator",
        "T04-PD",
    )
    y = 4.8
    ax.add_patch(Circle((2.2, y), 0.75, fc="#e8e8ed", ec=INK, lw=1.6, zorder=5))
    note(ax, 2.2, y, "J_r\nrotor", ha="center", fontsize=8.5)
    line(ax, [(0.6, y), (1.45, y)], arrow=True, color=RED)
    note(ax, 0.5, y + 0.45, "T_aero (input)", fontsize=8)
    line(ax, [(2.95, y), (3.6, y)])
    zigzag(ax, (3.6, y), (5.4, y), n=7, amp=0.15, color=INK, lw=1.5)
    note(ax, 4.5, y + 0.45, "k_shaft  torsion", ha="center", fontsize=8.5)
    line(ax, [(5.4, y), (6.2, y)])
    equipment(ax, 6.2, y - 0.6, 1.6, 1.2, "GEAR", "1 : 90", fc="#f5f5f7")
    line(ax, [(7.8, y), (9.0, y)])
    ax.add_patch(Circle((9.5, y), 0.5, fc="#e8e8ed", ec=INK, lw=1.6, zorder=5))
    note(ax, 9.5, y, "J_g", ha="center", fontsize=8.5)
    line(ax, [(10.0, y), (11.0, y)])
    equipment(ax, 11.0, y - 0.6, 2.0, 1.2, "GEN", "held at ω_grid", fc="#f5f5f7")
    # bearing damper to housing, under the rotor shaft
    damper_sym(ax, 3.2, y - 1.9, y - 0.1, label="c_b  bearing")
    hatch(ax, 2.6, 3.8, y - 1.9, up=False)
    note(ax, 3.2, y - 2.3, "housing", ha="center", fontsize=8)
    bubble(ax, 9.5, 6.6, "ST", "01", r=0.3)
    signal(ax, [(9.5, 6.3), (9.5, y + 0.55)])
    bubble(ax, 4.5, 6.6, "WT", "01", r=0.3)
    signal(ax, [(4.5, 6.3), (4.5, y + 0.2)])
    note(
        ax,
        1.0,
        1.6,
        "Angular velocity across, torque through. The gearbox is a Transformer between two rotational sides; the generator a SpeedSource.",
    )
    save(fig, "t04_pd.png")


def pd_water():
    fig, ax = pd_sheet(
        "Water supply: process and instrumentation diagram",
        "Reservoir, pump, filter, rising main, elevated tank, demand",
        "T05-PD",
    )
    vessel(ax, 1.0, 2.6, 2.2, 1.8, "TK-101  RESERVOIR", fill_frac=0.7)
    line(ax, [(3.2, 3.0), (4.2, 3.0)])
    pump_sym(ax, 4.6, 3.0, label="P-101")
    line(ax, [(4.98, 3.0), (5.8, 3.0)])
    filter_sym(ax, 6.2, 3.0, label="F-101")
    line(ax, [(6.55, 3.0), (7.4, 3.0)])
    valve(ax, 7.7, 3.0, label="HV-101")
    line(ax, [(7.96, 3.0), (9.4, 3.0), (9.4, 5.2)])
    note(ax, 8.6, 3.3, "rising main DN200", fontsize=8, ha="center")
    note(ax, 8.6, 2.7, "L = 1.2 km", fontsize=8, ha="center")
    vessel(ax, 8.6, 5.2, 1.6, 1.4, "TK-102  ELEVATED TANK", fill_frac=0.55)
    note(ax, 10.6, 6.9, "z = 30 m", fontsize=8, ha="center")
    line(ax, [(10.2, 5.6), (11.6, 5.6)])
    orifice_plate(ax, 11.9, 5.6, label="FE-102")
    line(ax, [(12.2, 5.6), (13.4, 5.6)], arrow=True)
    equipment(ax, 13.4, 5.2, 1.6, 0.8, "DEMAND", "q(t) input", fc="#f5f5f7")
    bubble(ax, 2.1, 5.3, "LT", "101", r=0.3)
    signal(ax, [(2.1, 5.0), (2.1, 4.45)])
    bubble(ax, 9.4, 7.5, "LT", "102", r=0.3)
    signal(ax, [(9.4, 7.2), (9.4, 6.65)])
    bubble(ax, 5.9, 4.4, "PT", "101", r=0.3)
    signal(ax, [(5.9, 4.1), (5.4, 3.0)])
    bubble(ax, 11.9, 4.4, "FT", "102", r=0.3)
    signal(ax, [(11.9, 4.7), (11.9, 5.25)])
    legend_box(
        ax,
        0.6,
        0.6,
        [
            ("TK", "tank"),
            ("P / F / HV", "pump, filter, hand valve"),
            ("LT PT FT", "level, pressure, flow transmitter"),
            ("FE", "orifice plate"),
        ],
    )
    save(fig, "t05_pd.png")


def pd_wastewater():
    fig, ax = pd_sheet(
        "Chlorine contact tank: P&ID",
        "Secondary effluent, hypochlorite dosing, four contact cells, outfall",
        "T06-PD",
    )
    line(ax, [(0.8, 4.0), (2.6, 4.0)], arrow=True)
    note(ax, 1.0, 4.35, "secondary effluent 0.35 m³/s", fontsize=8)
    bubble(ax, 1.9, 5.2, "FT", "201", r=0.3)
    signal(ax, [(1.9, 4.9), (1.9, 4.05)])
    # dosing
    vessel(ax, 1.0, 5.9, 1.2, 1.2, "TK-201  NaOCl", fill_frac=0.6, rounded=True)
    line(ax, [(2.2, 6.3), (3.0, 6.3)])
    pump_sym(ax, 3.3, 6.3, r=0.3, label="P-201 dosing")
    line(ax, [(3.6, 6.3), (4.1, 6.3), (4.1, 4.3)], arrow=True)
    bubble(ax, 4.9, 6.9, "FIC", "201", r=0.32, field=False)
    signal(ax, [(4.6, 6.9), (3.3, 6.9), (3.3, 6.6)])
    # contact cells
    for k in range(4):
        vessel(ax, 2.6 + k * 2.3, 3.0, 2.0, 1.3, f"CELL {k + 1}", fill_frac=0.75)
        if k < 3:
            line(ax, [(4.6 + k * 2.3, 3.6), (4.9 + k * 2.3, 3.6)], arrow=True)
    note(ax, 7.2, 2.6, "4 × 650 m³, serpentine, τ = 2.1 h", fontsize=8.5, ha="center")
    line(ax, [(11.8, 3.6), (13.6, 3.6)], arrow=True)
    equipment(ax, 13.6, 3.2, 1.6, 0.8, "OUTFALL", "Cl₂ ≥ 0.2 mg/L", fc="#f5f5f7")
    bubble(ax, 12.7, 5.0, "AT", "202", r=0.3)
    signal(ax, [(12.7, 4.7), (12.7, 3.65)])
    note(ax, 12.7, 5.5, "residual chlorine", fontsize=8, ha="center")
    bubble(ax, 5.6, 1.6, "AT", "201", r=0.3)
    signal(ax, [(5.6, 1.9), (5.6, 3.0)])
    legend_box(
        ax,
        11.0,
        6.0,
        [
            ("AT", "analyser transmitter"),
            ("FIC", "flow controller (panel)"),
            ("TK / P", "tank, pump"),
        ],
    )
    save(fig, "t06_pd.png")


def pd_building():
    fig, ax = pd_sheet(
        "Heated building: thermal network",
        "Boiler, water loop, room air, envelope, ventilation, weather",
        "T07-PD",
    )
    y = 4.6
    source_sym(ax, 1.6, y, kind="V", label="")
    note(ax, 1.6, y - 0.75, "U_mains 230 V", ha="center", fontsize=8)
    line(ax, [(1.6, y + 0.36), (1.6, y + 1.2), (3.0, y + 1.2)])
    resistor_sym(ax, 3.0, 4.2, y + 1.2, label="R_el heater element")
    line(
        ax,
        [(4.2, y + 1.2), (5.2, y + 1.2), (5.2, y - 1.0), (1.6, y - 1.0), (1.6, y - 0.36)],
    )
    ground_sym(ax, 3.4, y - 1.0)
    line(ax, [(3.6, y + 0.95), (3.6, y + 0.3), (6.0, y + 0.3)], arrow=True, color=RED)
    note(ax, 4.9, y + 0.55, "I²R to heat", fontsize=8, ha="center")
    equipment(ax, 6.0, y - 0.3, 1.8, 1.2, "WATER", "C_w  boiler loop", fc="#f5f5f7")
    line(ax, [(7.8, y + 0.3), (9.2, y + 0.3)])
    note(ax, 8.5, y + 0.6, "radiators hA", fontsize=8, ha="center")
    equipment(ax, 9.2, y - 0.3, 1.8, 1.2, "ROOM", "C_air", fc="#f5f5f7")
    line(ax, [(11.0, y + 0.3), (12.4, y + 0.3)])
    note(ax, 11.7, y + 0.6, "walls R_wall", fontsize=8, ha="center")
    line(ax, [(10.1, y - 0.3), (10.1, y - 1.6), (12.4, y - 1.6)])
    note(ax, 11.25, y - 1.3, "ventilation ṁ c_p", fontsize=8, ha="center")
    equipment(ax, 12.4, y - 1.9, 2.0, 2.5, "OUTDOOR", "T_out(t) input", fc="#f5f5f7")
    line(ax, [(10.1, y + 0.9), (10.1, y + 1.9)], arrow=True, color=RED)
    note(ax, 10.1, y + 2.2, "solar + occupants (input)", fontsize=8, ha="center")
    bubble(ax, 7.9, 6.6, "TT", "301", r=0.3)
    signal(ax, [(7.9, 6.3), (6.9, y + 0.9)])
    bubble(ax, 8.8, 6.6, "TT", "302", r=0.3)
    signal(ax, [(8.8, 6.3), (9.9, y + 0.9)])
    note(
        ax,
        1.0,
        1.4,
        "Temperature across, heat flow through. The heater's electrical losses enter the water through a Losses element; the model is pseudo-port-Hamiltonian.",
    )
    save(fig, "t07_pd.png")


def pd_pumpdrive():
    fig, ax = pd_sheet(
        "Motor-driven pump: multi-domain schematic",
        "Electrical supply, DC machine, shaft, gear pump, hydraulic circuit",
        "T08-PD",
    )
    y = 4.8
    source_sym(ax, 1.4, y - 0.8, kind="V", label="")
    note(ax, 1.4, y - 1.55, "U (input)", ha="center", fontsize=8)
    line(ax, [(1.4, y - 0.44), (1.4, y), (2.4, y)])
    resistor_sym(ax, 2.4, 3.3, y, label="R_a")
    line(ax, [(3.3, y), (3.7, y)])
    inductor_sym(ax, 3.7, 4.7, y, label="L_a")
    line(ax, [(4.7, y), (5.4, y)])
    ax.add_patch(Circle((5.9, y), 0.5, fc=PAPER, ec=INK, lw=1.6, zorder=5))
    note(ax, 5.9, y, "M", ha="center", fontsize=11)
    line(ax, [(5.9, y - 0.5), (5.9, y - 1.6), (1.4, y - 1.6), (1.4, y - 1.16)])
    ground_sym(ax, 3.6, y - 1.6)
    line(ax, [(6.4, y), (7.4, y)], lw=3.0)
    note(ax, 6.9, y + 0.35, "shaft", fontsize=8, ha="center")
    ax.add_patch(Circle((7.9, y), 0.5, fc="#e8e8ed", ec=INK, lw=1.6, zorder=5))
    note(ax, 7.9, y, "J", ha="center", fontsize=9)
    line(ax, [(8.4, y), (9.2, y)], lw=3.0)
    equipment(ax, 9.2, y - 0.6, 1.6, 1.2, "PUMP", "D = 20 cm³/rev", fc="#f5f5f7")
    line(ax, [(10.8, y + 0.3), (12.4, y + 0.3)], arrow=True)
    valve(ax, 12.8, y + 0.3, label="HV")
    line(ax, [(13.06, y + 0.3), (14.0, y + 0.3), (14.0, y + 1.2)])
    vessel(ax, 13.3, y + 1.2, 1.4, 1.2, "TK  head tank", fill_frac=0.5)
    line(
        ax,
        [(14.0, y - 0.3), (14.0, y - 1.4), (9.0, y - 1.4), (9.0, y - 0.6)],
        arrow=False,
    )
    note(ax, 11.5, y - 1.15, "return at atmosphere", fontsize=8, ha="center")
    bubble(ax, 11.6, 6.5, "PT", "401", r=0.3)
    signal(ax, [(11.6, 6.2), (11.6, y + 0.35)])
    bubble(ax, 7.9, 6.5, "ST", "401", r=0.3)
    signal(ax, [(7.9, 6.2), (7.9, y + 0.55)])
    note(
        ax,
        1.0,
        1.4,
        "Three domains, two couplings: the machine is a Transformer (back-emf k ω, torque k i), the gear pump a Gyrator (flow D ω, torque D Δp).",
    )
    save(fig, "t08_pd.png")


def pd_flywheel():
    fig, ax = pd_sheet(
        "Flywheel storage: energy flow schematic",
        "Converter, motor-generator, rotor, bearings",
        "T09-PD",
    )
    y = 4.8
    source_sym(ax, 1.6, y - 0.8, kind="V", label="")
    note(ax, 1.6, y - 1.55, "U_dc (input)", ha="center", fontsize=8)
    line(ax, [(1.6, y - 0.44), (1.6, y), (2.8, y)])
    resistor_sym(ax, 2.8, 3.8, y, label="R_w winding")
    line(ax, [(3.8, y), (4.8, y)])
    equipment(ax, 4.8, y - 0.6, 2.0, 1.2, "M / G", "gyrator  τ = k i", fc="#f5f5f7")
    line(ax, [(5.8, y - 0.6), (5.8, y - 1.6), (1.6, y - 1.6), (1.6, y - 1.16)])
    ground_sym(ax, 3.7, y - 1.6)
    line(ax, [(6.8, y), (8.0, y)], lw=3.0)
    ax.add_patch(Circle((8.9, y), 0.9, fc="#d9d9de", ec=INK, lw=1.8, zorder=5))
    ax.add_patch(Circle((8.9, y), 0.18, fc=INK, ec=INK, zorder=5.2))
    note(ax, 8.9, y - 1.2, "J rotor  ½Jω²", ha="center", fontsize=8.5)
    line(ax, [(9.8, y), (10.8, y)], lw=3.0)
    damper_sym(ax, 11.4, y - 1.4, y + 0.2, label="c  bearings, windage")
    line(ax, [(10.8, y), (11.4, y), (11.4, y + 0.2)])
    hatch(ax, 10.9, 11.9, y - 1.4, up=False)
    bubble(ax, 8.9, 6.6, "ST", "501", r=0.3)
    signal(ax, [(8.9, 6.3), (8.9, y + 0.95)])
    bubble(ax, 3.3, 6.6, "ET", "501", r=0.3)
    signal(ax, [(3.3, 6.3), (3.3, y + 0.15)])
    note(
        ax,
        1.0,
        1.4,
        "Built from the fundamental elements only: Storage, Dissipator, Source, Reference and a Gyrator, with the domain given by name.",
    )
    save(fig, "t09_pd.png")


def pd_twin():
    fig, ax = pd_sheet(
        "Digital twin of the elevated tank: data flow",
        "Measurement, model, fit, forecast, audit, decision",
        "T10-PD",
    )
    vessel(ax, 1.0, 3.6, 1.6, 1.6, "TK-102", fill_frac=0.55)
    bubble(ax, 1.8, 6.1, "LT", "102", r=0.3)
    signal(ax, [(1.8, 5.8), (1.8, 5.25)])
    line(ax, [(0.4, 4.0), (1.0, 4.0)], arrow=True)
    note(ax, 0.3, 4.3, "inflow", fontsize=8)
    line(ax, [(2.6, 4.0), (3.4, 4.0)])
    valve(ax, 3.7, 4.0, label="CV-102")
    line(ax, [(3.96, 4.0), (4.8, 4.0)], arrow=True)
    note(ax, 4.9, 4.0, "to the town")
    # the twin pipeline as blocks
    xs = [6.0, 8.3, 10.6, 12.9]
    labels = [
        ("MODEL", "Tank, Valve, components"),
        ("FIT", "fit_parameters: C_v"),
        ("FORECAST", "conformal 90 % range"),
        ("AUDIT", "coverage by horizon"),
    ]
    for x, (l1, l2) in zip(xs, labels, strict=True):
        equipment(ax, x, 5.2, 1.9, 1.1, l1, l2, fc="#f5f5f7")
    for a, b in zip(xs[:-1], xs[1:], strict=True):
        line(ax, [(a + 1.9, 5.75), (b, 5.75)], arrow=True)
    signal(ax, [(2.1, 6.1), (6.9, 6.1), (6.9, 6.3)])
    signal(ax, [(2.1, 6.1), (2.1, 7.0), (13.8, 7.0), (13.8, 6.3)])
    note(ax, 8.0, 7.25, "measurements (held-out days go only to the audit)", fontsize=8)
    equipment(
        ax,
        10.6,
        2.8,
        4.2,
        1.1,
        "DECIDE OR REFUSE",
        "Envelope: inside the validated range, or a refusal with the reason",
        fc="#efe6ff",
    )
    line(ax, [(13.85, 5.2), (13.85, 3.9)], arrow=True)
    note(
        ax,
        1.0,
        1.4,
        "What Otwin adds after the model exists: how wrong it has been, a range that was measured to hold, and a decision that can say no.",
    )
    save(fig, "t10_pd.png")


if __name__ == "__main__":
    for fn in (
        hero_bess,
        hero_feeder,
        hero_suspension,
        hero_turbine,
        hero_water,
        hero_wastewater,
        hero_building,
        hero_pumpdrive,
        hero_flywheel,
        hero_twin,
        readme_header,
        pd_bess,
        pd_feeder,
        pd_suspension,
        pd_turbine,
        pd_water,
        pd_wastewater,
        pd_building,
        pd_pumpdrive,
        pd_flywheel,
        pd_twin,
    ):
        fn()
