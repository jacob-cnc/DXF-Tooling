"""Regression tests for the fix: arcs are SUBDIVIDED where another entity
crosses their interior, so a chainable/splittable endpoint exists there.
Previously arcs passed through whole and a fillet arc crossing a line had no
vertex at the crossing."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ezdxf

from dxfclean.core import (circle_circle_points, _split_arcs_at_intersections,
                           clean_doc)


def test_circle_circle_points_two_intersections():
    # Two unit circles centred at (0,0) and (1,0) cross at x=0.5, y=+-sqrt(3)/2.
    pts = circle_circle_points(0, 0, 1, 1, 0, 1)
    assert len(pts) == 2
    xs = sorted(round(p[0], 6) for p in pts)
    ys = sorted(round(abs(p[1]), 6) for p in pts)
    assert xs == [0.5, 0.5]
    assert abs(ys[0] - math.sqrt(3) / 2) < 1e-6
    print("PASS test_circle_circle_points_two_intersections")


def test_circle_circle_points_disjoint_and_contained():
    assert circle_circle_points(0, 0, 1, 10, 0, 1) == []     # far apart
    assert circle_circle_points(0, 0, 5, 0, 0, 1) == []      # one inside other
    assert circle_circle_points(0, 0, 1, 0, 0, 1) == []      # coincident
    print("PASS test_circle_circle_points_disjoint_and_contained")


def test_circle_circle_points_tangent():
    # Externally tangent unit circles touch at (1, 0).
    pts = circle_circle_points(0, 0, 1, 2, 0, 1)
    assert len(pts) == 1
    assert abs(pts[0][0] - 1.0) < 1e-6 and abs(pts[0][1]) < 1e-6
    print("PASS test_circle_circle_points_tangent")


def test_arc_split_by_line_through_interior():
    # A semicircle arc (centre origin, r=1, sweep 0->180, i.e. the top half)
    # crossed by a vertical line x=0 at its top point (0,1), which is the
    # sweep midpoint -> the arc must break into two 90-degree pieces.
    arcs = [(0.0, 0.0, 1.0, 0.0, 180.0, "0")]
    line = [((0.0, -2.0), (0.0, 2.0))]
    out, dropped = _split_arcs_at_intersections(arcs, line, [])
    assert len(out) == 2, "arc crossing a line must split in two, got %d" % len(out)
    # The two pieces together still cover 0..180 and meet at 90 deg.
    sweeps = sorted(round(((ea - sa) % 360.0), 3) for (_, _, _, sa, ea, _) in out)
    assert sweeps == [90.0, 90.0]
    print("PASS test_arc_split_by_line_through_interior")


def test_arc_not_split_when_line_only_touches_endpoint():
    # A line ending exactly at the arc's start point is NOT an interior cut.
    arcs = [(0.0, 0.0, 1.0, 0.0, 180.0, "0")]
    line = [((1.0, 0.0), (3.0, 0.0))]   # meets arc only at its (1,0) endpoint
    out, dropped = _split_arcs_at_intersections(arcs, line, [])
    assert len(out) == 1, "endpoint touch must NOT split the arc"
    print("PASS test_arc_not_split_when_line_only_touches_endpoint")


def test_end_to_end_arc_gets_endpoint_at_line_crossing():
    # Build a doc: a top-half arc and a vertical line crossing it at (0,1).
    # After clean, there must be an arc endpoint at (0,1).
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_arc((0, 0), 1.0, start_angle=0, end_angle=180)
    msp.add_line((0, -2), (0, 2))
    ndoc, _ = clean_doc(doc)
    arc_pts = []
    for e in ndoc.modelspace():
        if e.dxftype() == "ARC":
            for ang in (e.dxf.start_angle, e.dxf.end_angle):
                r = math.radians(ang)
                arc_pts.append((e.dxf.center.x + e.dxf.radius * math.cos(r),
                                e.dxf.center.y + e.dxf.radius * math.sin(r)))
    near_top = any(abs(x) < 1e-4 and abs(y - 1.0) < 1e-4 for (x, y) in arc_pts)
    assert near_top, "expected an arc endpoint at the (0,1) crossing: %r" % arc_pts
    print("PASS test_end_to_end_arc_gets_endpoint_at_line_crossing")


if __name__ == "__main__":
    test_circle_circle_points_two_intersections()
    test_circle_circle_points_disjoint_and_contained()
    test_circle_circle_points_tangent()
    test_arc_split_by_line_through_interior()
    test_arc_not_split_when_line_only_touches_endpoint()
    test_end_to_end_arc_gets_endpoint_at_line_crossing()
    print("\nALL ARC-SPLIT TESTS PASSED")
