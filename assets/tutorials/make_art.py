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
from matplotlib.patches import Circle, Ellipse, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "tutorials" / "images"

INK, RED, GREY, LIGHT, PAPER = "#201E1D", "#EC3013", "#8A8886", "#D9D5D0", "#F6F4F0"
STEEL = ("#B9BDC2", "#8F949A", "#6A6F75")  # top, light side, dark side
CONCRETE = ("#D5D1CA", "#B4AFA6", "#8E8A82")
WATER = ("#9CC6DE", "#6FA6C4", "#4D86A6")
RUST = ("#F29B8B", "#EC3013", "#A32109")
DARK = ("#5E6268", "#3E4146", "#26282B")
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


def ground_plane(ax, ox, oy, s, size=8.0, shade="#E7E3DD"):
    p = [
        iso(0, 0, 0, ox, oy, s),
        iso(size, 0, 0, ox, oy, s),
        iso(size, size, 0, ox, oy, s),
        iso(0, size, 0, ox, oy, s),
    ]
    ax.add_patch(Polygon(p, closed=True, fc=shade, ec=GREY, lw=0.6, zorder=1))
    for k in np.arange(0, size + 0.01, 1.0):
        a, b = iso(k, 0, 0, ox, oy, s), iso(k, size, 0, ox, oy, s)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#D3CFC8", lw=0.4, zorder=1.1)
        a, b = iso(0, k, 0, ox, oy, s), iso(size, k, 0, ox, oy, s)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#D3CFC8", lw=0.4, zorder=1.1)


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


def hero_bess():
    fig, ax = sheet(
        "Battery energy storage container",
        "2 MWh LFP, HVAC on the roof, MV transformer",
        "T01",
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 9)
        box(
            ax,
            1,
            2,
            0,
            6.1,
            2.4,
            2.9,
            shades=("#DDDAD4", "#C6C1B9", "#A29D95"),
            ox=ox,
            oy=oy,
            s=s,
        )  # container
        for k in range(5):  # door panels on the long face
            a, b = (
                iso(1.35 + k * 1.15, 2, 0.15, ox, oy, s),
                iso(1.35 + k * 1.15, 2, 2.75, ox, oy, s),
            )
            ax.plot([a[0], b[0]], [a[1], b[1]], color=GREY, lw=0.6, zorder=3.2)
            p = [
                iso(1.4 + k * 1.15, 2, 0.3, ox, oy, s),
                iso(2.3 + k * 1.15, 2, 0.3, ox, oy, s),
                iso(2.3 + k * 1.15, 2, 2.6, ox, oy, s),
                iso(1.4 + k * 1.15, 2, 2.6, ox, oy, s),
            ]
            ax.add_patch(
                Polygon(p, closed=True, fc="#BBB6AE", ec=GREY, lw=0.4, zorder=3.2)
            )
        for k in range(3):  # HVAC units on the roof
            box(
                ax,
                1.6 + k * 1.9,
                2.5,
                2.9,
                1.2,
                1.4,
                0.7,
                shades=STEEL,
                ox=ox,
                oy=oy,
                s=s,
                zorder=3.5,
            )
            c = iso(2.2 + k * 1.9, 3.2, 3.6, ox, oy, s)
            ax.add_patch(
                Ellipse(c, 0.55 * s, 0.3 * s, fc=DARK[1], ec=INK, lw=0.5, zorder=3.7)
            )
        box(ax, 8.0, 2.4, 0, 1.4, 1.6, 1.7, shades=DARK, ox=ox, oy=oy, s=s)  # transformer
        for k in range(6):  # radiator fins
            a = iso(8.0, 2.45 + k * 0.25, 0.1, ox, oy, s)
            b = iso(8.0, 2.45 + k * 0.25, 1.6, ox, oy, s)
            ax.plot([a[0], b[0]], [a[1], b[1]], color="#1A1B1D", lw=1.8, zorder=3.6)
        for k in range(3):  # bushings
            c = iso(8.3 + k * 0.4, 3.2, 1.9, ox, oy, s)
            ax.add_patch(
                Ellipse(c, 0.18 * s, 0.1 * s, fc=STEEL[0], ec=INK, lw=0.4, zorder=3.8)
            )
            ax.plot([c[0], c[0]], [c[1] - 0.2 * s, c[1]], color=INK, lw=1.2, zorder=3.7)
        pipe(
            ax,
            [(7.1, 3.2, 0.4), (8.0, 3.2, 0.4)],
            width=4,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )  # DC/AC cable
        pipe(
            ax,
            [(9.4, 3.2, 1.5), (10.8, 3.2, 3.6)],
            width=2.5,
            color=INK,
            ox=ox,
            oy=oy,
            s=s,
        )  # line to the grid
        box(ax, 10.8, 3.0, 0, 0.3, 0.3, 3.8, shades=STEEL, ox=ox, oy=oy, s=s)  # pole
        callout(ax, iso(4, 2, 2.9, ox, oy, s), "battery racks: 2 MWh LFP", (0.6, 1.3))
        callout(ax, iso(8.7, 2.4, 1.7, ox, oy, s), "MV transformer", (0.9, 0.9))
        callout(
            ax, iso(2.2, 3.2, 3.6, ox, oy, s), "HVAC: the heat has to leave", (-3.2, 1.0)
        )

    fit_scene(ax, scene)
    save(fig, "t01_hero.png")


