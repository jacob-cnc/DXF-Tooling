"""Regression test for joinseg.order_chain (segment-join chaining).

Runnable:
    <real python> -m pytest tests/test_join.py
    <real python> tests/test_join.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from dxfclean.joinseg import order_chain, longest_chain  # noqa: E402


def test_longest_chain_takes_main_path_and_leaves_branch():
    """A fork: three segments meet at (10,0). longest_chain must join the
    longest straight run and leave the stub out (not reject everything)."""
    main_a = ("line", (0, 0), (10, 0))
    main_b = ("line", (10, 0), (20, 0))
    stub = ("line", (10, 0), (10, 5))      # branch off the junction
    chain, used, leftover, reason = longest_chain([main_a, main_b, stub])
    assert chain is not None
    assert len(used) == 2 and len(leftover) == 1
    assert leftover[0] == stub
    assert "branch" in reason


def test_longest_chain_leaves_disconnected_piece():
    a = ("line", (0, 0), (10, 0))
    b = ("line", (10, 0), (20, 0))
    far = ("line", (90, 90), (99, 90))
    chain, used, leftover, reason = longest_chain([a, b, far])
    assert chain is not None
    assert far in leftover and len(used) == 2
    assert "not connected" in reason


def test_longest_chain_clean_run_no_leftover():
    chain, used, leftover, reason = longest_chain(
        [("line", (0, 0), (10, 0)),
         ("line", (10, 0), (10, 10)),
         ("line", (10, 10), (0, 10))])
    assert chain is not None and not leftover and reason == ""
    assert len(used) == 3


def test_two_lines_connected():
    chain = order_chain([("line", (0, 0), (10, 0)),
                         ("line", (10, 0), (10, 5))])
    assert chain is not None
    assert len(chain) == 3
    assert chain[-1][1] == 0.0        # last vertex has no bulge


def test_segment_direction_agnostic():
    # second segment given end-first still chains
    chain = order_chain([("line", (0, 0), (10, 0)),
                         ("line", (10, 5), (10, 0))])
    assert chain is not None
    assert len(chain) == 3


def test_disjoint_rejected():
    assert order_chain([("line", (0, 0), (10, 0)),
                        ("line", (50, 50), (60, 50))]) is None


def test_gap_rejected():
    # tiny gap bigger than JOIN_TOL
    assert order_chain([("line", (0, 0), (10, 0)),
                        ("line", (10.01, 0), (20, 0))]) is None


def test_single_entity_rejected():
    assert order_chain([("line", (0, 0), (10, 0))]) is None


def test_arc_contributes_bulge():
    # quarter circle CCW from (10,0) to (0,10), centre (0,0), r=10:
    # start_angle 0, end_angle 90 -> sweep 90 -> bulge tan(22.5deg) ~ 0.4142
    line = ("line", (-10, 0), (10, 0))
    arc = ("arc", 0.0, 0.0, 10.0, 0.0, 90.0)
    chain = order_chain([line, arc])
    assert chain is not None
    bulges = [round(v[1], 4) for v in chain]
    assert any(abs(b) > 0.1 for b in bulges), \
        "arc should contribute a non-zero bulge: %r" % bulges


def test_three_segment_chain():
    chain = order_chain([("line", (0, 0), (10, 0)),
                         ("line", (10, 0), (10, 10)),
                         ("line", (10, 10), (0, 10))])
    assert chain is not None
    assert len(chain) == 4


def test_interior_first_segment_orders():
    """Repro of the reported Join bug: the chain's FIRST selected item sits in
    the MIDDLE of the path. The old forward-only walk grew only from item 0's
    tail and never matched the neighbour on item 0's start side, so it wrongly
    reported 'not a single connected chain'. Both-ends growth must handle it."""
    # Path A-B-C-D given with the middle piece (B-C) first.
    middle = ("line", (10, 0), (20, 0))
    left = ("line", (0, 0), (10, 0))
    right = ("line", (20, 0), (30, 0))
    chain = order_chain([middle, left, right])
    assert chain is not None, "interior-first selection wrongly rejected"
    assert len(chain) == 4
    xs = [round(v[0][0], 4) for v in chain]
    assert xs == [0, 10, 20, 30] or xs == [30, 20, 10, 0], \
        "chain not ordered end-to-end: %r" % xs


def test_two_collinear_verticals_sharing_midpoint():
    """The exact second-screenshot case: two vertical segments meeting at a
    shared midpoint, given middle-out / reversed. Must join."""
    top = ("line", (50.0, 6.0371), (50.0, 0.0))
    bottom = ("line", (50.0, 0.0), (50.0, -50.0))
    assert order_chain([top, bottom]) is not None
    # reversed orientations too
    assert order_chain([("line", (50.0, 0.0), (50.0, 6.0371)),
                        ("line", (50.0, -50.0), (50.0, 0.0))]) is not None


def test_small_fit_gap_within_tolerance_joins():
    """Biarc-fitted endpoints differ by ~1e-3; such a seam must still join
    (the old 1e-4 tolerance rejected it)."""
    a = ("line", (0.0, 0.0), (10.0, 0.0))
    b = ("line", (10.0008, 0.0), (20.0, 0.0))   # 8e-4 seam gap
    assert order_chain([a, b]) is not None, \
        "a sub-millimetre fit seam should join"
    # but a genuine gap is still rejected
    c = ("line", (10.05, 0.0), (20.0, 0.0))     # 0.05 gap
    assert order_chain([a, c]) is None


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("\nALL JOIN TESTS PASSED")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
