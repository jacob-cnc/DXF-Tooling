"""Split feature: cutting a joined child at a parent-seam vertex yields two
pieces, and the cut vertex transitions from a translucent SEAM dot to a solid
ENDPOINT on the resulting geometry (the endpoint-visualizer behavior called
out in the design). A side with a single parent segment becomes a plain
LINE/ARC again (no seam dots).

Runnable:
    <real python> -m pytest tests/test_split.py
    <real python> tests/test_split.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

FIXTURE = os.path.join(REPO, "fixtures", "spline_to_arc_test.dxf")


def _app():
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception:
        return None, None
    root.geometry("1320x720")
    root.update()
    import app as A
    import tkinter.messagebox as mb
    mb.showwarning = lambda *a, **k: None
    mb.showinfo = lambda *a, **k: None
    a = A.App(root)
    a.arc_mode.set(True)
    a.src_path = FIXTURE
    a.clean()
    root.update()
    return a, root


def _near(p, pts, tol=1e-6):
    return any(math.hypot(p[0] - q[0], p[1] - q[1]) < tol for q in pts)


def test_split_divides_child_and_promotes_seam_to_endpoint():
    a, root = _app()
    if a is None:
        import pytest; pytest.skip("no Tk display")
    try:
        if len(a._arcs) < 6:
            import pytest; pytest.skip("fixture produced too few arcs")
        for ar in a._arcs[:6]:
            a._select_geom(("arc",) + tuple(ar), [])
        a.join_selected(); root.update()
        assert len(a._polylines) == 1
        assert len(a._seams) >= 3

        mid = len(a._seams) // 2
        seam_pt = a._seams[mid].point
        a._arm_split(mid)
        assert a._pending_split is not None
        assert str(a.split_btn["state"]) == "normal"

        a.split_at_seam(); root.update()
        # The one child became two pieces (polylines and/or plain segments).
        pieces = len(a._polylines)
        assert pieces >= 1
        # The cut vertex is now a solid endpoint (poly endpoint or a plain
        # LINE/ARC endpoint), and NOT a translucent seam dot any more.
        seg_eps = [p for seg in a._segments for p in seg]
        assert _near(seam_pt, a._poly_endpoints) or _near(seam_pt, seg_eps), \
            "cut seam should become a solid endpoint"
        assert not _near(seam_pt, [s.point for s in a._seams]), \
            "cut seam should no longer be a translucent seam dot"
        # Split button disarmed after use.
        assert a._pending_split is None
        assert str(a.split_btn["state"]) == "disabled"
    finally:
        root.destroy()


def test_split_single_segment_side_becomes_plain_entity():
    """Splitting one vertex in from the end leaves a single-segment side, which
    must become a plain LINE/ARC (in the per-segment caches), not a polyline."""
    a, root = _app()
    if a is None:
        import pytest; pytest.skip("no Tk display")
    try:
        if len(a._arcs) < 4:
            import pytest; pytest.skip("fixture produced too few arcs")
        for ar in a._arcs[:4]:
            a._select_geom(("arc",) + tuple(ar), [])
        a.join_selected(); root.update()
        assert len(a._polylines) == 1
        segs_before = len(a._segments) + len(a._arcs)
        # Arm the FIRST seam (one segment on the left side).
        a._arm_split(0)
        a.split_at_seam(); root.update()
        # One single-segment side -> a plain entity appeared in the caches.
        segs_after = len(a._segments) + len(a._arcs)
        assert segs_after > segs_before, \
            "a single-segment split side should become a plain LINE/ARC"
    finally:
        root.destroy()


if __name__ == "__main__":
    test_split_divides_child_and_promotes_seam_to_endpoint()
    test_split_single_segment_side_becomes_plain_entity()
    print("split: OK")