def hero_feeder():
    fig, ax = sheet(
        "DC distribution feeder",
        "Substation, 2 km cable, a converter and its loads",
        "T02",
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 10)
        box(
            ax, 0.8, 1.0, 0, 2.2, 1.6, 1.9, shades=DARK, ox=ox, oy=oy, s=s
        )  # substation transformer
        for k in range(8):
            a, b = (
                iso(0.8, 1.05 + k * 0.19, 0.1, ox, oy, s),
                iso(0.8, 1.05 + k * 0.19, 1.8, ox, oy, s),
            )
            ax.plot([a[0], b[0]], [a[1], b[1]], color="#1A1B1D", lw=1.6, zorder=3.6)
        box(ax, 3.4, 1.2, 0, 1.0, 1.2, 1.4, shades=STEEL, ox=ox, oy=oy, s=s)  # switchgear
        pipe(
            ax,
            [(3.0, 1.8, 0.4), (3.4, 1.8, 0.4)],
            width=3,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )
        pipe(
            ax,
            [(4.4, 1.8, 0.25), (6.5, 1.8, 0.25), (6.5, 5.5, 0.25), (8.8, 5.5, 0.25)],
            width=3.2,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )
        for k, (bx, by) in enumerate(
            [(6.9, 6.0), (8.3, 6.0), (5.4, 3.2)]
        ):  # buildings with loads
            box(
                ax, bx, by, 0, 1.0, 1.0, 1.2 + 0.3 * k, shades=CONCRETE, ox=ox, oy=oy, s=s
            )
        pipe(
            ax,
            [(6.5, 3.7, 0.25), (5.4, 3.7, 0.25)],
            width=2.4,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )
        box(
            ax, 8.9, 5.3, 0, 0.7, 0.6, 0.9, shades=DARK, ox=ox, oy=oy, s=s
        )  # DC/DC converter cabinet
        callout(
            ax, iso(1.9, 1.0, 1.9, ox, oy, s), "11 kV / 750 V substation", (-2.6, 1.1)
        )
        callout(
            ax,
            iso(6.5, 3.5, 0.25, ox, oy, s),
            "2 km cable: resistance and inductance",
            (1.4, -0.9),
        )
        callout(ax, iso(9.2, 5.3, 0.9, ox, oy, s), "DC/DC converter to 48 V", (0.8, 1.2))

    fit_scene(ax, scene)
    save(fig, "t02_hero.png")


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


