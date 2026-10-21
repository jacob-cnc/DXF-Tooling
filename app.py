"""DXF Cleanup -- lightweight Tkinter desktop app.

Pick (or drag) a DXF in -> cleaned DXF out (default ``CLEAN_<name>.dxf``).
Shows a before/after preview and a short report. Local only; no network.

Run with the REAL interpreter (not the Microsoft Store 'python' stub):
    "C:\\Users\\jhonick\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" app.py

Drag-and-drop works only if the optional ``tkinterdnd2`` package is installed;
otherwise use the "Choose DXF..." button. Everything else is dependency-free.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dxfclean import (clean_file, clean_doc, draw_dxf, collect_points,  # noqa: E402
                      write_csv)

import matplotlib  # noqa: E402
matplotlib.use("TkAgg")
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Arc as MplArc, Circle as MplCircle  # noqa: E402
from matplotlib.backends.backend_tkagg import (  # noqa: E402
    FigureCanvasTkAgg, NavigationToolbar2Tk)

# Optional drag-and-drop support.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    _HAS_DND = True
except Exception:
    _HAS_DND = False


# Selection highlight colors.
_SELECT_COLOR = "#228B22"   # forest green -- highlighted geometry
_DOT_COLOR = "#1E6FE0"      # complementary blue -- coordinate marker dots
_DESELECT_COLOR = "#C0392B" # red -- Ctrl-drag deselect rubber-band


class _DragLog:
    """Lightweight in-memory event log for diagnosing the after-view drag
    gesture. Captures every press/motion/release (matplotlib AND Tk) with
    coords, in-axis flag, toolbar mode and drag state, and writes the whole
    trace to a file when the app closes. Enabled by setting the environment
    variable ``DXFCLEANUP_DEBUG=1`` or running with ``--debug``; otherwise it
    is a no-op so normal users pay nothing.

    One bad top-down drag + closing the app produces a log the developer can
    read to see exactly which events fired and where they were dropped."""

    def __init__(self, enabled, path):
        self.enabled = bool(enabled)
        self.path = path
        self.lines = []
        self._t0 = None

    def log(self, tag, **fields):
        if not self.enabled:
            return
        import time
        now = time.time()
        if self._t0 is None:
            self._t0 = now
        dt = (now - self._t0) * 1000.0           # ms since first event
        parts = ["%8.1fms" % dt, "%-22s" % tag]
        for k, v in fields.items():
            if isinstance(v, float):
                v = round(v, 3)
            parts.append("%s=%s" % (k, v))
        self.lines.append(" ".join(parts))

    def flush(self):
        if not self.enabled or not self.lines:
            return
        try:
            import datetime
            header = ("DXF Cleanup drag-event log -- %s\n%d events\n%s\n"
                      % (datetime.datetime.now().isoformat(timespec="seconds"),
                         len(self.lines), "-" * 60))
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(header)
                fh.write("\n".join(self.lines))
                fh.write("\n")
        except Exception:
            pass


def _close(a, b, tol=1e-4):
    """Point equality within tol."""
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _point_seg_distance(px, py, a, b):
    """Shortest distance from point (px,py) to segment a-b."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _angle_in_sweep(deg, start_deg, end_deg):
    """True if angle ``deg`` lies on the CCW sweep start->end (DXF convention)."""
    a = deg % 360.0
    s = start_deg % 360.0
    e = end_deg % 360.0
    if s <= e:
        return s - 1e-9 <= a <= e + 1e-9
    return a >= s - 1e-9 or a <= e + 1e-9


