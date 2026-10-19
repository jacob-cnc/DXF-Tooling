"""DXF Cleanup -- lightweight Tkinter desktop app.

Pick (or drag) a DXF in -> cleaned DXF out (default ``<name>_clean.dxf``).
Shows a before/after preview and a short report. Local only; no network.

Run with the REAL interpreter (not the Microsoft Store 'python' stub):
    "C:\\Users\\jhonick\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" app.py

Drag-and-drop works only if the optional ``tkinterdnd2`` package is installed;
otherwise use the "Choose DXF..." button. Everything else is dependency-free.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dxfclean import clean_file, render, collect_points, write_csv  # noqa: E402

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
        self._tmpdir = tempfile.mkdtemp(prefix="dxfclean_preview_")
        self._before_img = None
        self._after_img = None

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

        before_frame = ttk.LabelFrame(mid, text="Before")
        before_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.before_canvas = tk.Label(before_frame, background="white")
        self.before_canvas.pack(fill="both", expand=True)

        after_frame = ttk.LabelFrame(mid, text="After (cleaned)")
        after_frame.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.after_canvas = tk.Label(after_frame, background="white")
        self.after_canvas.pack(fill="both", expand=True)

        # Report
        bottom = ttk.LabelFrame(self.root, text="Report", padding=4)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.report = tk.Text(bottom, height=9, wrap="word")
        self.report.pack(fill="x")
        self.report.configure(state="disabled")

        if _HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

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
        default = base + "_clean.dxf"
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
    def _render_async(self, path, which):
        def work():
            png = os.path.join(self._tmpdir, which + ".png")
            try:
                render(path, png)
            except Exception as exc:
                self.root.after(0, lambda: self._set_report(
                    "Preview render failed: %s" % exc))
                return
            self.root.after(0, lambda: self._show_png(png, which))
        threading.Thread(target=work, daemon=True).start()

    def _show_png(self, png, which):
        img = tk.PhotoImage(file=png)
        # Downsample large PNGs so they fit the pane without extra deps.
        pane_w = max(self.before_canvas.winfo_width(), 400)
        factor = max(1, img.width() // pane_w + 1)
        if factor > 1:
            img = img.subsample(factor, factor)
        if which == "before":
            self._before_img = img
            self.before_canvas.configure(image=img)
        else:
            self._after_img = img
            self.after_canvas.configure(image=img)

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