def hero_suspension():
    fig, ax = sheet(
        "Vehicle suspension", "Quarter-car: body, suspension, wheel, tyre and road", "T03"
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 8)
        # road bump profile on the ground
        xs = np.linspace(0.5, 7.5, 80)
        bump = 0.25 * np.exp(-((xs - 4.0) ** 2) / 0.4)
        road = [iso(x, 2.2, b, ox, oy, s) for x, b in zip(xs, bump, strict=True)] + [
            iso(x, 3.2, b, ox, oy, s) for x, b in zip(xs[::-1], bump[::-1], strict=True)
        ]
        ax.add_patch(Polygon(road, closed=True, fc=DARK[1], ec=INK, lw=0.5, zorder=1.5))
        # body
        box(ax, 1.5, 2.0, 2.2, 4.6, 1.5, 0.9, shades=RUST, ox=ox, oy=oy, s=s, zorder=5)
        box(
            ax,
            2.6,
            2.1,
            3.1,
            2.2,
            1.3,
            0.7,
            shades=("#DCE6EC", "#B8CBD6", "#8FA6B3"),
            ox=ox,
            oy=oy,
            s=s,
            zorder=5.2,
        )  # cabin
        # wheels and springs
        for wx in (2.2, 5.4):
            c = iso(wx, 2.3, 0.75, ox, oy, s)
            wheel(ax, c[0], c[1], 0.75 * s, ox, oy, s, zorder=4)
            top, bot = iso(wx, 2.2, 2.2, ox, oy, s), iso(wx, 2.2, 1.2, ox, oy, s)
            zigzag(ax, bot, top, n=6, amp=0.1, color=INK, lw=1.6, zorder=4.5)
            d0, d1 = (
                iso(wx + 0.35, 2.2, 1.2, ox, oy, s),
                iso(wx + 0.35, 2.2, 2.2, ox, oy, s),
            )
            ax.plot(
                [d0[0], d1[0]],
                [d0[1], d1[1]],
                color=INK,
                lw=4.5,
                zorder=4.4,
                solid_capstyle="butt",
            )
            ax.plot([d0[0], d1[0]], [d0[1], d1[1]], color=STEEL[0], lw=2.2, zorder=4.5)
        callout(
            ax, iso(4, 2.0, 3.1, ox, oy, s), "sprung mass: 1/4 of the body", (1.6, 1.0)
        )
        callout(ax, iso(2.2, 2.2, 1.7, ox, oy, s), "spring and damper", (-3.0, 0.6))
        callout(
            ax, iso(4.0, 2.7, 0.25, ox, oy, s), "road profile: the input", (1.2, -1.1)
        )

    fit_scene(ax, scene)
    save(fig, "t03_hero.png")


def hero_turbine():
    fig, ax = sheet(
        "Wind turbine drivetrain", "Rotor, main shaft, gearbox, generator", "T04"
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 8)
        # tower
        cylinder(
            ax,
            3.0,
            3.0,
            0,
            0.5,
            6.3,
            shades=("#E6E6E6", "#CFCFCF", "#9F9F9F"),
            ox=ox,
            oy=oy,
            s=s,
        )
        # nacelle (cutaway): outer shell as light box, drivetrain inside
        box(
            ax,
            1.6,
            2.55,
            6.3,
            3.6,
            0.9,
            0.8,
            shades=("#EEEEEE", "#D5D5D5", "#B3B3B3"),
            ox=ox,
            oy=oy,
            s=s,
            zorder=5,
        )
        # hub and blades
        hub = iso(1.5, 3.0, 6.75, ox, oy, s)
        ax.add_patch(Circle(hub, 0.32 * s, fc=STEEL[0], ec=INK, lw=0.7, zorder=6))
        for ang in (90, 210, 330):
            a = math.radians(ang)
            tip = (hub[0] + 3.3 * s * math.cos(a), hub[1] + 3.3 * s * math.sin(a))
            w = 0.22 * s
            n = (-math.sin(a) * w, math.cos(a) * w)
            poly = [
                (hub[0] + n[0], hub[1] + n[1]),
                (hub[0] - n[0], hub[1] - n[1]),
                (tip[0] - n[0] * 0.15, tip[1] - n[1] * 0.15),
                tip,
            ]
            ax.add_patch(
                Polygon(poly, closed=True, fc="#F2F2F2", ec=INK, lw=0.7, zorder=5.9)
            )
        # drivetrain drawn as an exploded strip in front
        y0 = 1.9
        pipe(
            ax,
            [(7.0, y0, 1.2), (8.6, y0, 1.2)],
            width=5,
            color=STEEL[1],
            ox=ox,
            oy=oy,
            s=s,
        )  # main shaft
        box(
            ax, 8.6, y0 - 0.5, 0.5, 1.2, 1.0, 1.4, shades=DARK, ox=ox, oy=oy, s=s
        )  # gearbox
        pipe(
            ax,
            [(9.8, y0, 1.2), (10.6, y0, 1.2)],
            width=3.2,
            color=STEEL[1],
            ox=ox,
            oy=oy,
            s=s,
        )  # high-speed shaft
        # generator as a horizontal cylinder: approximate with a box
        box(
            ax,
            10.6,
            y0 - 0.45,
            0.6,
            1.5,
            0.9,
            1.2,
            shades=("#D7DEE4", "#A9B5BE", "#7E8A93"),
            ox=ox,
            oy=oy,
            s=s,
        )
        callout(ax, iso(7.6, y0, 1.2, ox, oy, s), "main shaft: torsion", (-0.9, -0.9))
        callout(ax, iso(9.2, y0, 1.9, ox, oy, s), "gearbox 1:90", (0.0, 1.1))
        callout(
            ax, iso(11.3, y0, 1.8, ox, oy, s), "generator held at grid speed", (0.4, 1.2)
        )
        callout(
            ax,
            iso(1.5, 3.0, 8.3, ox, oy, s),
            "aerodynamic torque: the input",
            (-3.4, 0.4),
        )

    fit_scene(ax, scene)
    save(fig, "t04_hero.png")


