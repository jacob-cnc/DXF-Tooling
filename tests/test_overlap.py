"""Regression test for the collinear overlapping-line merge pass.

Runnable two ways:
    <real python> -m pytest tests/test_overlap.py
    <real python> tests/test_overlap.py

Covers the cases ProtoTRAK chaining cares about:
  * exact duplicate lines collapse to one,
  * a short line lying on a longer one collapses to the longer,
  * a chain of touching colinear pieces collapses to one span,
  * two colinear pieces with a REAL GAP stay as two (gap never bridged),
  * segments on different LAYERS are never merged together,
  * non-colinear / crossing lines are left for the splitter (not merged),
  * the proven splitter still runs after the merge (end-to-end via clean_doc).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import ezdxf  # noqa: E402

from dxfclean.core import merge_overlapping_lines, clean_doc  # noqa: E402

TOL = 1e-6


def _seglen(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _approx(a, b, t=1e-5):
    return abs(a - b) <= t


# -------------------------------------------------------------------------
# Unit tests on the merge pass directly
# -------------------------------------------------------------------------
def test_exact_duplicate():
    segs = [((0, 0), (10, 0)), ((0, 0), (10, 0))]
    layers = ["0", "0"]
    out, outl, merged = merge_overlapping_lines(segs, layers)
    assert len(out) == 1, "two identical lines must collapse to one"
    assert merged == 1
    assert _seglen(*out[0]) == 10


def test_subset_overlap():
    # short line (2..6) lies entirely on the long one (0..10)
    segs = [((0, 0), (10, 0)), ((2, 0), (6, 0))]
    layers = ["0", "0"]
    out, outl, merged = merge_overlapping_lines(segs, layers)
    assert len(out) == 1
    assert merged == 1
    lo = min(out[0][0][0], out[0][1][0])
    hi = max(out[0][0][0], out[0][1][0])
    assert _approx(lo, 0) and _approx(hi, 10)


def test_partial_overlap_chain():
    # 0..6 and 4..10 overlap on 4..6 -> union 0..10
    segs = [((0, 0), (6, 0)), ((4, 0), (10, 0))]
    out, outl, merged = merge_overlapping_lines(segs, ["0", "0"])
    assert len(out) == 1
    assert merged == 1
    lo = min(out[0][0][0], out[0][1][0])
    hi = max(out[0][0][0], out[0][1][0])
    assert _approx(lo, 0) and _approx(hi, 10)


def test_abutting_pieces_preserved():
    # 0..5 and 5..10 touch ONLY at the point 5 (no shared length) -> these
    # are a legitimately-split edge, NOT an overlap. They must be PRESERVED,
    # so the proven splitter's break points are never undone.
    segs = [((0, 0), (5, 0)), ((5, 0), (10, 0))]
    out, outl, merged = merge_overlapping_lines(segs, ["0", "0"])
    assert len(out) == 2, "abutting split pieces must NOT be fused"
    assert merged == 0


def test_gap_preserved():
    # 0..4 and 6..10 are colinear but have a GAP 4..6 -> stay as two
    segs = [((0, 0), (4, 0)), ((6, 0), (10, 0))]
    out, outl, merged = merge_overlapping_lines(segs, ["0", "0"])
    assert len(out) == 2, "a real gap must NOT be bridged"
    assert merged == 0


def test_layers_not_merged():
    # identical geometry, different layers -> NOT merged
    segs = [((0, 0), (10, 0)), ((0, 0), (10, 0))]
    out, outl, merged = merge_overlapping_lines(segs, ["0", "CUT"])
    assert len(out) == 2
    assert merged == 0
    assert set(outl) == {"0", "CUT"}


def test_non_colinear_untouched():
    # a crossing X: two non-parallel lines -> left for the splitter
    segs = [((0, 0), (10, 10)), ((0, 10), (10, 0))]
    out, outl, merged = merge_overlapping_lines(segs, ["0", "0"])
    assert len(out) == 2
    assert merged == 0


def test_parallel_offset_not_merged():
    # parallel but NOT colinear (offset in Y) -> not merged
    segs = [((0, 0), (10, 0)), ((0, 1), (10, 1))]
    out, outl, merged = merge_overlapping_lines(segs, ["0", "0"])
    assert len(out) == 2
    assert merged == 0


# -------------------------------------------------------------------------
# End-to-end: merge pass + proven splitter together via clean_doc
# -------------------------------------------------------------------------
def test_end_to_end_duplicate_through_clean_doc():
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # two stacked duplicate horizontal lines + a vertical whose ENDPOINT lands
    # on them (the proven splitter breaks a line at another line's endpoint,
    # not at a pure interior X-crossing -- so this gives a real cut point).
    msp.add_line((0, 5), (10, 5))
    msp.add_line((0, 5), (10, 5))     # exact duplicate -> must merge
    msp.add_line((5, 5), (5, 10))     # endpoint at (5,5) lies on the H line
    ndoc, report = clean_doc(doc)

    # The duplicate horizontal collapses to one.
    assert report.overlaps_merged == 1, \
        "duplicate horizontal line should have been merged (got %d)" \
        % report.overlaps_merged

    out = [e for e in ndoc.modelspace() if e.dxftype() == "LINE"]
    segs = [((round(e.dxf.start.x, 6), round(e.dxf.start.y, 6)),
             (round(e.dxf.end.x, 6), round(e.dxf.end.y, 6))) for e in out]

    # Empirical invariants (not a magic total):
    #  - no two identical segments survive (duplicate gone)
    keys = [tuple(sorted(s)) for s in segs]
    assert len(keys) == len(set(keys)), \
        "duplicate segment survived: %r" % (keys,)
    #  - no collinear overlap survives anywhere
    assert not _collinear_overlaps(segs), "overlap survived: %r" % (segs,)
    #  - the vertical's endpoint at (5,5) split the merged H line into
    #    0..5 and 5..10, so: 2 H pieces + 1 vertical = 3 segments.
    assert len(segs) == 3, "expected 3 segments, got %d: %r" % (len(segs), segs)


def test_real_hex_tool_fixture():
    """Empirical check on a REAL shop drawing (183311-001 hex tool), which
    contains genuine stacked-duplicate edges. We assert PROPERTIES, not a
    magic count: overlaps are removed, none survive, bbox is preserved."""
    fx = os.path.join(REPO, "fixtures", "hex_tool_overlap.dxf")
    if not os.path.isfile(fx):
        return  # fixture optional; skip if absent
    doc = ezdxf.readfile(fx)

    # bbox of input lines
    def _bbox(msp):
        xs, ys = [], []
        for e in msp:
            if e.dxftype() == "LINE":
                xs += [e.dxf.start.x, e.dxf.end.x]
                ys += [e.dxf.start.y, e.dxf.end.y]
        return (min(xs), min(ys), max(xs), max(ys))

    bb_in = _bbox(doc.modelspace())
    ndoc, report = clean_doc(doc)

    # 1) the filter actually fired on this real file
    assert report.overlaps_merged > 0, \
        "expected overlaps to be found in the real hex-tool drawing"

    out_segs = [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))
                for e in ndoc.modelspace() if e.dxftype() == "LINE"]

    # 2) NO collinear overlap survives
    bad = _collinear_overlaps(out_segs)
    assert not bad, "overlaps survived in hex tool: %d pairs" % len(bad)

    # 3) bounding geometry of the lines is preserved
    bb_out = _bbox(ndoc.modelspace())
    for a, b in zip(bb_in, bb_out):
        assert abs(a - b) <= 1e-4, "hex bbox changed: %r vs %r" % (bb_in, bb_out)


def _collinear_overlaps(lines, dist=1e-6):
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
            dx2, dy2 = ex - cx, ey - cy
            L2 = math.hypot(dx2, dy2)
            if L2 == 0:
                continue
            vx, vy = dx2 / L2, dy2 / L2
            if abs(ux * vy - uy * vx) > 1e-6:
                continue
            if abs((cx - ax) * (-uy) + (cy - ay) * ux) > dist:
                continue
            t0 = (cx - ax) * ux + (cy - ay) * uy
            t1 = (ex - ax) * ux + (ey - ay) * uy
            lo, hi = sorted((t0, t1))
            if min(hi, L) - max(lo, 0.0) > dist:
                bad.append((i, j))
    return bad


def run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print("\nALL OVERLAP TESTS PASSED (%d)" % len(tests))
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
