"""Render a DXF to a PNG using ezdxf geometry + matplotlib.

Direct port of the proven ``render_dxf.py``: draws LINE, CIRCLE, ARC and
LWPOLYLINE/POLYLINE entities as plain black geometry on a white background.
SPLINE entities are skipped (this tooling targets arc/line/circle drawings;
cleanup converts splines to lines before rendering the "after" image).

The matplotlib backend is forced to ``Agg`` so this works headless and inside
a Tkinter app without opening extra windows.
"""
from __future__ import annotations

import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Arc as MplArc, Circle as MplCircle  # noqa: E402
import ezdxf  # noqa: E402

LW = 1.8
COLOR = "black"


def draw_dxf(ax, src: str) -> list:
    """Draw DXF ``src`` onto an existing matplotlib ``ax``.

    Shared by the PNG renderer and the interactive GUI canvas so both show
    byte-identical geometry. Returns a list of skipped entity type names.
    """
    doc = ezdxf.readfile(src)
    msp = doc.modelspace()
    skipped = []

    for e in msp:
        t = e.dxftype()
        if t == "LINE":
            s, en = e.dxf.start, e.dxf.end
            ax.plot([s.x, en.x], [s.y, en.y], color=COLOR, lw=LW,
                    solid_capstyle="round")
        elif t == "CIRCLE":
            c = e.dxf.center
            ax.add_patch(MplCircle((c.x, c.y), e.dxf.radius, fill=False,
                                   edgecolor=COLOR, lw=LW))
        elif t == "ARC":
            c = e.dxf.center
            d = e.dxf.radius * 2
            ax.add_patch(MplArc((c.x, c.y), d, d, angle=0,
                                theta1=e.dxf.start_angle,
                                theta2=e.dxf.end_angle,
                                edgecolor=COLOR, lw=LW))
        elif t in ("LWPOLYLINE", "POLYLINE"):
            pts = [(p[0], p[1]) for p in e.get_points("xy")] \
                if t == "LWPOLYLINE" \
                else [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            if getattr(e, "closed", False) or getattr(e.dxf, "flags", 0) & 1:
                pts = pts + pts[:1]
            xs, ys = zip(*pts)
            ax.plot(xs, ys, color=COLOR, lw=LW, solid_capstyle="round")
        else:
            skipped.append(t)

    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.margins(0.08)
    ax.set_axis_off()
    return skipped


def render(src: str, out: str) -> list:
    """Render DXF ``src`` to PNG ``out``. Returns a list of skipped type names."""
    fig, ax = plt.subplots(figsize=(10, 5), dpi=200)
    skipped = draw_dxf(ax, src)
    fig.patch.set_facecolor("white")
    fig.savefig(out, dpi=200, facecolor="white", bbox_inches="tight",
                pad_inches=0.15)
    plt.close(fig)
    return skipped


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = argv[1]
    if not os.path.isfile(src):
        print("ERROR: DXF not found:", src)
        return 1
    out = argv[2] if len(argv) > 2 else os.path.splitext(src)[0] + ".png"
    skipped = render(src, out)
    print("WROTE", out)
    if skipped:
        print("SKIPPED entity types:", dict(Counter(skipped)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
