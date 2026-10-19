"""Regression test for the coordinate-points table feature.

Runnable two ways:
    <real python> -m pytest tests/test_points.py     (if pytest present)
    <real python> tests/test_points.py               (standalone; no deps)

Locks the numbered X|Y point table produced for the known delrin-peg fixture:
all three point classes (line endpoints/vertices, line<->arc/circle
intersections, arc endpoints + circle vertices) de-duplicated within
tolerance and numbered stably by ascending Y then X.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import ezdxf  # noqa: E402

from dxfclean import collect_points, points_as_csv  # noqa: E402

FIXTURE = os.path.join(REPO, "fixtures", "delrin_peg_ARCS_unsplit.dxf")

# The expected 14 de-duplicated points for the delrin peg, in numbering order
# (ascending Y, then X). Coordinates rounded to 6 dp for comparison.
EXPECTED = [
    (1,  0.000000,  0.000000),
    (2,  24.600000, 0.000000),
    (3,  37.100000, 0.000000),
    (4,  46.600000, 0.000000),
    (5,  7.200000,  6.950000),
    (6,  4.650000,  9.500000),
    (7,  7.200000,  9.500000),
    (8,  9.750000,  9.500000),
    (9,  46.600000, 9.500000),
    (10, 7.200000,  12.050000),
    (11, 0.000000,  19.000000),
    (12, 24.600000, 19.000000),
    (13, 37.100000, 19.000000),
    (14, 46.600000, 19.000000),
]


def run():
    assert os.path.isfile(FIXTURE), "fixture missing: %s" % FIXTURE
    doc = ezdxf.readfile(FIXTURE)
    points, report = collect_points(doc)

    print("Collected %d points:" % len(points))
    for p in points:
        print("  %2d  (%.4f, %.4f)  [%s]"
              % (p.index, p.x, p.y, ",".join(p.kinds)))

    # 1) exact count
    assert len(points) == len(EXPECTED), \
        "expected %d points, got %d" % (len(EXPECTED), len(points))

    # 2) numbering is 1..N contiguous
    assert [p.index for p in points] == list(range(1, len(points) + 1)), \
        "point indices must be 1..N contiguous"

    # 3) coordinates match the locked set (order = numbering)
    for p, (idx, ex, ey) in zip(points, EXPECTED):
        assert p.index == idx
        assert abs(p.x - ex) <= 1e-6 and abs(p.y - ey) <= 1e-6, \
            "point %d: got (%.6f, %.6f), expected (%.6f, %.6f)" \
            % (p.index, p.x, p.y, ex, ey)

    # 4) de-dup actually happened: the arc/edge junctions carry multiple kinds
    junction = next(p for p in points if abs(p.x - 24.6) <= 1e-6
                    and abs(p.y - 0.0) <= 1e-6)
    assert len(junction.kinds) > 1, \
        "expected a de-duplicated multi-kind junction, got %r" % \
        (junction.kinds,)

    # 5) CSV round-trips with a header + one row per point
    csv_text = points_as_csv(points)
    csv_rows = [r for r in csv_text.strip().splitlines() if r]
    assert csv_rows[0].startswith("index,x,y"), "CSV header malformed"
    assert len(csv_rows) == len(points) + 1, "CSV row count mismatch"

    print("\nALL POINTS CHECKS PASSED: 14 de-duped points, "
          "stable numbering, CSV ok.")
    return True


def test_points():
    assert run() is True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
