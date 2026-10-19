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

from dxfclean import clean_file, render  # noqa: E402

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
        self.root.geometry("1000x680")

        self.src_path = None
        self.out_path = None
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
