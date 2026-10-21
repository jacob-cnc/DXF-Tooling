"""Integration test: after a Join, the child polyline's PARENT segments stay
selectable (the polyline is expanded back into its LINE/ARC sub-entities in
the hit-test caches) and its interior seams are tracked for the latent
translucent+outline dots. Regression guard for the reported "joined parents
not selectable / no seam dots" bug.

Runnable:
    <real python> -m pytest tests/test_join_seams.py
    <real python> tests/test_join_seams.py
"""
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
    # Silence the leftover-info dialog so the test is non-interactive.
    import tkinter.messagebox as mb
    mb.showwarning = lambda *a, **k: None
    mb.showinfo = lambda *a, **k: None
    a = A.App(root)
    a.arc_mode.set(True)
    a.src_path = FIXTURE
    a.clean()
    root.update()
    return a, root


def test_join_keeps_parents_selectable_and_records_seams():
    a, root = _app()
    if a is None:
        import pytest; pytest.skip("no Tk display")
    try:
        if len(a._arcs) < 8:
            import pytest; pytest.skip("fixture produced too few arcs")
        arcs8 = a._arcs[:8]
        for ar in arcs8:
            a._select_geom(("arc",) + tuple(ar), [])
        assert len(a._sel_entities) == 8
        a.join_selected()
        root.update()
        # One joined child recorded.
        assert len(a._join_parents) == 1
        # 8 arcs joined -> 7 interior seams + 2 endpoints.
        assert len(a._seam_points) == 7, \
            "expected 7 seam points, got %d" % len(a._seam_points)
        assert len(a._poly_endpoints) == 2
        # The child's parent segments are back in the hit-test caches (so the
        # curve is still selectable), not collapsed into an opaque polyline.
        assert len(a._arcs) >= 8, \
            "joined sub-arcs should remain selectable in the arc cache"
        # Latent seam dots were actually drawn as artists.
        assert len(a._seam_dot_artists) == len(a._seam_points)
    finally:
        root.destroy()


if __name__ == "__main__":
    test_join_keeps_parents_selectable_and_records_seams()
    print("join seams: OK")
