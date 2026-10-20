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
    assert report.arcs_from_splines == len(arcs)
    assert report.splines_converted == 4


def test_line_mode_still_default_off():
    """Default clean_doc still flattens splines to lines (no behaviour change
    for existing callers)."""
    doc = ezdxf.readfile(FIXTURE)
    ndoc, report = clean_doc(doc)   # spline_to_arcs defaults False
    arcs = [e for e in ndoc.modelspace() if e.dxftype() == "ARC"]
    assert report.arcs_from_splines == 0
    assert len(arcs) == 0, "default mode should not emit spline arcs"


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("\nALL ARCFIT TESTS PASSED")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
