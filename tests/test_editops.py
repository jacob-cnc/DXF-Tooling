"""Unit tests for dxfclean.editops -- the join/split modelspace surgery
extracted out of the GUI. Uses a real ezdxf document (no Tk/matplotlib)."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ezdxf

from dxfclean import editops


def _geom_key(g):
    return repr(tuple(round(v, 5) if isinstance(v, (int, float)) else
                      (round(v[0], 5), round(v[1], 5)) if isinstance(v, tuple)
                      else v for v in g))


def _new_doc():
    doc = ezdxf.new()
    return doc, doc.modelspace()


def _counts(msp):
    c = {"LINE": 0, "ARC": 0, "LWPOLYLINE": 0}
    for e in msp:
        c[e.dxftype()] = c.get(e.dxftype(), 0) + 1
    return c


def test_entity_matches_any_line_reversed():
    doc, msp = _new_doc()
    msp.add_line((0, 0), (1, 0))
    e = list(msp)[0]
    # Forward and reversed geom both match.
    assert editops.entity_matches_any(e, [("line", (0, 0), (1, 0))])
    assert editops.entity_matches_any(e, [("line", (1, 0), (0, 0))])
    assert not editops.entity_matches_any(e, [("line", (0, 0), (0, 5))])
    print("PASS test_entity_matches_any_line_reversed")


def test_join_two_lines_into_polyline():
    doc, msp = _new_doc()
    msp.add_line((0, 0), (1, 0))
    msp.add_line((1, 0), (2, 0))
    sel = [("line", (0, 0), (1, 0)), ("line", (1, 0), (2, 0))]
    res = editops.join_in_modelspace(msp, sel, [], _geom_key)
    assert res.ok and res.n_used == 2 and not res.extended
    c = _counts(msp)
    assert c["LINE"] == 0 and c["LWPOLYLINE"] == 1
    assert len(res.vertices) == 3
    print("PASS test_join_two_lines_into_polyline")


def test_join_too_few_segments():
    doc, msp = _new_doc()
    msp.add_line((0, 0), (1, 0))
    res = editops.join_in_modelspace(msp, [("line", (0, 0), (1, 0))], [],
                                     _geom_key)
    assert not res.ok and res.error_kind == "too_few"
    print("PASS test_join_too_few_segments")


def test_join_not_connected():
    doc, msp = _new_doc()
    msp.add_line((0, 0), (1, 0))
    msp.add_line((5, 5), (6, 5))
    sel = [("line", (0, 0), (1, 0)), ("line", (5, 5), (6, 5))]
    res = editops.join_in_modelspace(msp, sel, [], _geom_key)
    assert not res.ok and res.error_kind == "not_connected"
    # Nothing consumed.
    assert _counts(msp)["LINE"] == 2
    print("PASS test_join_not_connected")


def test_split_roundtrip_two_pieces():
    doc, msp = _new_doc()
    # Build a 3-segment polyline, then split it at the middle vertex.
    for a, b in [((0, 0), (1, 0)), ((1, 0), (2, 0)), ((2, 0), (3, 0))]:
        msp.add_line(a, b)
    sel = [("line", (0, 0), (1, 0)), ("line", (1, 0), (2, 0)),
           ("line", (2, 0), (3, 0))]
    res = editops.join_in_modelspace(msp, sel, [], _geom_key)
    assert res.ok and _counts(msp)["LWPOLYLINE"] == 1
    subs = [("line", (0, 0), (1, 0)), ("line", (1, 0), (2, 0)),
            ("line", (2, 0), (3, 0))]
    verts = [(0, 0), (1, 0), (2, 0), (3, 0)]
    # Split at vertex 1 -> a single LINE (left) + a 2-seg polyline (right).
    ok = editops.split_in_modelspace(msp, subs, verts, 1)
    assert ok
    c = _counts(msp)
    assert c["LWPOLYLINE"] == 1 and c["LINE"] == 1
    print("PASS test_split_roundtrip_two_pieces")


def test_split_invalid_index():
    doc, msp = _new_doc()
    subs = [("line", (0, 0), (1, 0)), ("line", (1, 0), (2, 0))]
    verts = [(0, 0), (1, 0), (2, 0)]
    assert not editops.split_in_modelspace(msp, subs, verts, 0)
    assert not editops.split_in_modelspace(msp, subs, verts, 2)
    print("PASS test_split_invalid_index")


def test_emit_single_sub_stays_plain():
    doc, msp = _new_doc()
    editops.emit_subs(msp, [("line", (0, 0), (1, 0))], "0")
    assert _counts(msp)["LINE"] == 1 and _counts(msp)["LWPOLYLINE"] == 0
    editops.emit_subs(msp, [("arc", 0, 0, 1, 0, 90)], "0")
    assert _counts(msp)["ARC"] == 1
    print("PASS test_emit_single_sub_stays_plain")


if __name__ == "__main__":
    test_entity_matches_any_line_reversed()
    test_join_two_lines_into_polyline()
    test_join_too_few_segments()
    test_join_not_connected()
    test_split_roundtrip_two_pieces()
    test_split_invalid_index()
    test_emit_single_sub_stays_plain()
    print("\nALL EDITOPS TESTS PASSED")