def hero_water():
    fig, ax = sheet(
        "Municipal water supply",
        "Reservoir, pump station, rising main, elevated tank",
        "T05",
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 11)
        cylinder(
            ax, 2.0, 2.0, 0, 1.5, 1.6, shades=CONCRETE, ox=ox, oy=oy, s=s
        )  # reservoir
        water_surface(ax, 2.0, 2.0, 1.45, 1.42, ox, oy, s)
        box(
            ax,
            4.2,
            1.6,
            0,
            1.6,
            1.3,
            1.1,
            shades=("#E4DED4", "#CFC7BA", "#A89F91"),
            ox=ox,
            oy=oy,
            s=s,
        )  # pump house
        box(
            ax, 4.1, 1.5, 1.1, 1.8, 1.5, 0.35, shades=RUST, ox=ox, oy=oy, s=s, zorder=3.6
        )  # roof
        pipe(
            ax,
            [(3.5, 2.0, 0.3), (4.2, 2.0, 0.3)],
            width=5,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        pipe(
            ax,
            [
                (5.8, 2.2, 0.3),
                (7.2, 2.2, 0.3),
                (7.2, 6.2, 0.3),
                (9.0, 6.2, 0.3),
                (9.0, 6.2, 4.2),
            ],
            width=5,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        # elevated tank on a tower
        for lx, ly in ((8.6, 5.8), (9.4, 5.8), (8.6, 6.6), (9.4, 6.6)):
            box(
                ax,
                lx,
                ly,
                0,
                0.15,
                0.15,
                4.2,
                shades=STEEL,
                ox=ox,
                oy=oy,
                s=s,
                zorder=3.4,
            )
        cylinder(
            ax,
            9.0,
            6.2,
            4.2,
            1.1,
            1.3,
            shades=("#E8EEF2", "#BCC8D0", "#8C9BA6"),
            ox=ox,
            oy=oy,
            s=s,
            zorder=4,
        )
        # consumers
        for bx, by, h in ((4.0, 6.5, 0.8), (5.2, 7.4, 1.0), (3.2, 7.8, 0.7)):
            box(ax, bx, by, 0, 0.8, 0.8, h, shades=CONCRETE, ox=ox, oy=oy, s=s)
        pipe(
            ax,
            [(8.6, 6.2, 0.3), (5.6, 6.9, 0.3), (4.4, 6.9, 0.3)],
            width=3,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        callout(ax, iso(2.0, 2.0, 1.6, ox, oy, s), "raw-water reservoir", (-2.2, 1.0))
        callout(
            ax, iso(5.0, 1.6, 1.4, ox, oy, s), "pump station: pump, filter", (0.3, -1.3)
        )
        callout(ax, iso(9.0, 6.2, 5.5, ox, oy, s), "elevated tank, 30 m head", (0.8, 0.6))
        callout(
            ax,
            iso(7.2, 4.2, 0.3, ox, oy, s),
            "rising main: friction and inertia",
            (1.6, -0.9),
        )

    fit_scene(ax, scene)
    save(fig, "t05_hero.png")


def hero_wastewater():
    fig, ax = sheet(
        "Wastewater disinfection",
        "Chlorine contact tank: dosing, contact basins, outfall",
        "T06",
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 10)
        # contact basin: serpentine of 4 channels (open boxes)
        for k in range(4):
            box(
                ax,
                2.0,
                1.5 + k * 1.1,
                0,
                5.0,
                0.95,
                1.0,
                shades=CONCRETE,
                ox=ox,
                oy=oy,
                s=s,
            )
            top = [
                iso(2.1, 1.55 + k * 1.1, 0.85, ox, oy, s),
                iso(6.9, 1.55 + k * 1.1, 0.85, ox, oy, s),
                iso(6.9, 2.4 + k * 1.1, 0.85, ox, oy, s),
                iso(2.1, 2.4 + k * 1.1, 0.85, ox, oy, s),
            ]
            ax.add_patch(
                Polygon(top, closed=True, fc=WATER[0], ec=WATER[2], lw=0.5, zorder=3.3)
            )
        # dosing: chlorine tank + metering pump
        cylinder(
            ax,
            0.6,
            1.2,
            0,
            0.5,
            1.4,
            shades=("#F3E6B8", "#D9C77E", "#A8944F"),
            ox=ox,
            oy=oy,
            s=s,
        )
        box(ax, 0.3, 2.2, 0, 0.5, 0.5, 0.5, shades=DARK, ox=ox, oy=oy, s=s)
        pipe(
            ax,
            [(0.6, 1.2, 1.5), (0.6, 2.45, 1.5), (0.6, 2.45, 0.6), (2.0, 1.9, 0.6)],
            width=2.2,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )
        # inlet and outfall channels
        pipe(
            ax,
            [(0.0, 1.9, 0.5), (2.0, 1.9, 0.5)],
            width=5,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        pipe(
            ax,
            [(7.0, 5.3, 0.5), (9.4, 5.3, 0.5), (9.4, 5.3, -0.2)],
            width=5,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        callout(ax, iso(0.6, 1.2, 1.5, ox, oy, s), "hypochlorite dosing", (-2.4, 0.9))
        callout(
            ax,
            iso(4.5, 1.5, 1.0, ox, oy, s),
            "serpentine contact tank: near plug flow",
            (1.2, -1.0),
        )
        callout(
            ax,
            iso(9.4, 5.3, 0.5, ox, oy, s),
            "outfall: residual chlorine limit",
            (0.6, 1.0),
        )

    fit_scene(ax, scene)
    save(fig, "t06_hero.png")


def hero_building():
    fig, ax = sheet(
        "Heated building", "Electric boiler, envelope, ventilation, weather", "T07"
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 9)
        box(
            ax,
            2.0,
            2.0,
            0,
            4.0,
            3.0,
            2.6,
            shades=("#EDE5D6", "#D6CBB6", "#B3A68F"),
            ox=ox,
            oy=oy,
            s=s,
        )
        # roof: two slopes
        r1 = [
            iso(1.8, 1.8, 2.6, ox, oy, s),
            iso(6.2, 1.8, 2.6, ox, oy, s),
            iso(6.2, 3.5, 3.9, ox, oy, s),
            iso(1.8, 3.5, 3.9, ox, oy, s),
        ]
        r2 = [
            iso(6.2, 1.8, 2.6, ox, oy, s),
            iso(6.2, 5.2, 2.6, ox, oy, s),
            iso(6.2, 3.5, 3.9, ox, oy, s),
        ]
        ax.add_patch(Polygon(r1, closed=True, fc=RUST[1], ec=INK, lw=0.6, zorder=4))
        ax.add_patch(Polygon(r2, closed=True, fc=RUST[2], ec=INK, lw=0.6, zorder=4))
        for k in range(3):  # windows
            p = [
                iso(2.6 + k * 1.2, 2.0, 0.9, ox, oy, s),
                iso(3.3 + k * 1.2, 2.0, 0.9, ox, oy, s),
                iso(3.3 + k * 1.2, 2.0, 1.9, ox, oy, s),
                iso(2.6 + k * 1.2, 2.0, 1.9, ox, oy, s),
            ]
            ax.add_patch(
                Polygon(p, closed=True, fc="#C9DCE8", ec=INK, lw=0.5, zorder=3.5)
            )
        box(
            ax, 6.4, 2.2, 0, 0.9, 0.8, 1.3, shades=STEEL, ox=ox, oy=oy, s=s
        )  # boiler outside wall
        pipe(
            ax,
            [(6.4, 2.6, 0.9), (6.0, 2.6, 0.9)],
            width=3,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )
        pipe(
            ax,
            [(6.4, 2.9, 0.4), (6.0, 2.9, 0.4)],
            width=3,
            color=WATER[1],
            ox=ox,
            oy=oy,
            s=s,
        )
        box(
            ax, 7.6, 2.0, 0, 0.4, 0.4, 2.2, shades=DARK, ox=ox, oy=oy, s=s
        )  # weather mast
        callout(
            ax,
            iso(4.0, 2.0, 2.0, ox, oy, s),
            "envelope: walls, windows, air change",
            (-3.6, 1.4),
        )
        callout(
            ax,
            iso(6.85, 2.2, 1.3, ox, oy, s),
            "electric boiler: losses become heat",
            (0.9, 1.0),
        )
        callout(
            ax,
            iso(7.8, 2.0, 2.2, ox, oy, s),
            "outdoor temperature: the input",
            (0.6, 0.0),
        )

    fit_scene(ax, scene)
    save(fig, "t07_hero.png")


def hero_pumpdrive():
    fig, ax = sheet(
        "Motor-driven pump set", "DC machine, coupling, positive-displacement pump", "T08"
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 8)
        box(ax, 1.0, 2.0, 0, 6.0, 1.4, 0.3, shades=STEEL, ox=ox, oy=oy, s=s)  # baseplate
        box(
            ax,
            1.4,
            2.25,
            0.3,
            2.4,
            0.9,
            1.1,
            shades=("#D7DEE4", "#A9B5BE", "#7E8A93"),
            ox=ox,
            oy=oy,
            s=s,
        )  # motor
        for k in range(6):  # cooling fins
            a, b = (
                iso(1.5 + k * 0.38, 2.25, 0.4, ox, oy, s),
                iso(1.5 + k * 0.38, 2.25, 1.3, ox, oy, s),
            )
            ax.plot([a[0], b[0]], [a[1], b[1]], color="#5F6B74", lw=1.2, zorder=3.4)
        box(
            ax, 2.2, 2.45, 1.4, 0.8, 0.5, 0.35, shades=DARK, ox=ox, oy=oy, s=s
        )  # terminal box
        pipe(
            ax,
            [(3.8, 2.7, 0.85), (4.6, 2.7, 0.85)],
            width=4,
            color=STEEL[1],
            ox=ox,
            oy=oy,
            s=s,
        )  # coupling/shaft
        box(ax, 4.6, 2.3, 0.3, 1.6, 0.8, 1.0, shades=RUST, ox=ox, oy=oy, s=s)  # pump
        pipe(
            ax,
            [(5.4, 3.1, 1.3), (5.4, 3.1, 2.4), (5.4, 5.0, 2.4)],
            width=5,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )  # discharge
        pipe(
            ax,
            [(6.2, 2.7, 0.7), (7.6, 2.7, 0.7)],
            width=5,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )  # suction
        pipe(
            ax,
            [(1.0, 2.6, 1.55), (2.2, 2.6, 1.55)],
            width=2,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )  # supply cable
        callout(
            ax, iso(2.6, 2.25, 1.4, ox, oy, s), "DC machine: a transformer", (-2.8, 1.3)
        )
        callout(ax, iso(5.4, 2.3, 1.3, ox, oy, s), "gear pump: a gyrator", (1.4, 1.0))
        callout(ax, iso(5.4, 4.2, 2.4, ox, oy, s), "discharge to the tank", (0.8, 0.5))

    fit_scene(ax, scene)
    save(fig, "t08_hero.png")


def hero_flywheel():
    fig, ax = sheet(
        "Flywheel energy storage",
        "Steel rotor in a vacuum housing, motor-generator, converter",
        "T09",
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 8)
        cylinder(
            ax,
            3.0,
            3.0,
            0,
            1.6,
            3.0,
            shades=("#E3E6E9", "#B9BFC5", "#858C93"),
            ox=ox,
            oy=oy,
            s=s,
        )  # housing
        # cutaway: rotor disc visible as a dark ellipse on top
        top = iso(3.0, 3.0, 3.0, ox, oy, s)
        ax.add_patch(
            Ellipse(top, 2.4 * s, 1.38 * s, fc="#4A4E53", ec=INK, lw=0.6, zorder=4.2)
        )
        ax.add_patch(
            Ellipse(top, 0.5 * s, 0.29 * s, fc=STEEL[0], ec=INK, lw=0.5, zorder=4.3)
        )
        box(
            ax, 5.6, 2.4, 0, 1.2, 1.2, 1.9, shades=DARK, ox=ox, oy=oy, s=s
        )  # converter cabinet
        pipe(
            ax,
            [(4.6, 3.0, 0.5), (5.6, 3.0, 0.5)],
            width=3,
            color=RUST[1],
            ox=ox,
            oy=oy,
            s=s,
        )
        pipe(
            ax,
            [(6.8, 3.0, 0.5), (8.2, 3.0, 0.5), (8.2, 3.0, 2.8)],
            width=2.5,
            color=INK,
            ox=ox,
            oy=oy,
            s=s,
        )
        box(ax, 8.2, 2.85, 0, 0.3, 0.3, 3.0, shades=STEEL, ox=ox, oy=oy, s=s)
        callout(
            ax,
            iso(3.0, 3.0, 3.0, ox, oy, s),
            "rotor: 36 000 rpm, energy ½ J ω²",
            (-3.6, 1.2),
        )
        callout(
            ax, iso(6.2, 2.4, 1.9, ox, oy, s), "motor-generator and converter", (0.9, 1.0)
        )
        callout(
            ax,
            iso(4.6, 3.0, 0.5, ox, oy, s),
            "bearing losses: self-discharge",
            (-1.0, -1.4),
        )

    fit_scene(ax, scene)
    save(fig, "t09_hero.png")


def hero_twin():
    fig, ax = sheet(
        "From a model to a digital twin",
        "Elevated tank with level sensor, fitted, forecast and audited",
        "T10",
    )

    def scene(ax, ox, oy, s):
        ground_plane(ax, ox, oy, s, 9)
        for lx, ly in ((2.6, 2.6), (3.4, 2.6), (2.6, 3.4), (3.4, 3.4)):
            box(
                ax,
                lx,
                ly,
                0,
                0.15,
                0.15,
                3.8,
                shades=STEEL,
                ox=ox,
                oy=oy,
                s=s,
                zorder=3.4,
            )
        cylinder(
            ax,
            3.0,
            3.0,
            3.8,
            1.1,
            1.3,
            shades=("#E8EEF2", "#BCC8D0", "#8C9BA6"),
            ox=ox,
            oy=oy,
            s=s,
            zorder=4,
        )
        box(
            ax, 4.0, 3.3, 4.2, 0.25, 0.25, 0.5, shades=RUST, ox=ox, oy=oy, s=s, zorder=5
        )  # level transmitter
        pipe(
            ax,
            [(3.0, 3.0, 0.3), (3.0, 3.0, 3.8)],
            width=4,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        pipe(
            ax,
            [(3.0, 3.0, 0.3), (6.0, 3.0, 0.3)],
            width=4,
            color=WATER[2],
            ox=ox,
            oy=oy,
            s=s,
        )
        # the dashboard: a panel with a chart
        px, py, pw, ph = 9.6, 1.9, 5.2, 3.6
        ax.add_patch(
            FancyBboxPatch(
                (px, py),
                pw,
                ph,
                boxstyle="round,pad=0.05,rounding_size=0.12",
                fc="#FFFFFF",
                ec=INK,
                lw=1.0,
                zorder=6,
            )
        )
        t = np.linspace(0, 1, 120)
        y = 1.0 + 0.6 * np.sin(2 * np.pi * t * 1.5) * np.exp(-t)
        band = 0.15 + 0.5 * t
        xs = px + 0.4 + t * (pw - 0.8)
        ys = py + 0.6 + y * 1.3
        cut = 80
        ax.fill_between(
            xs[cut:],
            ys[cut:] - band[cut:],
            ys[cut:] + band[cut:],
            color="#FBD9D2",
            zorder=6.1,
        )
        ax.plot(xs[:cut], ys[:cut], color=INK, lw=1.6, zorder=6.2)
        ax.plot(xs[cut:], ys[cut:], color=RED, lw=1.6, ls="--", zorder=6.2)
        ax.plot(
            [px + 0.4, px + pw - 0.4],
            [py + 0.6, py + 0.6],
            color=GREY,
            lw=0.6,
            zorder=6.1,
        )
        ax.text(
            px + 0.4,
            py + ph - 0.45,
            "level  ·  measured, forecast, 90 % range",
            fontsize=9,
            color=INK,
            zorder=6.3,
        )
        ax.text(
            px + 0.4,
            py + 0.2,
            "coverage audit: 91 % delivered at the 90 % level",
            fontsize=8,
            color=GREY,
            zorder=6.3,
        )
        callout(ax, iso(4.1, 3.3, 4.7, ox, oy, s), "LT: the measurement", (0.7, 0.9))

    fit_scene(ax, scene)
    save(fig, "t10_hero.png")


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
        ground_plane(ax, ox, oy, s, 10, shade="#ECE8E2")
        box(
            ax,
            0.5,
            1.0,
            0,
            3.6,
            1.5,
            1.8,
            shades=("#DDDAD4", "#C6C1B9", "#A29D95"),
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
            shades=("#E8EEF2", "#BCC8D0", "#8C9BA6"),
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
            shades=("#E6E6E6", "#CFCFCF", "#9F9F9F"),
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
                    fc="#F2F2F2",
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
    ax.add_patch(Rectangle((x, y), w, h, fc="#E9E6E1", ec=INK, lw=1.6, zorder=5))
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
    equipment(ax, 9.2, 4.6, 2.0, 1.1, "RACK", "cell mass, 1.2 MJ/K", fc="#F3F0EB")
    equipment(ax, 12.2, 4.6, 2.0, 1.1, "AIR", "container air", fc="#F3F0EB")
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
    ax.add_patch(Circle((2.2, y), 0.75, fc="#E9E6E1", ec=INK, lw=1.6, zorder=5))
    note(ax, 2.2, y, "J_r\nrotor", ha="center", fontsize=8.5)
    line(ax, [(0.6, y), (1.45, y)], arrow=True, color=RED)
    note(ax, 0.5, y + 0.45, "T_aero (input)", fontsize=8)
    line(ax, [(2.95, y), (3.6, y)])
    zigzag(ax, (3.6, y), (5.4, y), n=7, amp=0.15, color=INK, lw=1.5)
    note(ax, 4.5, y + 0.45, "k_shaft  torsion", ha="center", fontsize=8.5)
    line(ax, [(5.4, y), (6.2, y)])
    equipment(ax, 6.2, y - 0.6, 1.6, 1.2, "GEAR", "1 : 90", fc="#F3F0EB")
    line(ax, [(7.8, y), (9.0, y)])
    ax.add_patch(Circle((9.5, y), 0.5, fc="#E9E6E1", ec=INK, lw=1.6, zorder=5))
    note(ax, 9.5, y, "J_g", ha="center", fontsize=8.5)
    line(ax, [(10.0, y), (11.0, y)])
    equipment(ax, 11.0, y - 0.6, 2.0, 1.2, "GEN", "held at ω_grid", fc="#F3F0EB")
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
    equipment(ax, 13.4, 5.2, 1.6, 0.8, "DEMAND", "q(t) input", fc="#F3F0EB")
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
    equipment(ax, 13.6, 3.2, 1.6, 0.8, "OUTFALL", "Cl₂ ≥ 0.2 mg/L", fc="#F3F0EB")
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
    equipment(ax, 6.0, y - 0.3, 1.8, 1.2, "WATER", "C_w  boiler loop", fc="#F3F0EB")
    line(ax, [(7.8, y + 0.3), (9.2, y + 0.3)])
    note(ax, 8.5, y + 0.6, "radiators hA", fontsize=8, ha="center")
    equipment(ax, 9.2, y - 0.3, 1.8, 1.2, "ROOM", "C_air", fc="#F3F0EB")
    line(ax, [(11.0, y + 0.3), (12.4, y + 0.3)])
    note(ax, 11.7, y + 0.6, "walls R_wall", fontsize=8, ha="center")
    line(ax, [(10.1, y - 0.3), (10.1, y - 1.6), (12.4, y - 1.6)])
    note(ax, 11.25, y - 1.3, "ventilation ṁ c_p", fontsize=8, ha="center")
    equipment(ax, 12.4, y - 1.9, 2.0, 2.5, "OUTDOOR", "T_out(t) input", fc="#F3F0EB")
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
    ax.add_patch(Circle((7.9, y), 0.5, fc="#E9E6E1", ec=INK, lw=1.6, zorder=5))
    note(ax, 7.9, y, "J", ha="center", fontsize=9)
    line(ax, [(8.4, y), (9.2, y)], lw=3.0)
    equipment(ax, 9.2, y - 0.6, 1.6, 1.2, "PUMP", "D = 20 cm³/rev", fc="#F3F0EB")
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
    equipment(ax, 4.8, y - 0.6, 2.0, 1.2, "M / G", "gyrator  τ = k i", fc="#F3F0EB")
    line(ax, [(5.8, y - 0.6), (5.8, y - 1.6), (1.6, y - 1.6), (1.6, y - 1.16)])
    ground_sym(ax, 3.7, y - 1.6)
    line(ax, [(6.8, y), (8.0, y)], lw=3.0)
    ax.add_patch(Circle((8.9, y), 0.9, fc="#D8DADD", ec=INK, lw=1.8, zorder=5))
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
        equipment(ax, x, 5.2, 1.9, 1.1, l1, l2, fc="#F3F0EB")
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
        fc="#FBD9D2",
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
