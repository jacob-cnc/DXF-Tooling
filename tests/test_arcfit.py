"""Regression test for spline -> circular-arc conversion (the moonshot).

Runnable two ways:
    <real python> -m pytest tests/test_arcfit.py
    <real python> tests/test_arcfit.py

Correctness is EMPIRICAL and fidelity-bounded (no magic arc count):
  * every fitted arc/line chain stays within the tolerance of the TRUE spline
    curve (the machining fidelity guarantee),
  * arc count is finite and reasonable (not an explosion, not zero),
  * end-to-end clean_doc(spline_to_arcs=True) emits real ARC entities,
  * tighter tolerance never increases deviation above tolerance.
Uses the ground-truth fixture (4 clean cubic Beziers: inflection-S, gentle
valley, tight hook, near-semicircle).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import ezdxf  # noqa: E402

from dxfclean import arcfit, clean_doc  # noqa: E402

FIXTURE = os.path.join(REPO, "fixtures", "spline_to_arc_test.dxf")


def _splines():
    doc = ezdxf.readfile(FIXTURE)
    return [e for e in doc.modelspace() if e.dxftype() == "SPLINE"]


def _max_deviation(spline, pieces, n=400):
    ct = spline.construction_tool()
    kmax = float(ct.max_t)
    worst = 0.0
    for k in range(n + 1):
        u = kmax * k / n
        p = ct.point(u)
        d = min(arcfit._dist_to_piece((p[0], p[1]), pc) for pc in pieces)
        worst = max(worst, d)
    return worst


def test_fixture_present():
    assert os.path.isfile(FIXTURE), "ground-truth fixture missing"
    assert len(_splines()) == 4, "fixture should have 4 splines"


def test_fidelity_within_tolerance():
    """Every spline is fitted within the tolerance, with a sane arc count."""
    tol = 0.005
    for i, sp in enumerate(_splines()):
        pieces = arcfit.fit_spline(sp, tol)
        assert pieces, "spline %d produced no pieces" % i
        narc = sum(1 for p in pieces if isinstance(p, arcfit.ArcSeg))
        assert narc >= 1, "spline %d produced no arcs" % i
        assert len(pieces) < 200, \
            "spline %d arc count exploded (%d)" % (i, len(pieces))
        dev = _max_deviation(sp, pieces)
        assert dev <= tol * 1.05, \
            "spline %d deviation %.5f exceeds tol %.5f" % (i, dev, tol)


def test_tighter_tol_holds():
    """A tighter tolerance is still honoured (monotonic fidelity)."""
    sp = _splines()[0]
    for tol in (0.05, 0.01, 0.005):
        pieces = arcfit.fit_spline(sp, tol)
        dev = _max_deviation(sp, pieces)
        assert dev <= tol * 1.05, "tol %.4f: dev %.5f too large" % (tol, dev)


def test_end_to_end_emits_arcs():
    """clean_doc(spline_to_arcs=True) emits real ARC entities."""
    doc = ezdxf.readfile(FIXTURE)
    ndoc, report = clean_doc(doc, spline_to_arcs=True, arc_tol=0.005)
    arcs = [e for e in ndoc.modelspace() if e.dxftype() == "ARC"]
    splines_out = [e for e in ndoc.modelspace() if e.dxftype() == "SPLINE"]
    assert len(arcs) >= 4, "expected arcs in output, got %d" % len(arcs)
    assert not splines_out, "no SPLINE should remain in cleaned output"
    # Fitted arcs may be SUBDIVIDED where they cross another entity (so an
    # endpoint exists at the intersection), so the output arc count is at
    # least the number of arcs fitted from splines, never fewer.
    assert len(arcs) >= report.arcs_from_splines
    assert report.splines_converted == 4


def test_line_mode_still_default_off():
    """Default clean_doc still flattens splines to lines (no behaviour change
    for existing callers)."""
    doc = ezdxf.readfile(FIXTURE)
    ndoc, report = clean_doc(doc)   # spline_to_arcs defaults False
    arcs = [e for e in ndoc.modelspace() if e.dxftype() == "ARC"]
    assert report.arcs_from_splines == 0
    assert len(arcs) == 0, "default mode should not emit spline arcs"


def _closed_splines():
    """Closed SPLINE loops whose start point equals their end point: a round
    loop and a long flat slot (the 2.17 x 0.03 shape from the Brian Flipper
    Base file that used to collapse to a zero-length line)."""
    doc = ezdxf.new()
    msp = doc.modelspace()
    round_pts = [(math.cos(a) * 5, math.sin(a) * 3)
                 for a in [k * math.pi / 4 for k in range(8)]]
    slot_pts = [(0, 0), (0.7, -0.015), (1.4, -0.015), (2.1, 0),
                (1.4, 0.015), (0.7, 0.015)]
    # Clamped splines whose first and last control points coincide start and
    # end on the same point, like the closed loops in that file.
    msp.add_open_spline(round_pts + round_pts[:1], degree=3)
    msp.add_open_spline(slot_pts + slot_pts[:1], degree=3)
    return doc, list(msp.query("SPLINE"))


def test_closed_spline_fits_as_closed_loop():
    """A closed spline is fitted as a connected loop within tolerance, with
    no zero-length pieces (they crashed the splitter with ZeroDivisionError)."""
    tol = 0.005
    _doc, splines = _closed_splines()
    for i, sp in enumerate(splines):
        ct = sp.construction_tool()
        p0, p1 = ct.point(0), ct.point(float(ct.max_t))
        assert math.dist(p0, p1) < 1e-9, "fixture spline %d not closed" % i
        pieces = arcfit.fit_spline(sp, tol)
        assert pieces and len(pieces) >= 2, \
            "closed spline %d collapsed to %d piece(s)" % (i, len(pieces or []))
        for pc in pieces:
            assert math.dist(pc.start, pc.end) > 1e-9, \
                "closed spline %d produced a zero-length piece" % i
        for a, b in zip(pieces, pieces[1:] + pieces[:1]):
            assert math.dist(a.end, b.start) < 1e-6, \
                "closed spline %d chain has a gap" % i
        dev = _max_deviation(sp, pieces)
        assert dev <= tol * 1.05, \
            "closed spline %d deviation %.5f exceeds tol" % (i, dev)


def test_closed_spline_cleans_end_to_end():
    """clean_doc(spline_to_arcs=True) handles closed splines without error."""
    doc, _ = _closed_splines()
    ndoc, report = clean_doc(doc, spline_to_arcs=True, arc_tol=0.005)
    assert report.splines_converted == 2
    assert len(list(ndoc.modelspace())) > 2


def test_line_circle_params_zero_length_segment():
    """A zero-length segment has no circle crossings (and must not divide by
    zero)."""
    from dxfclean.core import line_circle_params
    assert line_circle_params((1.0, 2.0), (1.0, 2.0), 0.0, 0.0, 3.0) == []


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("\nALL ARCFIT TESTS PASSED")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
