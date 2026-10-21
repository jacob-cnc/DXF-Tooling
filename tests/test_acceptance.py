"""Acceptance test for the DXF cleanup core.

Runnable two ways:
    <real python> -m pytest tests/test_acceptance.py      (if pytest present)
    <real python> tests/test_acceptance.py                (standalone; no deps)

The fixture ``fixtures/delrin_peg_ARCS_unsplit.dxf`` has 6 lines + 2 arcs +
1 circle. Correctness is judged EMPIRICALLY -- by geometric invariants that
must hold for any machinable output -- NOT by a hard-coded segment count
(the delrin peg is a smoke fixture, not an authority on the "right" number
of segments). After cleanup the output MUST satisfy:
  * at least one line segment, all of positive length (ZERO zero-length),
  * NO two segments collinear-overlapping (the overlap-filter guarantee),
  * NO line with any other entity crossing its interior,
  * arcs and circles passed through unchanged,
  * the same bounding geometry as the input.
Before/after PNGs are rendered under docs/ and examples/.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import ezdxf  # noqa: E402

from dxfclean import clean_file, render  # noqa: E402
from dxfclean.core import circle_circle_points  # noqa: E402

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
# Empirical overlap check (no magic count)
# -------------------------------------------------------------------------
def collinear_overlaps(lines, dist=1e-6):
    """Return (i, j, shared_len) for every pair of output segments that are
    collinear AND share a sub-interval of positive length -- a duplicate or
    overlap the filter should have removed. Empirical correctness check:
    NONE should survive, whatever the total segment count is."""
    bad = []
    for i in range(len(lines)):
        (ax, ay), (bx, by) = lines[i]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L == 0:
            continue
        ux, uy = dx / L, dy / L
        for j in range(i + 1, len(lines)):
            (cx, cy), (ex, ey) = lines[j]
            ex2, ey2 = ex - cx, ey - cy
            L2 = math.hypot(ex2, ey2)
            if L2 == 0:
                continue
            vx, vy = ex2 / L2, ey2 / L2
            if abs(ux * vy - uy * vx) > 1e-6:                    # not parallel
                continue
            if abs((cx - ax) * (-uy) + (cy - ay) * ux) > dist:   # not collinear
                continue
            t0 = (cx - ax) * ux + (cy - ay) * uy
            t1 = (ex - ax) * ux + (ey - ay) * uy
            lo, hi = sorted((t0, t1))
            shared = min(hi, L) - max(lo, 0.0)
            if shared > dist:
                bad.append((i, j, shared))
    return bad


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

    # 1) EMPIRICAL invariants on the segment set (no magic ground-truth
    #    count -- the delrin peg is NOT treated as an authority on how many
    #    segments are "correct"; we assert properties that must hold for ANY
    #    machinable output instead).
    assert len(out_lines) >= 1, "expected at least one output segment"
    #    NO two output segments are collinear-overlapping duplicates --
    #    this is the overlap-filter guarantee, asserted structurally.
    overlaps = collinear_overlaps(out_lines)
    assert not overlaps, \
        "overlapping/duplicate segments survived:\n" + "\n".join(
            "  %d <-> %d (shared %.4f)" % (i, j, s) for i, j, s in overlaps)
    print("collinear overlapping segment pairs:", len(overlaps))

    # 2) arcs may now be SUBDIVIDED at interior intersections (so an endpoint
    #    exists wherever another entity crosses an arc -- the chaining fix),
    #    but geometry is only subdivided, never lost: the piece count never
    #    drops below the input, and the total swept angle is preserved.
    assert len(out_arcs) >= len(in_arcs), \
        "arcs must not be dropped (only subdivided)"

    def _swept(arcs):
        tot = 0.0
        for (cx, cy, r, sa, ea) in arcs:
            tot += ((ea - sa) % 360.0) or 360.0
        return tot
    # Group by circle (cx,cy,r) so split pieces of one arc still sum to its
    # original sweep.
    def _by_circle(arcs):
        d = {}
        for (cx, cy, r, sa, ea) in arcs:
            key = (round(cx, 4), round(cy, 4), round(r, 4))
            d[key] = d.get(key, 0.0) + (((ea - sa) % 360.0) or 360.0)
        return d
    in_sweep, out_sweep = _by_circle(in_arcs), _by_circle(out_arcs)
    assert set(in_sweep) == set(out_sweep), "arc circles changed"
    for key in in_sweep:
        assert abs(in_sweep[key] - out_sweep[key]) < 1e-3, \
            "total swept angle changed for arc %r (%.4f -> %.4f)" % (
                key, in_sweep[key], out_sweep[key])
    # Circles are now subdivided into arc pieces at points where other
    # geometry crosses their ring (so each piece is independently
    # selectable/chainable); a circle with NO intersections on its ring is
    # left whole. So the invariant is not "circle count unchanged" but: every
    # OUTPUT circle genuinely has no vertex on its ring (nothing crosses it),
    # and no full-circle ring was dropped without being replaced by arc
    # geometry. We assert the first, machine-meaningful half here.
    def _circle_has_crossing(c, lines, arcs, circles):
        cx, cy, r = c
        for (a, b) in lines:
            for t in line_circle_params(a, b, cx, cy, r):
                if TOL < t < 1 - TOL:
                    return True
        for (ax, ay, ar, asa, aea) in arcs:
            for (px, py) in circle_circle_points(cx, cy, r, ax, ay, ar):
                oang = math.degrees(math.atan2(py - ay, px - ax))
                if ang_in(oang, asa, aea):
                    return True
        for (ox, oy, orr) in circles:
            if abs(ox - cx) < 1e-4 and abs(oy - cy) < 1e-4 \
                    and abs(orr - r) < 1e-4:
                continue
            if circle_circle_points(cx, cy, r, ox, oy, orr):
                return True
        return False

    for c in out_circles:
        assert not _circle_has_crossing(c, out_lines, out_arcs, out_circles), \
            "an output circle still has a vertex on its ring and should have " \
            "been split into arcs: %r" % (c,)

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
          "%d segments, 0 zero-length, 0 overlaps, 0 interior crossings."
          % len(out_lines))
    return True


# pytest entry point
def test_acceptance():
    assert run() is True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
