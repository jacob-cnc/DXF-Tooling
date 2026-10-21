"""Test the optional drag-event diagnostic logger (_DragLog) and that the App
records + flushes a log when debug is enabled. Keeps the debug aid honest:
a logger that silently fails to write would be useless for field debugging.

Runnable:
    <real python> -m pytest tests/test_draglog.py
    <real python> tests/test_draglog.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import app as A  # noqa: E402


def test_draglog_disabled_is_noop():
    tmp = os.path.join(tempfile.mkdtemp(), "nope.txt")
    log = A._DragLog(enabled=False, path=tmp)
    log.log("mpl_press", x=1.0, y=2.0)
    log.flush()
    assert not os.path.exists(tmp), "disabled logger must write nothing"


def test_draglog_enabled_writes_events():
    tmp = os.path.join(tempfile.mkdtemp(), "drag.txt")
    log = A._DragLog(enabled=True, path=tmp)
    log.log("mpl_press", x=1.0, y=2.0, inaxes=True)
    log.log("mpl_motion", x=3.0, y=4.0)
    log.log("finish_WINDOW", deselect=False)
    log.flush()
    assert os.path.exists(tmp), "enabled logger must write a file"
    body = open(tmp, encoding="utf-8").read()
    for tag in ("mpl_press", "mpl_motion", "finish_WINDOW"):
        assert tag in body, "missing %s in log" % tag
    assert "3 events" in body


def test_app_records_drag_events_when_debug_enabled():
    """Drive the real App press/motion/release with the logger forced on and
    confirm the gesture is captured and flushed -- the field-debug path."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception:
        import pytest; pytest.skip("no Tk display")
    root.withdraw()
    try:
        a = A.App(root)
        tmp = os.path.join(tempfile.mkdtemp(), "session.txt")
        a._draglog = A._DragLog(enabled=True, path=tmp)
        from types import SimpleNamespace
        ax = a.after_ax
        ev = lambda x, y: SimpleNamespace(inaxes=ax, xdata=x, ydata=y,
                                          key=None, button=1)
        a._on_after_press(ev(0.0, 0.0))
        a._on_after_motion(ev(5.0, 5.0))
        a._on_after_release(ev(5.0, 5.0))
        a._draglog.flush()
        body = open(tmp, encoding="utf-8").read()
        assert "mpl_press" in body and "drag_open" in body
        assert "mpl_release" in body
    finally:
        root.destroy()


if __name__ == "__main__":
    test_draglog_disabled_is_noop()
    test_draglog_enabled_writes_events()
    test_app_records_drag_events_when_debug_enabled()
    print("draglog: OK")
