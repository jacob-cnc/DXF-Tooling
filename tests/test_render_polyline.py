"""Regression: a joined LWPOLYLINE carrying arc BULGES must render as smooth
arcs, not faceted straight chords between vertices. draw_dxf previously read
only the xy points and drew line segments, so a joined arc-chain looked
faceted. It now expands the polyline via virtual_entities() (which applies the
bulges) and draws each sub-arc as a matplotlib Arc.

Runnable:
    <real python> -m pytest tests/test_render_polyline.py
    <real python> tests/test_render_polyline.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import matplotlib          # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.patches import Arc        # noqa: E402
import ezdxf                              # noqa: E402

from dxfclean import draw_dxf             # noqa: E402


def _tmp(name):
    d = os.environ.get("KIROCREW_SCRATCH") or os.environ.get("TMPDIR") or "."
    return os.path.join(d, name)


def test_bulged_polyline_renders_as_arcs():
    doc = ezdxf.new()
    msp = doc.modelspace()
    # Two 90-degree arc bulges (tan(90/4)=0.4142) + one straight segment.
    msp.add_lwpolyline(
        [(0, 0, 0, 0, 0.4142),      # arc to next
         (10, 10, 0, 0, 0.4142),    # arc to next
         (20, 0, 0, 0, 0.0),        # straight to next
         (30, 0, 0, 0, 0.0)],
        format="xyseb")
    path = _tmp("bulge_poly.dxf")
    doc.saveas(path)

    fig = plt.figure()
    ax = fig.add_subplot(111)
    draw_dxf(ax, path)
    n_arcs = sum(1 for p in ax.patches if isinstance(p, Arc))
    assert n_arcs >= 2, \
        "bulged polyline should render >=2 Arc patches, got %d (faceted?)" \
        % n_arcs
    plt.close(fig)


def test_straight_polyline_still_renders():
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)])   # no bulges
    path = _tmp("straight_poly.dxf")
    doc.saveas(path)
    fig = plt.figure()
    ax = fig.add_subplot(111)
    draw_dxf(ax, path)        # must not raise; lines drawn
    assert len(ax.lines) >= 1 or len(ax.patches) >= 1
    plt.close(fig)


if __name__ == "__main__":
    test_bulged_polyline_renders_as_arcs()
    test_straight_polyline_still_renders()
    print("render polyline: OK")
