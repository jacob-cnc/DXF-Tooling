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

from dxfclean.joinseg import order_chain  # noqa: E402


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


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("\nALL JOIN TESTS PASSED")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
