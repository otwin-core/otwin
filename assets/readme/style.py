"""Shared look for the README images: the Otwin brand colours and a Helvetica-like face."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

INK, RED, GREY, LIGHT, PINK = "#201E1D", "#EC3013", "#8A8886", "#EAE7E7", "#FBD9D2"
for name in ("Liberation Sans", "FreeSans"):
    if any(name in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break


def clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GREY)
    ax.tick_params(colors=GREY, labelsize=9.5)


def header(fig, title, subtitle):
    fig.text(0.02, 0.92, title, fontsize=18, weight="bold", color=INK)
    fig.text(0.02, 0.855, subtitle, fontsize=11, color=GREY)
