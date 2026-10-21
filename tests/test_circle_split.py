"""A full CIRCLE is broken into ARC pieces at the points where other geometry
crosses its ring (so each piece is independently selectable/chainable); a
circle with NO crossings is left whole -- we never blindly quarter circles."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ezdxf

from dxfclean.core import clean_doc


def _counts(msp):
    c = {}
    for e in msp:
        c[e.dxftype()] = c.get(e.dxftype(), 0) + 1
    return c


def test_isolated_circle_stays_whole():
    doc = ezdxf.new()
    doc.modelspace().add_circle((0, 0), 5.0)
    nd, _ = clean_doc(doc)
    c = _counts(nd.modelspace())
    assert c.get("CIRCLE", 0) == 1, "an untouched circle must stay a circle"
    assert c.get("ARC", 0) == 0
    print("PASS test_isolated_circle_stays_whole")


def test_circle_with_two_crossing_lines_splits_into_quadrants():
    # A circle crossed by a horizontal and a vertical diameter line -> four
    # intersection points at 0/90/180/270 -> four quadrant arcs, no circle.
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_circle((0, 0), 5.0)
    msp.add_line((-8, 0), (8, 0))
    msp.add_line((0, -8), (0, 8))
    nd, _ = clean_doc(doc)
    c = _counts(nd.modelspace())
    assert c.get("CIRCLE", 0) == 0, "a crossed circle must become arcs"
    arcs = [e for e in nd.modelspace() if e.dxftype() == "ARC"]
    assert len(arcs) == 4, "two diameters should yield 4 quadrant arcs, got %d" % len(arcs)
    # Each quadrant spans ~90 degrees.
    for e in arcs:
        sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360.0
        assert abs(sweep - 90.0) < 1e-3, "expected 90-degree quadrants, got %.3f" % sweep
    print("PASS test_circle_with_two_crossing_lines_splits_into_quadrants")


def test_circle_with_one_crossing_line_splits_into_halves():
    # A single diameter line -> two intersection points -> two half arcs.
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_circle((0, 0), 5.0)
    msp.add_line((-8, 0), (8, 0))
    nd, _ = clean_doc(doc)
    c = _counts(nd.modelspace())
    assert c.get("CIRCLE", 0) == 0
    arcs = [e for e in nd.modelspace() if e.dxftype() == "ARC"]
    assert len(arcs) == 2, "one diameter should yield 2 half arcs, got %d" % len(arcs)
    print("PASS test_circle_with_one_crossing_line_splits_into_halves")


if __name__ == "__main__":
    test_isolated_circle_stays_whole()
    test_circle_with_two_crossing_lines_splits_into_quadrants()
    test_circle_with_one_crossing_line_splits_into_halves()
    print("\nALL CIRCLE-SPLIT TESTS PASSED")
