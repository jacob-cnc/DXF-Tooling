"""DXF Cleanup -- lightweight Tkinter desktop app.

Pick (or drag) a DXF in -> cleaned DXF out (default ``CLEAN_<name>.dxf``).
Shows a before/after preview and a short report. Local only; no network.

Run with the REAL interpreter (not the Microsoft Store 'python' stub):
    "C:\\Users\\jhonick\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" app.py

Drag-and-drop works only if the optional ``tkinterdnd2`` package is installed;
otherwise use the "Choose DXF..." button. Everything else is dependency-free.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dxfclean import clean_file, draw_dxf, collect_points, write_csv  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("TkAgg")
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.backends.backend_tkagg import (  # noqa: E402
    FigureCanvasTkAgg, NavigationToolbar2Tk)

# Optional drag-and-drop support.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    _HAS_DND = True
except Exception:
    _HAS_DND = False


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("DXF Cleanup -- ProtoTRAK DPM RMX")
        self.root.geometry("1320x720")
        self.root.minsize(1100, 560)

        self.src_path = None
        self.out_path = None
        self.points = []
        self._selected_idx = None   # currently-highlighted point index (1-based)
        self._dot = None            # matplotlib artist for the red marker

        self._build_ui()

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        ttk.Button(top, text="Choose DXF...",
                   command=self.choose_file).pack(side="left")
        self.path_var = tk.StringVar(
            value="Drop a .dxf here or click Choose DXF..."
            if _HAS_DND else "Click Choose DXF...")
        ttk.Label(top, textvariable=self.path_var).pack(side="left", padx=10)

        self.clean_btn = ttk.Button(top, text="Clean + Save",
                                     command=self.clean, state="disabled")
        self.clean_btn.pack(side="right")

        # Preview panes
        mid = ttk.Frame(self.root, padding=8)
        mid.pack(fill="both", expand=True)

        # Points table (right rail) -- packed FIRST so it always reserves its
        # width and can never be pushed off-screen by the previews.
        pts_frame = ttk.LabelFrame(mid, text="Coordinate points")
        pts_frame.pack(side="right", fill="y", padx=(8, 0))
        pts_frame.pack_propagate(False)
        pts_frame.configure(width=280)

        cols = ("idx", "x", "y")
        self.pts_tree = ttk.Treeview(pts_frame, columns=cols, show="headings",
                                     selectmode="browse")
        self.pts_tree.heading("idx", text="#")
        self.pts_tree.heading("x", text="X")
        self.pts_tree.heading("y", text="Y")
        self.pts_tree.column("idx", width=48, anchor="e")
        self.pts_tree.column("x", width=100, anchor="e")
        self.pts_tree.column("y", width=100, anchor="e")
        pts_scroll = ttk.Scrollbar(pts_frame, orient="vertical",
                                   command=self.pts_tree.yview)
        self.pts_tree.configure(yscrollcommand=pts_scroll.set)
        self.pts_count = tk.StringVar(value="No points yet - clean a file.")
        ttk.Label(pts_frame, textvariable=self.pts_count).pack(
            side="top", anchor="w", padx=4, pady=(2, 2))
        self.save_csv_btn = ttk.Button(pts_frame, text="Save points CSV...",
                                       command=self.save_points_csv,
                                       state="disabled")
        self.save_csv_btn.pack(side="bottom", fill="x", pady=(4, 0))
        pts_scroll.pack(side="right", fill="y")
        self.pts_tree.pack(side="left", fill="both", expand=True)
        # Click a row to drop a red dot at that point in the After view;
        # click the same row again to clear it. Bound on Button-1 (not
        # <<TreeviewSelect>>) so re-clicking the selected row can toggle off.
        self.pts_tree.bind("<Button-1>", self._on_point_click)

        before_frame = ttk.LabelFrame(mid, text="Before")
        before_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.before_fig, self.before_ax, self.before_canvas = \
            self._make_canvas(before_frame)

        after_frame = ttk.LabelFrame(mid, text="After (cleaned)")
        after_frame.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.after_fig, self.after_ax, self.after_canvas = \
            self._make_canvas(after_frame)

        # Report
        bottom = ttk.LabelFrame(self.root, text="Report", padding=4)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.report = tk.Text(bottom, height=9, wrap="word")
        self.report.pack(fill="x")
        self.report.configure(state="disabled")

        if _HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

    # ------------------------------------------------------- canvas factory
    def _make_canvas(self, parent):
        """Build an interactive matplotlib canvas with a navigation toolbar
        (zoom-box, pan, home/reset, save) and scroll-wheel zoom."""
        fig = Figure(figsize=(5, 4), dpi=100)
        fig.patch.set_facecolor("white")
        ax = fig.add_subplot(111)
        ax.set_aspect("equal")
        ax.set_axis_off()
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, parent, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="bottom", fill="x")
        # scroll-wheel zoom centred on the cursor
        canvas.mpl_connect("scroll_event",
                           lambda ev, a=ax, c=canvas: self._on_scroll(ev, a, c))
        return fig, ax, canvas

    @staticmethod
    def _on_scroll(event, ax, canvas):
        if event.inaxes is not ax or event.xdata is None:
            return
        scale = 0.8 if event.button == "up" else 1.25   # up = zoom in
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        xd, yd = event.xdata, event.ydata
        ax.set_xlim(xd - (xd - x0) * scale, xd + (x1 - xd) * scale)
        ax.set_ylim(yd - (yd - y0) * scale, yd + (y1 - yd) * scale)
        canvas.draw_idle()

    # ------------------------------------------------------------- events
    def _on_drop(self, event):
        path = event.data.strip().strip("{}")
        if path.lower().endswith(".dxf"):
            self.load(path)
        else:
            messagebox.showwarning("Not a DXF", "Please drop a .dxf file.")

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Choose a DXF file",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")])
        if path:
            self.load(path)

    # -------------------------------------------------------------- logic
    def load(self, path):
        self.src_path = path
        self.path_var.set(path)
        self.clean_btn.configure(state="normal")
        self._set_report("Loaded %s\nRendering preview..." % path)
        self._render_async(path, which="before")

    def clean(self):
        if not self.src_path:
            return
        base, _ext = os.path.splitext(self.src_path)
        # Default output name: CLEAN_<original>.dxf (prefix, not suffix).
        _dir = os.path.dirname(base)
        _name = os.path.basename(base)
        default = os.path.join(_dir, "CLEAN_" + _name + ".dxf")
        out = filedialog.asksaveasfilename(
            title="Save cleaned DXF as",
            defaultextension=".dxf",
            initialfile=os.path.basename(default),
            initialdir=os.path.dirname(default),
            filetypes=[("DXF files", "*.dxf")])
        if not out:
            return
        try:
            out, report = clean_file(self.src_path, out)
        except Exception as exc:
            messagebox.showerror("Cleanup failed", str(exc))
            return
        self.out_path = out
        self._set_report(report.as_text() + "\n\nSaved: " + out)
        self._render_async(out, which="after")
        self._populate_points()

    # -------------------------------------------------------------- points
    def _populate_points(self):
        """Compute the numbered coordinate points for the cleaned drawing and
        fill the table. Runs off the SOURCE doc so numbering matches the
        machinable output exactly."""
        import ezdxf
        self._clear_point_marker()
        for row in self.pts_tree.get_children():
            self.pts_tree.delete(row)
        self.points = []
        if not self.src_path:
            return
        try:
            doc = ezdxf.readfile(self.src_path)
            points, _report = collect_points(doc)
        except Exception as exc:
            messagebox.showwarning("Points", "Could not compute points:\n%s"
                                   % exc)
            return
        self.points = points
        for p in points:
            self.pts_tree.insert("", "end", iid=str(p.index),
                                 values=(p.index, "%.4f" % p.x, "%.4f" % p.y))
        self.pts_count.set("%d points" % len(points))
        self.save_csv_btn.configure(
            state=("normal" if points else "disabled"))

    # ---------------------------------------------------- interactive point
    def _on_point_click(self, event):
        """Toggle a red marker for the clicked coordinate row.

        Clicking a row highlights it and drops a red dot at that point in the
        After (cleaned) view. Clicking the SAME row again clears both.
        """
        row = self.pts_tree.identify_row(event.y)
        if not row:
            return None
        if row == self._selected_idx:
            # re-click the active row -> toggle OFF
            self._clear_point_marker()
            return "break"           # swallow so Treeview doesn't re-select
        self._select_point(row)
        return "break"

    def _select_point(self, iid):
        """Highlight row ``iid`` and draw the red dot at its coordinate."""
        try:
            idx = int(iid)
        except (TypeError, ValueError):
            return
        pt = next((p for p in self.points if p.index == idx), None)
        if pt is None:
            return
        # highlight the table row
        self.pts_tree.selection_set(iid)
        self.pts_tree.focus(iid)
        self.pts_tree.see(iid)
        self._selected_idx = iid
        # draw / move the red dot on the After axis (the cleaned geometry)
        if self._dot is not None:
            try:
                self._dot.remove()
            except Exception:
                pass
            self._dot = None
        (self._dot,) = self.after_ax.plot(
            [pt.x], [pt.y], marker="o", markersize=9,
            markerfacecolor="red", markeredgecolor="red", zorder=10,
            linestyle="None")
        self.after_canvas.draw_idle()

    def _clear_point_marker(self):
        """Remove the red dot and clear the row highlight."""
        if self._dot is not None:
            try:
                self._dot.remove()
            except Exception:
                pass
            self._dot = None
            self.after_canvas.draw_idle()
        if self._selected_idx is not None:
            try:
                self.pts_tree.selection_remove(self._selected_idx)
            except Exception:
                pass
        self._selected_idx = None


    def save_points_csv(self):
        if not self.points:
            return
        base = os.path.splitext(self.out_path or self.src_path or "points")[0]
        default = base + "_points.csv"
        path = filedialog.asksaveasfilename(
            title="Save coordinate points as CSV",
            defaultextension=".csv",
            initialfile=os.path.basename(default),
            initialdir=os.path.dirname(default),
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            write_csv(self.points, path)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        messagebox.showinfo("Saved", "Wrote %d points to:\n%s"
                            % (len(self.points), path))

    # ------------------------------------------------------------ preview
    def _render_into(self, path, which):
        """Draw ``path`` into the Before/After interactive axes."""
        ax = self.before_ax if which == "before" else self.after_ax
        canvas = self.before_canvas if which == "before" else self.after_canvas
        ax.clear()
        if which == "after":
            # ax.clear() wiped any red marker artist; drop the stale reference.
            self._dot = None
        ax.set_aspect("equal")
        ax.set_axis_off()
        try:
            draw_dxf(ax, path)
        except Exception as exc:
            self._set_report("Preview render failed: %s" % exc)
            return
        canvas.draw_idle()

    def _render_async(self, path, which):
        # Drawing touches Tk/matplotlib state, so do it on the main thread.
        # (File parse is fast; this keeps the canvas thread-safe.)
        self.root.after(0, lambda: self._render_into(path, which))

    def _set_report(self, text):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")


def main():
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
