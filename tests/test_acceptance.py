"""Acceptance test for the DXF cleanup core.

Runnable two ways:
    <real python> -m pytest tests/test_acceptance.py      (if pytest present)
    <real python> tests/test_acceptance.py                (standalone; no deps)

The fixture ``fixtures/delrin_peg_ARCS_unsplit.dxf`` has 6 lines + 2 arcs +
1 circle. After cleanup the output MUST contain:
  * exactly 11 discrete line segments,
  * the 2 arcs and 1 circle unchanged,
  * ZERO zero-length segments,
  * and NO line with any other entity crossing its interior.
Before/after PNGs are rendered under docs/ and examples/ and asserted to have
the same bounding geometry (only segmentation differs).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import ezdxf  # noqa: E402

from dxfclean import clean_file, render  # noqa: E402

FIXTURE = os.path.join(REPO, "fixtures", "delrin_peg_ARCS_unsplit.dxf")
DOCS = os.path.join(REPO, "docs")
EXAMPLES = os.path.join(REPO, "examples")

TOL = 1e-6


# -------------------------------------------------------------------------
# Geometry readers
# -------------------------------------------------------------------------
def read_entities(path):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    lines, arcs, circles = [], [], []
    for e in msp:
        t = e.dxftype()
        if t == "LINE":
            lines.append(((e.dxf.start.x, e.dxf.start.y),
                          (e.dxf.end.x, e.dxf.end.y)))
        elif t == "ARC":
            arcs.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius,
                         e.dxf.start_angle, e.dxf.end_angle))
        elif t == "CIRCLE":
            circles.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius))
    return lines, arcs, circles


def bbox_of(path):
    lines, arcs, circles = read_entities(path)
    xs, ys = [], []
    for (a, b) in lines:
        xs += [a[0], b[0]]
        ys += [a[1], b[1]]
    for (cx, cy, r, _sa, _ea) in arcs:
        xs += [cx - r, cx + r]
        ys += [cy - r, cy + r]
    for (cx, cy, r) in circles:
        xs += [cx - r, cx + r]
        ys += [cy - r, cy + r]
    return (min(xs), min(ys), max(xs), max(ys))


# -------------------------------------------------------------------------
# Interior-crossing check
# -------------------------------------------------------------------------
def ang_in(a, s, e):
    a %= 360.0
    s %= 360.0
    e %= 360.0
    if s <= e:
        return s - 1e-6 <= a <= e + 1e-6
    return a >= s - 1e-6 or a <= e + 1e-6


def line_circle_params(a, b, cx, cy, r):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    A = dx * dx + dy * dy
    fx, fy = ax - cx, ay - cy
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - r * r
    disc = B * B - 4 * A * C
    if disc < -1e-9:
        return []
    disc = max(disc, 0.0)
    sq = math.sqrt(disc)
    return [(-B + sq) / (2 * A), (-B - sq) / (2 * A)]


def interior_crossings(lines, arcs, circles):
    """Return a list of (line_index, description) for any entity that falls
    STRICTLY between a line's endpoints (i.e. crosses its interior)."""
    bad = []
    for i, (a, b) in enumerate(lines):
        (ax, ay), (bx, by) = a, b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            continue
        seg_len = math.sqrt(L2)

        # other line endpoints lying colinear in the interior
        for j, (c, d) in enumerate(lines):
            if j == i:
                continue
            for p in (c, d):
                px, py = p
                cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
                if abs(cross) <= 1e-6 * math.sqrt(L2 + 1):
                    t = ((px - ax) * dx + (py - ay) * dy) / L2
                    if TOL < t < 1 - TOL:
                        bad.append((i, "line %d endpoint at t=%.5f" % (j, t)))

        # arc intersections on the active sweep
        for (cx, cy, r, sa, ea) in arcs:
            for t in line_circle_params(a, b, cx, cy, r):
                if TOL < t < 1 - TOL:
                    px, py = ax + t * dx, ay + t * dy
                    ang = math.degrees(math.atan2(py - cy, px - cx))
                    if ang_in(ang, sa, ea):
                        bad.append((i, "arc crossing at t=%.5f" % t))

        # circle intersections
        for (cx, cy, r) in circles:
            for t in line_circle_params(a, b, cx, cy, r):
                if TOL < t < 1 - TOL:
                    bad.append((i, "circle crossing at t=%.5f" % t))

        del seg_len
    return bad


# -------------------------------------------------------------------------
# The test
# -------------------------------------------------------------------------
def run():
    os.makedirs(DOCS, exist_ok=True)
    os.makedirs(EXAMPLES, exist_ok=True)

    assert os.path.isfile(FIXTURE), "fixture missing: %s" % FIXTURE

    in_lines, in_arcs, in_circles = read_entities(FIXTURE)
    print("INPUT : %d lines, %d arcs, %d circles"
          % (len(in_lines), len(in_arcs), len(in_circles)))
    assert len(in_lines) == 6, "fixture should have 6 lines"
    assert len(in_arcs) == 2, "fixture should have 2 arcs"
    assert len(in_circles) == 1, "fixture should have 1 circle"

    out_path = os.path.join(EXAMPLES, "delrin_peg_ARCS_clean.dxf")
    out_path, report = clean_file(FIXTURE, out_path)
    print("\n" + report.as_text())
    print("\nWROTE", out_path)

    out_lines, out_arcs, out_circles = read_entities(out_path)
    print("\nOUTPUT: %d lines, %d arcs, %d circles"
          % (len(out_lines), len(out_arcs), len(out_circles)))

    # 1) exactly 11 line segments
    assert len(out_lines) == 11, \
        "expected 11 line segments, got %d" % len(out_lines)

    # 2) arcs + circle unchanged
    assert len(out_arcs) == 2, "arcs must be unchanged (2)"
    assert len(out_circles) == 1, "circle must be unchanged (1)"

    # 3) zero zero-length segments
    zeros = [i for i, (a, b) in enumerate(out_lines)
             if math.hypot(b[0] - a[0], b[1] - a[1]) <= TOL]
    assert not zeros, "found zero-length segments at indices %r" % zeros
    print("zero-length segments:", len(zeros))
    assert report.segments_dropped >= 0

    # 4) no line has any other entity crossing its interior
    bad = interior_crossings(out_lines, out_arcs, out_circles)
    assert not bad, "interior crossings found:\n" + "\n".join(
        "  line %d: %s" % (i, d) for i, d in bad)
    print("interior crossings:", len(bad))

    # 5) bounding geometry preserved (only segmentation differs)
    bb_in = bbox_of(FIXTURE)
    bb_out = bbox_of(out_path)
    for a, b in zip(bb_in, bb_out):
        assert abs(a - b) <= 1e-6, "bbox changed: %r vs %r" % (bb_in, bb_out)
    print("bbox in :", tuple(round(v, 4) for v in bb_in))
    print("bbox out:", tuple(round(v, 4) for v in bb_out))

    # 6) render before/after PNGs
    before_png = os.path.join(DOCS, "before.png")
    after_png = os.path.join(DOCS, "after.png")
    render(FIXTURE, before_png)
    render(out_path, after_png)
    assert os.path.isfile(before_png) and os.path.getsize(before_png) > 0
    assert os.path.isfile(after_png) and os.path.getsize(after_png) > 0
    print("WROTE", before_png)
    print("WROTE", after_png)

    print("\nALL ACCEPTANCE CHECKS PASSED: "
          "11 segments, 0 zero-length, 0 interior crossings.")
    return True


# pytest entry point
def test_acceptance():
    assert run() is True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
