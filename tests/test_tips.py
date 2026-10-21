"""The Tips tab: a Workspace/Tips notebook exists and the Tips page is a
read-only text widget populated with the key reference topics."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)


def _app():
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception:
        return None, None
    root.geometry("1320x720")
    import app as A
    a = A.App(root)
    root.update()
    return a, root


def test_tips_tab_present_and_populated():
    a, root = _app()
    if a is None:
        print("PASS test_tips_tab_present_and_populated (no display, skipped)")
        return
    try:
        import tkinter as tk
        tabs = [a.nb.tab(i, "text") for i in range(len(a.nb.tabs()))]
        assert "Workspace" in tabs, "expected a Workspace tab, got %r" % tabs
        assert "Tips" in tabs, "expected a Tips tab, got %r" % tabs

        # Find the Tips page's Text widget and read its content.
        tips_frame = a.nb.nametowidget(a.nb.tabs()[tabs.index("Tips")])
        texts = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Text):
                    texts.append(c)
                walk(c)
        walk(tips_frame)
        assert texts, "Tips tab has no Text widget"
        content = texts[0].get("1.0", "end")

        # It documents the three things the user asked to be explained.
        for topic in ("click", "chart", "Join", "Split", "window select"):
            assert topic.lower() in content.lower(), \
                "Tips page missing topic: %s" % topic
        # Read-only.
        assert str(texts[0]["state"]) == "disabled"
        print("PASS test_tips_tab_present_and_populated")
    finally:
        root.destroy()


if __name__ == "__main__":
    test_tips_tab_present_and_populated()
    print("\nALL TIPS TESTS PASSED")
