"""Headless GUI smoke test for Ctrl-click / Ctrl-window DESELECT.

Drives the real App selection state machine (no file I/O, no save dialog):
clean the spline-to-arc fixture in memory, select geometry, then remove it
with the Ctrl (deselect) path and assert the selection state empties, while a
point row shared between two still-selected entities survives.

Runnable:
    <real python> -m pytest tests/test_deselect.py
    <real python> tests/test_deselect.py

Skips cleanly if a Tk display is unavailable (e.g. truly headless CI).
"""
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

FIXTURE = os.path.join(REPO, "fixtures", "spline_to_arc_test.dxf")


def _make_app():
    """Build a withdrawn real-Tk App, or return None if Tk is unavailable."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception:
        return None, None
    root.withdraw()
    import app as A
    a = A.App(root)
    a.arc_mode.set(True)          # arc conversion on (matches the default)
    a.src_path = FIXTURE
    a.clean()                     # in-memory clean -> populates caches/points
    return a, root


def _ev(x, y, ax, ctrl=False):
    """Minimal matplotlib-event stand-in for the after-axis handlers."""
    return SimpleNamespace(inaxes=ax, xdata=x, ydata=y,
                           key="control" if ctrl else None)


def _bbox(app):
    """Bounding box of all cached geometry (so a window covers everything)."""
    xs, ys = [], []
    for (p0, p1) in app._segments:
        xs += [p0[0], p1[0]]; ys += [p0[1], p1[1]]
    for (cx, cy, r, _sa, _ea) in app._arcs:
        xs += [cx - r, cx + r]; ys += [cy - r, cy + r]
    for (ox, oy, r) in app._circles:
        xs += [ox - r, ox + r]; ys += [oy - r, oy + r]
    pad = 1.0
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def test_ctrl_window_deselects_everything():
    app, root = _make_app()
    if app is None:
        import pytest; pytest.skip("no Tk display")
    try:
        xmin, ymin, xmax, ymax = _bbox(app)
        # Select all via a plain window.
        app._window_select(xmin, ymin, xmax, ymax, deselect=False)
        assert len(app._sel_entities) > 0, "window select picked nothing"
        n = len(app._sel_entities)
        # Ctrl-window over the same box removes all of them.
        app._window_select(xmin, ymin, xmax, ymax, deselect=True)
        assert len(app._sel_entities) == 0, \
            "deselect left %d of %d entities" % (len(app._sel_entities), n)
        assert len(app._geom_highlights) == 0, "green overlays not cleared"
        assert str(app.join_btn["state"]) == "disabled"
    finally:
        root.destroy()


def test_ctrl_click_removes_one_entity():
    app, root = _make_app()
    if app is None:
        import pytest; pytest.skip("no Tk display")
    try:
        # Select the first two cached lines directly through the public path.
        assert len(app._segments) >= 2, "fixture needs >=2 lines"
        (a0, a1), (b0, b1) = app._segments[0], app._segments[1]
        app._select_geom(("line", a0, a1), [a0, a1])
        app._select_geom(("line", b0, b1), [b0, b1])
        assert len(app._sel_entities) == 2
        marked_before = len(app._markers)
        assert marked_before > 0

        # Ctrl-click the midpoint of the first line to deselect just it.
        mx, my = (a0[0] + a1[0]) / 2.0, (a0[1] + a1[1]) / 2.0
        app._on_segment_click(_ev(mx, my, app.after_ax, ctrl=True),
                              deselect=True)
        assert len(app._sel_entities) == 1, "Ctrl-click should drop one entity"
        # The surviving entity's green overlay is still present.
        assert len(app._geom_highlights) == 1
    finally:
        root.destroy()


def test_shared_endpoint_survives_partial_deselect():
    """Two connected segments share an endpoint. Deselecting one must keep the
    shared point's dot (still owned by the other)."""
    app, root = _make_app()
    if app is None:
        import pytest; pytest.skip("no Tk display")
    try:
        # Synthesize two connected lines that map onto real point rows: use the
        # first line and a second line sharing its endpoint via the cache if
        # present; otherwise fabricate a shared-endpoint pair on the same rows.
        if not app.points:
            import pytest; pytest.skip("fixture produced no points")
        p = app.points[0]
        shared = (p.x, p.y)
        other_a = (shared[0] + 10.0, shared[1])
        other_b = (shared[0], shared[1] + 10.0)
        geom1 = ("line", other_a, shared)
        geom2 = ("line", shared, other_b)
        app._select_geom(geom1, [other_a, shared])
        app._select_geom(geom2, [shared, other_b])
        shared_iid = app._nearest_point_iid(shared)
        assert shared_iid in app._markers, "shared row should be marked"
        # Deselect geom1; shared row is still owned by geom2 -> stays marked.
        app._deselect_geom(geom1, [other_a, shared])
        assert shared_iid in app._markers, \
            "shared endpoint dropped though another entity still owns it"
        assert len(app._sel_entities) == 1
        # Deselect geom2 too; now nothing owns the shared row -> unmarked.
        app._deselect_geom(geom2, [shared, other_b])
        assert shared_iid not in app._markers
        assert len(app._sel_entities) == 0
    finally:
        root.destroy()


def test_window_gesture_fires_when_release_is_outside_axis():
    """Repro of the ~50% miss: a window-drag whose mouse-up lands OUTSIDE the
    axis (event.inaxes is None, no data coords) must still fire the gesture,
    using the last in-axis drag point. Drives the real press/motion/release
    handlers end to end."""
    app, root = _make_app()
    if app is None:
        import pytest; pytest.skip("no Tk display")
    try:
        xmin, ymin, xmax, ymax = _bbox(app)
        ax = app.after_ax
        # Press inside, drag inside, then RELEASE with no coords (outside axis).
        app._on_after_press(_ev(xmin, ymin, ax))
        app._on_after_motion(_ev(xmax, ymax, ax))      # last in-axis point
        release = SimpleNamespace(inaxes=None, xdata=None, ydata=None, key=None)
        app._on_after_release(release)
        assert len(app._sel_entities) > 0, \
            "window select dropped because release landed outside the axis"
    finally:
        root.destroy()


def test_ctrl_window_fires_when_release_is_outside_axis():
    """Same repro for the deselect window: select all, then Ctrl-window-drag
    that releases outside the axis must still clear the selection."""
    app, root = _make_app()
    if app is None:
        import pytest; pytest.skip("no Tk display")
    try:
        xmin, ymin, xmax, ymax = _bbox(app)
        ax = app.after_ax
        app._window_select(xmin, ymin, xmax, ymax, deselect=False)
        assert len(app._sel_entities) > 0
        # Ctrl-drag, releasing outside the axis.
        app._on_after_press(_ev(xmin, ymin, ax, ctrl=True))
        app._on_after_motion(_ev(xmax, ymax, ax, ctrl=True))
        release = SimpleNamespace(inaxes=None, xdata=None, ydata=None,
                                  key="control")
        app._on_after_release(release)
        assert len(app._sel_entities) == 0, \
            "Ctrl-window deselect dropped on release outside the axis"
    finally:
        root.destroy()


if __name__ == "__main__":
    test_ctrl_window_deselects_everything()
    test_ctrl_click_removes_one_entity()
    test_shared_endpoint_survives_partial_deselect()
    test_window_gesture_fires_when_release_is_outside_axis()
    test_ctrl_window_fires_when_release_is_outside_axis()
    print("deselect smoke: OK")
