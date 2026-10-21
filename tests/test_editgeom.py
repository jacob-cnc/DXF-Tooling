"""Unit tests for dxfclean.editgeom -- the pure hit-test / chain-split
geometry extracted out of the GUI. No Tk, no matplotlib: this is exactly the
logic that used to be untestable inside app.py."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dxfclean import editgeom as eg


def test_point_seg_distance_on_and_off_segment():
    # On the segment -> 0; perpendicular offset -> that offset; past the end
    # -> distance to the nearer endpoint (clamped).
    assert eg.point_seg_distance(0.5, 0.0, (0, 0), (1, 0)) == 0.0
    assert math.isclose(eg.point_seg_distance(0.5, 2.0, (0, 0), (1, 0)), 2.0)
    assert math.isclose(eg.point_seg_distance(3.0, 0.0, (0, 0), (1, 0)), 2.0)
    print("PASS test_point_seg_distance_on_and_off_segment")


def test_point_seg_distance_degenerate():
    # Zero-length segment falls back to point distance.
    assert math.isclose(eg.point_seg_distance(3.0, 4.0, (0, 0), (0, 0)), 5.0)
    print("PASS test_point_seg_distance_degenerate")


def test_angle_in_sweep_wrapping():
    # Simple sweep.
    assert eg.angle_in_sweep(45, 0, 90)
    assert not eg.angle_in_sweep(135, 0, 90)
    # Wrapping sweep crossing 0 degrees (e.g. 350 -> 10).
    assert eg.angle_in_sweep(0, 350, 10)
    assert eg.angle_in_sweep(355, 350, 10)
    assert not eg.angle_in_sweep(180, 350, 10)
    print("PASS test_angle_in_sweep_wrapping")


def test_point_arc_distance_radial_vs_endpoint():
    # Unit circle centred at origin, quarter arc 0 -> 90 deg.
    # A point on the radial outside the sweep angle uses endpoint distance.
    # Radial hit inside the sweep: point at (2,0)-ish direction 45deg, r=1.
    d_in = eg.point_arc_distance(math.cos(math.radians(45)) * 2,
                                 math.sin(math.radians(45)) * 2,
                                 0, 0, 1, 0, 90)
    assert math.isclose(d_in, 1.0, abs_tol=1e-9)   # |2 - 1| radial
    # Angle 180 is outside 0..90, so distance is to the nearer endpoint (0,1)
    # or (1,0). Point at (-1, 0): nearer endpoint (1,0) dist 2, (0,1) dist ~1.41
    d_out = eg.point_arc_distance(-1.0, 0.0, 0, 0, 1, 0, 90)
    assert math.isclose(d_out, math.hypot(-1 - 0, 0 - 1), abs_tol=1e-9)
    print("PASS test_point_arc_distance_radial_vs_endpoint")


def test_poly_distance_picks_nearest_sub():
    subs = [("line", (0, 0), (1, 0)), ("line", (1, 0), (2, 0))]
    # Click right above the second sub.
    assert math.isclose(eg.poly_distance(1.5, 0.3, subs), 0.3, abs_tol=1e-9)
    assert eg.poly_distance(0, 0, []) is None
    print("PASS test_poly_distance_picks_nearest_sub")


def test_subs_to_lwpoly_points_lines():
    subs = [("line", (0, 0), (1, 0)), ("line", (1, 0), (1, 1))]
    pts = eg.subs_to_lwpoly_points(subs)
    assert len(pts) == 3
    assert all(abs(p[4]) < 1e-12 for p in pts)   # lines carry zero bulge
    assert math.isclose(pts[0][0], 0.0) and math.isclose(pts[-1][1], 1.0)
    print("PASS test_subs_to_lwpoly_points_lines")


def test_subs_to_lwpoly_points_arc_bulge_sign():
    # A CCW quarter arc 0 -> 90 contributes bulge tan(90deg/4) = tan(22.5) ~ .4142
    arc = ("arc", 0.0, 0.0, 1.0, 0.0, 90.0)
    pts = eg.subs_to_lwpoly_points([arc, ("line", (0, 1), (0, 2))])
    expected = math.tan(math.radians(90.0) / 4.0)
    assert math.isclose(pts[0][4], expected, abs_tol=1e-9)
    print("PASS test_subs_to_lwpoly_points_arc_bulge_sign")


def test_subs_to_lwpoly_points_reversed_sub_flips_bulge():
    # Second sub given end-first; builder must flip it and negate its bulge
    # so the chain stays continuous.
    a = ("line", (0, 0), (1, 0))
    arc_rev = ("arc", 1.0, 1.0, 1.0, 270.0, 0.0)   # endpoints (1,0) and (2,1)
    pts = eg.subs_to_lwpoly_points([a, arc_rev])
    # Chain must be continuous: consecutive vertices coincide at the seam (1,0).
    assert math.isclose(pts[1][0], 1.0, abs_tol=1e-9)
    assert math.isclose(pts[1][1], 0.0, abs_tol=1e-9)
    print("PASS test_subs_to_lwpoly_points_reversed_sub_flips_bulge")


def test_split_chain_subs():
    subs = [("line", (0, 0), (1, 0)), ("line", (1, 0), (2, 0)),
            ("line", (2, 0), (3, 0))]
    left, right = eg.split_chain_subs(subs, 1)
    assert left == subs[:1] and right == subs[1:]
    left2, right2 = eg.split_chain_subs(subs, 2)
    assert left2 == subs[:2] and right2 == subs[2:]
    # Endpoints are not valid interior cuts.
    assert eg.split_chain_subs(subs, 0) == (None, None)
    assert eg.split_chain_subs(subs, 3) == (None, None)
    print("PASS test_split_chain_subs")


def test_chain_vertices_count():
    subs = [("line", (0, 0), (1, 0)), ("line", (1, 0), (2, 0))]
    verts = eg.chain_vertices(subs)
    assert len(verts) == len(subs) + 1
    print("PASS test_chain_vertices_count")


if __name__ == "__main__":
    test_point_seg_distance_on_and_off_segment()
    test_point_seg_distance_degenerate()
    test_angle_in_sweep_wrapping()
    test_point_arc_distance_radial_vs_endpoint()
    test_poly_distance_picks_nearest_sub()
    test_subs_to_lwpoly_points_lines()
    test_subs_to_lwpoly_points_arc_bulge_sign()
    test_subs_to_lwpoly_points_reversed_sub_flips_bulge()
    test_split_chain_subs()
    test_chain_vertices_count()
    print("\nALL EDITGEOM TESTS PASSED")
