"""Unit test for dxfclean.selection.Seam -- the record that replaced the
parallel seam-point / seam-owner lists."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dxfclean import Seam


def test_seam_fields_and_owner():
    s = Seam((1.5, 2.5), poly=3, vertex=4)
    assert s.point == (1.5, 2.5)
    assert s.poly == 3 and s.vertex == 4
    assert s.owner == (3, 4)
    print("PASS test_seam_fields_and_owner")


def test_seam_is_frozen_and_hashable():
    s = Seam((0.0, 0.0), 0, 1)
    # frozen dataclass -> hashable, usable in a set/dict.
    assert s in {s}
    try:
        s.poly = 9  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "Seam should be immutable"
    print("PASS test_seam_is_frozen_and_hashable")


if __name__ == "__main__":
    test_seam_fields_and_owner()
    test_seam_is_frozen_and_hashable()
    print("\nALL SELECTION TESTS PASSED")
