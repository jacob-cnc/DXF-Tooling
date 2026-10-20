"""Regression test for curvature-adaptive SPLINE flattening.

Runnable two ways:
    <real python> -m pytest tests/test_spline.py
    <real python> tests/test_spline.py

Correctness is EMPIRICAL (no magic segment count):
  * every flattened vertex lies within a bounded chord-error of the TRUE
    spline curve (fidelity -- "true to CAD intention"),
  * adaptive sampling uses far FEWER segments than the old fixed 0.01 flatten
    on a large curve (the spline-vertex-flood fix),
  * sampling scales with curve SIZE (a 10x-larger copy does not blow up the
    count proportionally the way a fixed absolute tolerance would).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import ezdxf  # noqa: E402

import dxfclean.core as core  # noqa: E402

FIT = [(0, 0), (50, 40), (100, -30), (150, 35), (200, 0)]
SPAN = 200.0


def _clean_segments(fit):
    doc = ezdxf.new("R2010")
    doc.modelspace().add_spline(fit)
    nd, rep = core.clean_doc(doc)
    segs = [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))
            for e in nd.modelspace() if e.dxftype() == "LINE"]
    return doc, segs, rep


def _pt_seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def test_fidelity_within_tolerance():
    """Every point on the true curve is within the chord tolerance of the
    flattened polyline. Tolerance is ~_SPLINE_REL_TOL of the span; allow a
    small multiple for the recursive-subdivision slack."""
    doc, segs, rep = _clean_segments(FIT)
    assert rep.splines_converted == 1
    assert len(segs) >= 2
    sp = doc.modelspace()[0]
    truth = [(p.x, p.y) for p in sp.flattening(0.005)]
    worst = max(min(_pt_seg_dist(tp, a, b) for (a, b) in segs) for tp in truth)
    budget = core._SPLINE_REL_TOL * SPAN * 3.0   # 0.1% * 3 slack
    assert worst <= budget, \
        "curve deviation %.4f exceeds budget %.4f" % (worst, budget)


def test_fewer_segments_than_fixed_flatten():
    """Adaptive sampling beats the old fixed 0.01 tolerance on a large curve."""
    _doc, adaptive, _rep = _clean_segments(FIT)

    orig = core._spline_to_lines

    def fixed(spline, report):
        try:
            pts = [(p.x, p.y) for p in spline.flattening(0.01)]
        except Exception:
            return []
        out = []
        for k in range(len(pts) - 1):
            p0, p1 = pts[k], pts[k + 1]
            if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 0:
                out.append((p0, p1))
        return out

    core._spline_to_lines = fixed
    try:
        _d2, fixed_segs, _r2 = _clean_segments(FIT)
    finally:
        core._spline_to_lines = orig

    assert len(adaptive) < len(fixed_segs), \
        "adaptive (%d) should use fewer segments than fixed 0.01 (%d)" \
        % (len(adaptive), len(fixed_segs))


def test_scales_with_size():
    """A 10x-larger copy of the same shape keeps a similar segment count --
    the tolerance is RELATIVE to size, not a fixed absolute grid."""
    _d1, small, _r1 = _clean_segments(FIT)
    big_fit = [(x * 10, y * 10) for (x, y) in FIT]
    _d2, big, _r2 = _clean_segments(big_fit)
    # within 2x of each other (would be ~10x with a fixed absolute tolerance)
    ratio = len(big) / max(len(small), 1)
    assert 0.5 <= ratio <= 2.0, \
        "segment count should scale with shape, not size (ratio %.2f)" % ratio


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("\nALL SPLINE TESTS PASSED")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
