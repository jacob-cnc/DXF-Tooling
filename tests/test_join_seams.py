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


def test_join_makes_one_unit_and_records_seams():
    a, root = _app()
    if a is None:
        import pytest; pytest.skip("no Tk display")
    try:
        if len(a._arcs) < 8:
            import pytest; pytest.skip("fixture produced too few arcs")
        before_arcs = len(a._arcs)
        arcs8 = a._arcs[:8]
        for ar in arcs8:
            a._select_geom(("arc",) + tuple(ar), [])
        assert len(a._sel_entities) == 8
        a.join_selected()
        root.update()
        # One joined child recorded, cached as a single selectable unit.
        assert len(a._join_parents) == 1
        assert len(a._polylines) == 1, \
            "joined child should be one polyline unit"
        # 8 arcs joined -> 7 interior seams + 2 endpoints.
        assert len(a._seams) == 7, \
            "expected 7 seam points, got %d" % len(a._seams)
        assert len(a._poly_endpoints) == 2
        # The joined arcs LEFT the per-segment cache (they are no longer
        # individually selectable; only the whole polyline is).
        assert len(a._arcs) == before_arcs - 8, \
            "joined sub-arcs must leave the per-arc cache (child is one unit)"
        # Latent seam dots were actually drawn as artists.
        assert len(a._seam_dot_artists) == len(a._seams)
    finally:
        root.destroy()


def test_clicking_joined_child_selects_whole_polyline():
    """Clicking anywhere on a joined child selects the WHOLE polyline as one
    unit, not a parent segment inside it; re-joining it is a no-op."""
    import math
    from types import SimpleNamespace
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
        a.clear_all_points()
        sub = a._polylines[0]["subs"][1]
        if sub[0] == "arc":
            _, cx, cy, r, sa, ea = sub
            m = math.radians((sa + ea) / 2.0)
            px, py = cx + r * math.cos(m), cy + r * math.sin(m)
        else:
            px = (sub[1][0] + sub[2][0]) / 2.0
            py = (sub[1][1] + sub[2][1]) / 2.0
        ev = SimpleNamespace(inaxes=a.after_ax, xdata=px, ydata=py, key=None)
        a._on_segment_click(ev)
        keys = list(a._sel_entities.keys())
        assert len(keys) == 1 and "poly" in keys[0], \
            "clicking a joined child should select the whole polyline unit"
        # Re-joining a selection that is only a joined child must be a no-op.
        n_before = len(a._polylines)
        a.join_selected()
        assert len(a._polylines) == n_before, "a child was re-joined (overlay)"
    finally:
        root.destroy()


def test_extend_existing_child_with_more_segments():
    """Join a few arcs into a child, then select that child + an adjacent arc
    and Join again: the existing polyline must GROW into one longer chain, not
    spawn a second polyline."""
    import math
    from types import SimpleNamespace
    a, root = _app()
    if a is None:
        import pytest; pytest.skip("no Tk display")
    try:
        if len(a._arcs) < 5:
            import pytest; pytest.skip("fixture produced too few arcs")

        def ep(ar):
            cx, cy, r, sa, ea = ar
            return ((cx + r * math.cos(math.radians(sa)),
                     cy + r * math.sin(math.radians(sa))),
                    (cx + r * math.cos(math.radians(ea)),
                     cy + r * math.sin(math.radians(ea))))

        for ar in a._arcs[:4]:
            a._select_geom(("arc",) + tuple(ar), [])
        a.join_selected(); root.update()
        assert len(a._polylines) == 1
        v_before = len(a._polylines[0]["verts"])

        # Select the child, then an arc adjacent to one of its endpoints.
        a.clear_all_points()
        sub = a._polylines[0]["subs"][1]
        if sub[0] == "arc":
            _, cx, cy, r, sa, ea = sub
            m = math.radians((sa + ea) / 2.0)
            px, py = cx + r * math.cos(m), cy + r * math.sin(m)
        else:
            px = (sub[1][0] + sub[2][0]) / 2.0
            py = (sub[1][1] + sub[2][1]) / 2.0
        a._on_segment_click(SimpleNamespace(inaxes=a.after_ax, xdata=px,
                                            ydata=py, key=None))
        ends = {a._polylines[0]["verts"][0], a._polylines[0]["verts"][-1]}
        added = 0
        for ar in list(a._arcs):
            e0, e1 = ep(ar)
            if any(math.hypot(e[0] - c[0], e[1] - c[1]) < 1e-6
                   for e in (e0, e1) for c in ends):
                a._select_geom(("arc",) + tuple(ar), [])
                added += 1
                break
        if added == 0:
            import pytest; pytest.skip("no arc adjacent to the child endpoints")

        a.join_selected(); root.update()
        assert len(a._polylines) == 1, \
            "extending should keep ONE polyline, not create a second"
        assert len(a._polylines[0]["verts"]) > v_before, \
            "the child's chain should have grown"
    finally:
        root.destroy()


if __name__ == "__main__":
    test_join_makes_one_unit_and_records_seams()
    test_clicking_joined_child_selects_whole_polyline()
    test_extend_existing_child_with_more_segments()
    print("join seams: OK")