def _point_arc_distance(px, py, cx, cy, r, start_deg, end_deg):
    """Distance from (px,py) to an arc. If the click's angle is within the
    sweep, it's the radial distance |dist-to-centre - r|; otherwise it's the
    distance to the nearer arc endpoint."""
    d = math.hypot(px - cx, py - cy)
    ang = math.degrees(math.atan2(py - cy, px - cx))
    if _angle_in_sweep(ang, start_deg, end_deg):
        return abs(d - r)
    best = None
    for a_deg in (start_deg, end_deg):
        rad = math.radians(a_deg)
        ex, ey = cx + r * math.cos(rad), cy + r * math.sin(rad)
        dd = math.hypot(px - ex, py - ey)
        best = dd if best is None else min(best, dd)
    return best if best is not None else abs(d - r)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("DXF Cleanup -- ProtoTRAK DPM RMX")
        self.root.geometry("1320x720")
        self.root.minsize(1100, 560)

        self.src_path = None
        self.out_path = None
        self._cleaned_doc = None    # in-memory cleaned doc (source of truth)
        self._tmpdir = tempfile.mkdtemp(prefix="dxfcleanup_")
        self.points = []
        self._markers = {}          # iid -> matplotlib artist (one red dot each)
        self._segments = []         # cleaned LINE segments ((x0,y0),(x1,y1))
        self._arcs = []             # cleaned arcs (cx,cy,r,start_deg,end_deg)
        self._circles = []          # cleaned circles (cx,cy,r)
        self._geom_highlights = {}  # key -> green overlay artist (selected geom)
        # Selected cleaned entities for Join: handle -> ("line"|"arc", params).
        self._sel_entities = {}
        # Row iid -> set of selected-entity keys that reference it. A row's dot
        # is removed only when the LAST owning entity is deselected, so a point
        # shared between two selected segments survives deselecting one.
        self._row_owners = {}
        self._rubber = None         # rubber-band rectangle artist
        self._drag_start = None     # window-select drag anchor (data coords)
        self._drag_last = None      # last in-axis drag point (data coords)
        self._drag_deselect = False # True while a Ctrl-drag is in progress

        # Optional drag-event diagnostics (DXFCLEANUP_DEBUG=1 or --debug).
        _debug = (os.environ.get("DXFCLEANUP_DEBUG") in ("1", "true", "True")
                  or "--debug" in sys.argv)
        _logdir = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(_logdir):
            _logdir = os.path.expanduser("~")
        self._draglog = _DragLog(
            _debug, os.path.join(_logdir, "dxfcleanup_drag_log.txt"))

        self._build_ui()
        # Flush the diagnostic log when the window closes.
        try:
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            pass

    def _on_close(self):
        """Flush diagnostics (if enabled) then close the window."""
        try:
            self._draglog.flush()
        except Exception:
            pass
        self.root.destroy()

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

        self.save_btn = ttk.Button(top, text="Save As...",
                                    command=self.save, state="disabled")
        self.save_btn.pack(side="right")
        self.join_btn = ttk.Button(top, text="Join selected",
                                    command=self.join_selected,
                                    state="disabled")
        self.join_btn.pack(side="right", padx=(0, 6))
        self.clean_btn = ttk.Button(top, text="Clean",
                                    command=self.clean, state="disabled")
        self.clean_btn.pack(side="right", padx=(0, 6))

        # Convert-splines-to-arcs toggle (G2/G3-friendly output).
        self.arc_mode = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Convert splines to arcs",
                        variable=self.arc_mode).pack(side="right", padx=10)

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
                                     selectmode="extended")
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
        # Select-all / clear-all row (above the Save button).
        sel_row = ttk.Frame(pts_frame)
        sel_row.pack(side="bottom", fill="x", pady=(4, 0))
        self.sel_all_btn = ttk.Button(sel_row, text="Select all",
                                      command=self.select_all_points,
                                      state="disabled")
        self.sel_all_btn.pack(side="left", fill="x", expand=True)
        self.clear_all_btn = ttk.Button(sel_row, text="Clear all",
                                        command=self.clear_all_points,
                                        state="disabled")
        self.clear_all_btn.pack(side="left", fill="x", expand=True)
        pts_scroll.pack(side="right", fill="y")
        self.pts_tree.pack(side="left", fill="both", expand=True)
        # Click a row to toggle a red dot at that point in the After view.
        # Each marked row persists until clicked again; several can be marked
        # at once. Bound on Button-1 so we fully control the toggle state.
        self.pts_tree.bind("<Button-1>", self._on_point_click)

        before_frame = ttk.LabelFrame(mid, text="Before")
        before_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.before_fig, self.before_ax, self.before_canvas, \
            self.before_toolbar = self._make_canvas(before_frame)

        after_frame = ttk.LabelFrame(mid, text="After (cleaned)")
        after_frame.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.after_fig, self.after_ax, self.after_canvas, \
            self.after_toolbar = self._make_canvas(after_frame)
        # After-view interaction: a plain click selects one entity; a
        # click-and-drag draws a rubber-band rectangle (window select).
        self.after_canvas.mpl_connect("button_press_event",
                                      self._on_after_press)
        self.after_canvas.mpl_connect("motion_notify_event",
                                      self._on_after_motion)
        self.after_canvas.mpl_connect("button_release_event",
                                      self._on_after_release)
        # Tk-level release backstop. matplotlib's button_release_event is NOT
        # delivered when the mouse-up lands on the toolbar widget or past the
        # canvas (which is why a top-to-bottom drag -- releasing toward the
        # bottom toolbar -- missed far more often than bottom-to-top). Tk holds
        # an implicit pointer grab from the press, so this fires regardless of
        # where the button is released and finalizes any in-progress drag.
        self.after_canvas.get_tk_widget().bind(
            "<ButtonRelease-1>", self._on_after_release_tk, add="+")
        # Diagnostic-only Tk press/motion probes: these let the log compare
        # what Tk delivers against what matplotlib delivers, so a press that
        # matplotlib never registers in-axis is visible. They never touch
        # selection state -- they only log.
        _tkw = self.after_canvas.get_tk_widget()
        _tkw.bind("<ButtonPress-1>",
                  lambda e: self._draglog.log("tk_press", wx=e.x, wy=e.y),
                  add="+")
        _tkw.bind("<Control-ButtonPress-1>",
                  lambda e: self._draglog.log("tk_press", wx=e.x, wy=e.y,
                                              ctrl=True), add="+")

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
        return fig, ax, canvas, toolbar

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
        """Clean the loaded DXF IN MEMORY -- no file is written. Populates the
        After view, points table and selectable geometry; enables Save/Join."""
        if not self.src_path:
            return
        import ezdxf
        try:
            doc = ezdxf.readfile(self.src_path)
            ndoc, report = clean_doc(doc, spline_to_arcs=self.arc_mode.get(),
                                     arc_tol=0.005)
        except Exception as exc:
            messagebox.showerror("Cleanup failed", str(exc))
            return
        self._cleaned_doc = ndoc
        self._set_report(report.as_text()
                         + "\n\n(Not saved yet -- use Save As...)")
        self._refresh_after()
        self.save_btn.configure(state="normal")

    def save(self):
        """Serialize the current in-memory cleaned doc (including any joins)."""
        if self._cleaned_doc is None:
            return
        base, _ext = os.path.splitext(self.src_path or "drawing.dxf")
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
            self._cleaned_doc.saveas(out)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.out_path = out
        messagebox.showinfo("Saved", "Wrote cleaned DXF to:\n%s" % out)

    def join_selected(self):
        """Fuse the selected adjacent entities into one LWPOLYLINE so the
        ProtoTRAK chains the whole run in a single pick. The selection must
        form a single unbroken path (else it is rejected)."""
        if self._cleaned_doc is None or len(self._sel_entities) < 2:
            return
        from dxfclean import order_chain
        geoms = list(self._sel_entities.values())
        chain = order_chain(geoms)
        if chain is None:
            messagebox.showwarning(
                "Join",
                "The selected segments must form a single connected chain "
                "(end-to-end, no gaps or branches). Adjust the selection and "
                "try again.")
            return
        msp = self._cleaned_doc.modelspace()
        layer = "0"
        to_delete = []
        for e in msp:
            if self._entity_matches_selection(e):
                to_delete.append(e)
                try:
                    layer = e.dxf.layer
                except Exception:
                    pass
        for e in to_delete:
            msp.delete_entity(e)
        # LWPOLYLINE vertices: (x, y, start_width, end_width, bulge).
        pts = [(v[0][0], v[0][1], 0.0, 0.0, v[1]) for v in chain]
        msp.add_lwpolyline(pts, format="xyseb", dxfattribs={"layer": layer})
        n = len(geoms)
        self.clear_all_points()
        self._refresh_after()
        self._set_report("Joined %d segments into one polyline chain.\n"
                         "(Not saved yet -- use Save As...)" % n)

    def _entity_matches_selection(self, e) -> bool:
        """True if a live cleaned entity corresponds to a selected geom."""
        t = e.dxftype()
        for g in self._sel_entities.values():
            if g[0] == "line" and t == "LINE":
                p0, p1 = g[1], g[2]
                s = (e.dxf.start.x, e.dxf.start.y)
                en = (e.dxf.end.x, e.dxf.end.y)
                if (_close(s, p0) and _close(en, p1)) or \
                   (_close(s, p1) and _close(en, p0)):
                    return True
            elif g[0] == "arc" and t == "ARC":
                _, cx, cy, r, sa, ea = g
                if (abs(e.dxf.center.x - cx) < 1e-4
                        and abs(e.dxf.center.y - cy) < 1e-4
                        and abs(e.dxf.radius - r) < 1e-4
                        and abs(e.dxf.start_angle - sa) < 1e-3
                        and abs(e.dxf.end_angle - ea) < 1e-3):
                    return True
        return False


    def _refresh_after(self):
        """Render the in-memory cleaned doc into the After view and rebuild the
        points table + selectable-geometry caches from it."""
        if self._cleaned_doc is None:
            return
        tmp = os.path.join(self._tmpdir, "cleaned_preview.dxf")
        try:
            self._cleaned_doc.saveas(tmp)
        except Exception as exc:
            self._set_report("Could not render cleaned doc: %s" % exc)
            return
        self._render_async(tmp, which="after")
        self._populate_points_from(tmp)

    # -------------------------------------------------------------- points
    def _populate_points(self):
        """Legacy entry for backward compat; points from source doc."""
        if self.out_path:
            return self._populate_points_from(self.out_path)

    def _populate_points_from(self, dxf_path):
        """Compute points and build geometry caches from a cleaned DXF file."""
        import ezdxf
        self.clear_all_points()
        for row in self.pts_tree.get_children():
            self.pts_tree.delete(row)
        self.points = []
        self._sel_entities = {}
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
        # Cache the cleaned geometry for viewer-side hit-testing.
        self._segments = []
        self._arcs = []
        self._circles = []
        try:
            cdoc = ezdxf.readfile(dxf_path)
            for e in cdoc.modelspace():
                t = e.dxftype()
                if t == "LINE":
                    self._segments.append(
                        ((e.dxf.start.x, e.dxf.start.y),
                         (e.dxf.end.x, e.dxf.end.y)))
                elif t == "ARC":
                    self._arcs.append(
                        (e.dxf.center.x, e.dxf.center.y, e.dxf.radius,
                         e.dxf.start_angle, e.dxf.end_angle))
                elif t == "CIRCLE":
                    self._circles.append(
                        (e.dxf.center.x, e.dxf.center.y, e.dxf.radius))
        except Exception:
            self._segments, self._arcs, self._circles = [], [], []
        for p in points:
            self.pts_tree.insert("", "end", iid=str(p.index),
                                 values=(p.index, "%.4f" % p.x, "%.4f" % p.y))
        self.pts_count.set("%d points" % len(points))
        state = "normal" if points else "disabled"
        self.save_csv_btn.configure(state=state)
        self.sel_all_btn.configure(state=state)
        self.clear_all_btn.configure(state=state)

    # ---------------------------------------------------- interactive points
    # ---------------------------------------------------- after-view input
    @staticmethod
    def _is_ctrl(event):
        """True if Ctrl was held for this matplotlib mouse event. matplotlib
        reports the modifier in ``event.key`` (e.g. 'control', 'ctrl+shift')."""
        k = getattr(event, "key", None) or ""
        return "control" in k or "ctrl" in k

    def _on_after_press(self, event):
        self._draglog.log("mpl_press", x=event.xdata, y=event.ydata,
                          inaxes=(event.inaxes is self.after_ax),
                          mode=getattr(self.after_toolbar, "mode", ""),
                          key=getattr(event, "key", None),
                          button=getattr(event, "button", None))
        if getattr(self.after_toolbar, "mode", ""):
            self._draglog.log("mpl_press_SKIP", why="toolbar_mode")
            return
        if event.inaxes is not self.after_ax or event.xdata is None:
            self._draglog.log("mpl_press_SKIP", why="not_in_axis")
            return
        self._drag_start = (event.xdata, event.ydata)
        self._drag_last = (event.xdata, event.ydata)
        # Latch the mode for the whole gesture: Ctrl = deselect, else select.
        self._drag_deselect = self._is_ctrl(event)
        self._draglog.log("drag_open", deselect=self._drag_deselect)

    def _on_after_motion(self, event):
        if self._drag_start is None or event.inaxes is not self.after_ax \
                or event.xdata is None:
            return
        x0, y0 = self._drag_start
        x1, y1 = event.xdata, event.ydata
        self._drag_last = (x1, y1)   # remember for a release outside the axis
        self._draglog.log("mpl_motion", x=x1, y=y1)
        if self._rubber is not None:
            try:
                self._rubber.remove()
            except Exception:
                pass
        from matplotlib.patches import Rectangle
        edge = _DESELECT_COLOR if self._drag_deselect else _SELECT_COLOR
        self._rubber = Rectangle((min(x0, x1), min(y0, y1)),
                                 abs(x1 - x0), abs(y1 - y0),
                                 fill=False, edgecolor=edge,
                                 linestyle="--", lw=1.0, zorder=12)
        self.after_ax.add_patch(self._rubber)
        self.after_canvas.draw_idle()

    def _on_after_release(self, event):
        """matplotlib release: finalize the drag using the event's data coords
        when it lands on the axis, else the last tracked in-axis point."""
        self._draglog.log("mpl_release", x=getattr(event, "xdata", None),
                          y=getattr(event, "ydata", None),
                          inaxes=(getattr(event, "inaxes", None)
                                  is self.after_ax),
                          drag_open=(self._drag_start is not None))
        if self._drag_start is None:
            return
        if event is not None and event.xdata is not None \
                and event.inaxes is self.after_ax:
            self._finish_drag(event.xdata, event.ydata, click_event=event)
        else:
            self._finish_drag(None, None, click_event=None)

    def _on_after_release_tk(self, _tk_event):
        """Tk-level backstop: if the matplotlib release never arrived (mouse-up
        over the toolbar or past the canvas), finalize the still-open drag with
        the last in-axis point. Deferred to idle so the matplotlib release --
        dispatched from the same Tk event -- gets first chance; this then
        no-ops because _drag_start is already cleared. Only a genuinely lost
        matplotlib release leaves the drag open for this to complete."""
        self._draglog.log("tk_release", wx=getattr(_tk_event, "x", None),
                          wy=getattr(_tk_event, "y", None),
                          drag_open=(self._drag_start is not None))

        def _backstop():
            if self._drag_start is None:
                self._draglog.log("tk_backstop_noop")
                return   # matplotlib release already handled it
            self._draglog.log("tk_backstop_FINISH")
            self._finish_drag(None, None, click_event=None)
        try:
            self.root.after_idle(_backstop)
        except Exception:
            _backstop()

    def _finish_drag(self, rel_x, rel_y, click_event=None):
        """Complete a press..release gesture exactly once. ``rel_x``/``rel_y``
        are the release data coords when available, else None (fall back to the
        last in-axis drag point)."""
        start = self._drag_start
        last = self._drag_last
        deselect = self._drag_deselect
        # Clear state up front so the two release paths can't double-fire.
        self._drag_start = None
        self._drag_last = None
        self._drag_deselect = False
        if self._rubber is not None:
            try:
                self._rubber.remove()
            except Exception:
                pass
            self._rubber = None
            self.after_canvas.draw_idle()
        if getattr(self.after_toolbar, "mode", ""):
            self._draglog.log("finish_SKIP", why="toolbar_mode")
            return
        if start is None:
            self._draglog.log("finish_SKIP", why="no_start")
            return
        if rel_x is not None:
            x1, y1 = rel_x, rel_y
            src = "release"
        elif last is not None:
            x1, y1 = last
            src = "drag_last"
        else:
            self._draglog.log("finish_SKIP", why="no_endpoint")
            return
        x0, y0 = start
        # Treat tiny drags as a click (single pick / single unpick). A click
        # needs real on-axis release coords to hit-test the point.
        if abs(x1 - x0) < self._pick_tolerance(4) and \
                abs(y1 - y0) < self._pick_tolerance(4):
            self._draglog.log("finish_CLICK", endpoint_src=src,
                              has_click_event=(click_event is not None))
            if click_event is not None:
                self._on_segment_click(click_event, deselect=deselect)
            return
        # Window gesture: everything fully inside the rectangle.
        self._draglog.log("finish_WINDOW", endpoint_src=src, deselect=deselect,
                          x0=x0, y0=y0, x1=x1, y1=y1)
        self._window_select(min(x0, x1), min(y0, y1),
                            max(x0, x1), max(y0, y1), deselect=deselect)
        self._draglog.log("window_done", selected=len(self._sel_entities))

    def _window_select(self, xmin, ymin, xmax, ymax, deselect=False):
        """Select (or, with ``deselect``, remove) every cleaned entity whose
        VISIBLE extent lies inside the box. Arcs are tested by their actual
        swept portion, not their full bounding circle (a fitted arc is a sliver
        of a huge circle, so the bounding-circle test wrongly rejected them)."""
        act = self._deselect_geom if deselect else self._select_geom

        def inside(p):
            return xmin <= p[0] <= xmax and ymin <= p[1] <= ymax

        def sweep_points(cx, cy, r, sa, ea, n=16):
            sweep = (ea - sa) % 360.0        # CCW magnitude
            if sweep == 0:
                sweep = 360.0
            return [(cx + r * math.cos(math.radians(sa + sweep * k / n)),
                     cy + r * math.sin(math.radians(sa + sweep * k / n)))
                    for k in range(n + 1)]

        for (p0, p1) in self._segments:
            if inside(p0) and inside(p1):
                act(("line", p0, p1), [p0, p1])
        for (cx, cy, r, sa, ea) in self._arcs:
            # Arc is selected only if its whole visible sweep is in the box.
            if all(inside(p) for p in sweep_points(cx, cy, r, sa, ea)):
                e0 = (cx + r * math.cos(math.radians(sa)),
                      cy + r * math.sin(math.radians(sa)))
                e1 = (cx + r * math.cos(math.radians(ea)),
                      cy + r * math.sin(math.radians(ea)))
                act(("arc", cx, cy, r, sa, ea), [e0, e1])
        for (ox, oy, r) in self._circles:
            # A full circle: its bounding box must fit (it has no partial sweep).
            if (xmin <= ox - r and ox + r <= xmax
                    and ymin <= oy - r and oy + r <= ymax):
                quads = [(ox, oy)]
                for ang in (0.0, 90.0, 180.0, 270.0):
                    rad = math.radians(ang)
                    quads.append((ox + r * math.cos(rad),
                                  oy + r * math.sin(rad)))
                act(("circle", ox, oy, r), quads)

    @staticmethod
    def _geom_key(geom):
        """Stable signature for a geom tuple (matches _add_selected_entity)."""
        return repr(tuple(round(v, 6) if isinstance(v, float) else v
                          for v in geom))

    def _select_geom(self, geom, targets):
        """Highlight a geom, record it for Join, and mark its point rows."""
        self._highlight_geometry(geom)
        self._add_selected_entity(geom)
        key = self._geom_key(geom)
        for xy in targets:
            iid = self._nearest_point_iid(xy)
            if iid is None:
                continue
            self._row_owners.setdefault(iid, set()).add(key)
            if iid not in self._markers:
                self._mark_point(iid)

    def _deselect_geom(self, geom, targets):
        """Inverse of _select_geom: drop the green overlay, forget the entity
        for Join, and remove each point dot that no OTHER selected entity still
        owns (so a shared endpoint survives deselecting just one segment)."""
        key = self._geom_key(geom)
        if key not in self._sel_entities:
            return   # wasn't selected; nothing to do
        # Remove the green overlay for this specific geom.
        art = self._geom_highlights.pop(key, None)
        if art is not None:
            try:
                art.remove()
            except Exception:
                pass
        self._sel_entities.pop(key, None)
        # Release this entity's claim on each of its point rows.
        for xy in targets:
            iid = self._nearest_point_iid(xy)
            if iid is None:
                continue
            owners = self._row_owners.get(iid)
            if owners is not None:
                owners.discard(key)
                if not owners:
                    self._row_owners.pop(iid, None)
                    self._unmark_point(iid)
        if self.join_btn is not None and len(self._sel_entities) < 2:
            self.join_btn.configure(state="disabled")
        self.after_canvas.draw_idle()
        self._update_sel_count()

    def _on_segment_click(self, event, deselect=False):
        """Click a LINE / ARC / CIRCLE in the After view -> mark the related
        point-chart rows (highlight + dots), reusing the multi-marker model.
        With ``deselect`` (Ctrl-click) the nearest selected entity is removed
        instead. Ignored while the toolbar is panning/zooming.

        Row mapping:
          * LINE   -> its two endpoints,
          * ARC    -> its two sweep endpoints,
          * CIRCLE -> its centre + four quadrant points.
        The nearest geometry (within a pixel-scaled tolerance) wins.
        """
        if getattr(self.after_toolbar, "mode", ""):
            return
        if event.inaxes is not self.after_ax or event.xdata is None:
            return
        cx, cy = event.xdata, event.ydata
        tol = self._pick_tolerance(8)

        best_d = None
        best_targets = None   # list of (x, y) coords whose rows to mark
        best_geom = None      # ("line", p0, p1) / ("arc", ...) / ("circle", ...)

        # Lines: distance to the segment; targets = both endpoints.
        for (p0, p1) in self._segments:
            d = _point_seg_distance(cx, cy, p0, p1)
            if best_d is None or d < best_d:
                best_d, best_targets = d, [p0, p1]
                best_geom = ("line", p0, p1)

        # Arcs: distance to the arc curve (radial, but only on the sweep);
        # targets = the two sweep endpoints.
        for (ax0, ay0, r, sa, ea) in self._arcs:
            d = _point_arc_distance(cx, cy, ax0, ay0, r, sa, ea)
            if best_d is None or d < best_d:
                ends = []
                for ang in (sa, ea):
                    rad = math.radians(ang)
                    ends.append((ax0 + r * math.cos(rad),
                                 ay0 + r * math.sin(rad)))
                best_d, best_targets = d, ends
                best_geom = ("arc", ax0, ay0, r, sa, ea)

        # Circles: radial distance to the ring; targets = centre + 4 quadrants.
        for (ox, oy, r) in self._circles:
            d = abs(math.hypot(cx - ox, cy - oy) - r)
            if best_d is None or d < best_d:
                quads = [(ox, oy)]
                for ang in (0.0, 90.0, 180.0, 270.0):
                    rad = math.radians(ang)
                    quads.append((ox + r * math.cos(rad),
                                  oy + r * math.sin(rad)))
                best_d, best_targets = d, quads
                best_geom = ("circle", ox, oy, r)

        if best_targets is None or best_d > tol:
            return   # click wasn't near any geometry

        if deselect:
            self._deselect_geom(best_geom, best_targets)
        else:
            self._select_geom(best_geom, best_targets)

    def _add_selected_entity(self, geom):
        """Record a clicked cleaned entity for Join, keyed by a signature."""
        if not geom:
            return
        self._sel_entities[self._geom_key(geom)] = geom
        if self.join_btn is not None and len(self._sel_entities) >= 2:
            self.join_btn.configure(state="normal")

    def _highlight_geometry(self, geom):
        """Draw a forest-green overlay on top of the selected entity. A geom
        already highlighted is left alone (no duplicate overlay stacking)."""
        if not geom:
            return
        key = self._geom_key(geom)
        if key in self._geom_highlights:
            return
        kind = geom[0]
        artist = None
        if kind == "line":
            _, p0, p1 = geom
            (artist,) = self.after_ax.plot(
                [p0[0], p1[0]], [p0[1], p1[1]], color=_SELECT_COLOR,
                lw=3.0, solid_capstyle="round", zorder=9)
        elif kind == "arc":
            _, ax0, ay0, r, sa, ea = geom
            artist = MplArc((ax0, ay0), r * 2, r * 2, angle=0,
                            theta1=sa, theta2=ea, edgecolor=_SELECT_COLOR,
                            lw=3.0, zorder=9)
            self.after_ax.add_patch(artist)
        elif kind == "circle":
            _, ox, oy, r = geom
            artist = MplCircle((ox, oy), r, fill=False,
                               edgecolor=_SELECT_COLOR, lw=3.0, zorder=9)
            self.after_ax.add_patch(artist)
        if artist is not None:
            self._geom_highlights[key] = artist
            self.after_canvas.draw_idle()

    def _pick_tolerance(self, pixels):
        """Convert a pixel pick radius to data units on the After axis."""
        try:
            x0, x1 = self.after_ax.get_xlim()
            bbox = self.after_ax.get_window_extent()
            if bbox.width <= 0:
                return abs(x1 - x0) * 0.02
            return abs(x1 - x0) * (pixels / bbox.width)
        except Exception:
            return 1.0

    def _nearest_point_iid(self, xy):
        """Return the row iid of the point nearest coordinate ``xy``."""
        if not self.points:
            return None
        x, y = xy
        best = None
        best_d = None
        for p in self.points:
            d = (p.x - x) ** 2 + (p.y - y) ** 2
            if best_d is None or d < best_d:
                best_d, best = d, p
        return str(best.index) if best is not None else None

    def _on_point_click(self, event):
        """Toggle a red marker for the clicked coordinate row. Each marked row
        stays marked (its own red dot + highlight) until it is clicked again;
        multiple rows can be marked at once."""
        row = self.pts_tree.identify_row(event.y)
        if not row:
            return None
        if row in self._markers:
            self._unmark_point(row)
        else:
            self._mark_point(row)
        return "break"   # swallow default so we fully control selection state

    def _mark_point(self, iid):
        """Add a red dot for row ``iid`` and highlight it (no effect if already
        marked)."""
        if iid in self._markers:
            return
        try:
            idx = int(iid)
        except (TypeError, ValueError):
            return
        pt = next((p for p in self.points if p.index == idx), None)
        if pt is None:
            return
        self.pts_tree.selection_add(iid)
        (dot,) = self.after_ax.plot(
            [pt.x], [pt.y], marker="o", markersize=9,
            markerfacecolor=_DOT_COLOR, markeredgecolor=_DOT_COLOR,
            zorder=11, linestyle="None")
        self._markers[iid] = dot
        self.after_canvas.draw_idle()
        self._update_sel_count()

    def _unmark_point(self, iid):
        """Remove the red dot and highlight for one row."""
        dot = self._markers.pop(iid, None)
        if dot is not None:
            try:
                dot.remove()
            except Exception:
                pass
            self.after_canvas.draw_idle()
        try:
            self.pts_tree.selection_remove(iid)
        except Exception:
            pass
        self._update_sel_count()

    def select_all_points(self):
        """Mark every point."""
        for p in self.points:
            self._mark_point(str(p.index))

    def clear_all_points(self):
        """Remove every marker and highlight."""
        for iid in list(self._markers.keys()):
            dot = self._markers.pop(iid, None)
            if dot is not None:
                try:
                    dot.remove()
                except Exception:
                    pass
        try:
            self.pts_tree.selection_remove(*self.pts_tree.selection())
        except Exception:
            pass
        for art in self._geom_highlights.values():
            try:
                art.remove()
            except Exception:
                pass
        self._geom_highlights = {}
        self._sel_entities = {}
        self._row_owners = {}
        if getattr(self, "join_btn", None) is not None:
            self.join_btn.configure(state="disabled")
        self.after_canvas.draw_idle()
        self._update_sel_count()

    def _update_sel_count(self):
        n = len(self._markers)
        total = len(self.points)
        if total:
            self.pts_count.set("%d points  (%d selected)" % (total, n))

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
            # ax.clear() wiped any overlay artists; drop their stale refs.
            # Geometry caches are repopulated by _populate_points after render.
            self._markers = {}
            self._geom_highlights = {}
            self._row_owners = {}
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
    app = App(root)
    try:
        root.mainloop()
    finally:
        try:
            app._draglog.flush()
        except Exception:
            pass


if __name__ == "__main__":
    main()
