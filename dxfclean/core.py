"""Core DXF cleanup for ProtoTRAK DPM RMX chaining.

This is a direct port of the proven ``split_lines_at_intersections.py``
proof-of-concept. The line-splitting math (``ang_in``, ``line_circle_params``
and the per-line cut-parameter accumulation / dedupe / zero-length drop) is
preserved **byte-for-byte** so its validated-on-the-machine results do not
change. The only additions wrapped around it are:

* a SPLINE -> arc/line approximation pre-pass (requirement: no splines in the
  output; flag anything that cannot be converted), and
* a structured :class:`CleanReport` so the GUI and the acceptance test can read
  counts instead of parsing stdout.

Guarantees preserved from the PoC:
* geometry is only *subdivided* -- never moved, trimmed or merged;
* arcs and circles are copied through untouched;
* layers and units are preserved.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Tuple

import ezdxf

# Coincidence tolerance (relative). Matches the proven PoC exactly.
TOL = 1e-7

# Curvature-adaptive spline flattening (see _spline_to_lines). The chord-error
# tolerance is set RELATIVE to each spline's bounding-box diagonal, then
# clamped to an absolute floor/ceiling. _SPLINE_REL_TOL ~ 0.1% of the curve
# size gives faithful curves without over-segmenting straight runs.
_SPLINE_REL_TOL = 1e-3     # chord error as a fraction of the spline's bbox diag
_SPLINE_MIN_TOL = 1e-3     # absolute floor (drawing units) -- avoids over-fine
_SPLINE_MAX_TOL = 0.5      # absolute ceiling -- keeps big curves faithful


# --------------------------------------------------------------------------
# Proven geometry helpers -- ported verbatim from split_lines_at_intersections
# --------------------------------------------------------------------------
def ang_in(a, s, e):
    a %= 360.0
    s %= 360.0
    e %= 360.0
    if s <= e:
        return s - 1e-6 <= a <= e + 1e-6
    return a >= s - 1e-6 or a <= e + 1e-6


def line_circle_params(a, b, cx, cy, r):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    A = dx * dx + dy * dy
    fx, fy = ax - cx, ay - cy
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - r * r
    disc = B * B - 4 * A * C
    if disc < -1e-9:
        return []
    disc = max(disc, 0.0)
    sq = math.sqrt(disc)
    return [(-B + sq) / (2 * A), (-B - sq) / (2 * A)]


# --------------------------------------------------------------------------
# Overlapping-line merge  (NEW -- runs BEFORE the proven splitter)
# --------------------------------------------------------------------------
# Absolute distance tolerances for deciding two segments are the SAME line.
# These are drawing-unit absolutes (mm), chosen well below any machinable
# feature and safely above float noise. Kept deliberately LOOSER than
# LibreCAD's RS_TOLERANCE (1e-10): that is tuned for clean model geometry,
# whereas messy CAD-exported DXFs need a more forgiving merge threshold.
_MERGE_DIST = 1e-6      # max perpendicular offset to be "collinear"
_MERGE_ANG = 1e-6       # max |sin(angle)| between unit directions (parallel)
# Squared-length floor for the zero-length test. Comparing squared lengths
# avoids a sqrt and matches LibreCAD's isNonZeroLineLength() approach.
_MERGE_LEN2 = _MERGE_DIST * _MERGE_DIST


def merge_overlapping_lines(segs, layers):
    """Merge collinear, overlapping line segments into their union.

    ProtoTRAK chaining breaks when two LINE entities sit on top of each other
    (a duplicate, or a short line lying along a longer one): the control can
    chain the duplicate and emit a doubled or zero-feed move. The proven
    splitter never removed these -- it only *subdivides* geometry, by design.
    This pass collapses them up front.

    Two segments overlap when they are collinear (same infinite line, within
    ``_MERGE_DIST`` / ``_MERGE_ANG``) **and on the same layer**, and their 1-D
    projections onto that line share more than a single point. A connected
    group of such segments is replaced by the maximal covered run(s) along the
    shared line -- so a chain of touching/overlapping colinear pieces becomes
    one segment, but two colinear pieces with a real GAP between them stay as
    two (the gap is preserved, never bridged).

    Layers are preserved: segments on different layers are never merged with
    each other. Direction is normalised; the returned segment keeps the
    group's extreme endpoints.

    Parameters
    ----------
    segs   : list of ((x,y),(x,y))
    layers : list of layer names, parallel to ``segs``

    Returns
    -------
    (new_segs, new_layers, merged_count)
        ``merged_count`` is how many input segments were absorbed into
        another (i.e. ``len(segs) - len(new_segs)``, never negative).
    """
    n = len(segs)
    if n < 2:
        return list(segs), list(layers), 0

    # Pre-compute per-segment direction, length and a canonical line key.
    info = []
    for (a, b) in segs:
        (ax, ay), (bx, by) = a, b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 <= _MERGE_LEN2:   # squared-length zero test (no sqrt)
            info.append(None)   # degenerate; left untouched, splitter drops it
            continue
        L = math.sqrt(L2)
        ux, uy = dx / L, dy / L
        info.append((ax, ay, ux, uy, L))

    def collinear(i, j):
        """True if segs i and j lie on the same infinite line (same layer)."""
        if info[i] is None or info[j] is None:
            return False
        if layers[i] != layers[j]:
            return False
        ax, ay, ux, uy, _ = info[i]
        bx, by, vx, vy, _ = info[j]
        # Parallel test: |sin(angle)| between unit directions ~ 0 (the 2D
        # cross product of two unit vectors IS sin of the angle between them).
        # This is the angle-based collinearity check LibreCAD uses
        # (areLinesOnSameRay) -- more robust than perpendicular distance alone
        # on long lines, where a tiny angular error becomes a large offset at
        # the far end.
        if abs(ux * vy - uy * vx) > _MERGE_ANG:
            return False
        # AND the lines must be coincident, not merely parallel: j's origin
        # must lie on i's infinite line (perpendicular distance ~ 0).
        wx, wy = bx - ax, by - ay
        perp = abs(wx * (-uy) + wy * ux)
        return perp <= _MERGE_DIST

    # Union-Find over collinear segments.
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        if info[i] is None:
            continue
        for j in range(i + 1, n):
            if collinear(i, j):
                union(i, j)

    # Group indices by their representative.
    groups: dict = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    new_segs, new_layers = [], []
    merged_count = 0

    for root, members in groups.items():
        real = [m for m in members if info[m] is not None]
        if not real:
            # all-degenerate group: pass through so splitter handles drops
            for m in members:
                new_segs.append(segs[m])
                new_layers.append(layers[m])
            continue
        if len(real) == 1:
            m = real[0]
            new_segs.append(segs[m])
            new_layers.append(layers[m])
            continue

        # Shared line: use the first real member's origin + direction.
        ax, ay, ux, uy, _ = info[real[0]]
        layer = layers[real[0]]

        # Project every input onto the line as [lo, hi] scalar intervals.
        intervals = []
        for m in real:
            (p0, p1) = segs[m]
            t0 = (p0[0] - ax) * ux + (p0[1] - ay) * uy
            t1 = (p1[0] - ax) * ux + (p1[1] - ay) * uy
            intervals.append((min(t0, t1), max(t0, t1)))

        # Does this colinear group contain a GENUINE overlap (two inputs share
        # a sub-interval of positive length)?  Merely abutting pieces
        # (share only an endpoint) and gapped pieces do NOT count.
        order = sorted(range(len(intervals)), key=lambda m: intervals[m])
        has_overlap = False
        for a_i in range(len(order)):
            lo_a, hi_a = intervals[order[a_i]]
            for b_i in range(a_i + 1, len(order)):
                lo_b, hi_b = intervals[order[b_i]]
                if lo_b >= hi_a - _MERGE_DIST:
                    break            # sorted: no later interval can overlap
                # shared span length = min(hi) - max(lo)
                shared = min(hi_a, hi_b) - max(lo_a, lo_b)
                if shared > _MERGE_DIST:
                    has_overlap = True
                    break
            if has_overlap:
                break

        if not has_overlap:
            # No duplicated coverage: leave every member EXACTLY as-is so the
            # proven splitter sees the original geometry (abutting splits and
            # real gaps are preserved byte-for-byte).
            for m in real:
                new_segs.append(segs[m])
                new_layers.append(layers[m])
            continue

        # Genuine overlap present: collapse to maximal covered run(s), fusing
        # overlapping/abutting coverage but NEVER bridging a real gap. The
        # proven splitter runs afterwards and re-breaks each run at every
        # true intersection, so legitimate break points are restored by it.
        intervals.sort()
        runs = []
        cur_lo, cur_hi = intervals[0]
        for lo, hi in intervals[1:]:
            if lo <= cur_hi + _MERGE_DIST:    # overlapping or touching -> extend
                cur_hi = max(cur_hi, hi)
            else:                              # real gap -> close run
                runs.append((cur_lo, cur_hi))
                cur_lo, cur_hi = lo, hi
        runs.append((cur_lo, cur_hi))

        for (lo, hi) in runs:
            p0 = (ax + ux * lo, ay + uy * lo)
            p1 = (ax + ux * hi, ay + uy * hi)
            new_segs.append((p0, p1))
            new_layers.append(layer)

        merged_count += max(0, len(real) - len(runs))

    return new_segs, new_layers, merged_count


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
@dataclass
class CleanReport:
    """Structured result of a cleanup run."""

    lines_in: int = 0
    lines_out: int = 0
    arcs: int = 0
    circles: int = 0
    splines_in: int = 0
    splines_converted: int = 0
    arcs_from_splines: int = 0
    segments_dropped: int = 0
    overlaps_merged: int = 0
    other_dropped: int = 0
    warnings: List[str] = field(default_factory=list)
    out_lines: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = \
        field(default_factory=list)

    @property
    def lines_split(self) -> int:
        """How many input lines were subdivided into more than one segment."""
        # out - in is the net number of extra segments; a line that is not cut
        # contributes 1 in and 1 out. This equals the count of extra segments
        # produced by splitting, which is the machinist-meaningful number.
        return max(0, self.lines_out - self.lines_in)

    def as_text(self) -> str:
        lines = [
            "Entities in : %d lines, %d arcs, %d circles, %d splines"
            % (self.lines_in, self.arcs, self.circles, self.splines_in),
            "Entities out: %d lines, %d arcs, %d circles"
            % (self.lines_out, self.arcs, self.circles),
            "Lines split (extra segments): %d" % self.lines_split,
            "Overlapping lines merged: %d" % self.overlaps_merged,
            "Segments dropped (zero-length): %d" % self.segments_dropped,
            "Splines converted: %d / %d"
            % (self.splines_converted, self.splines_in),
        ]
        if self.arcs_from_splines:
            lines.append("Arcs fitted from splines: %d"
                         % self.arcs_from_splines)
        if self.other_dropped:
            lines.append("Unhandled entities dropped: %d" % self.other_dropped)
        if self.warnings:
            lines.append("Warnings:")
            lines.extend("  - " + w for w in self.warnings)
        else:
            lines.append("Warnings: none")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Spline conversion (no splines allowed in output)
# --------------------------------------------------------------------------
def _spline_to_lines(spline, report: CleanReport):
    """Flatten a SPLINE to a chain of LINE segments with CURVATURE-ADAPTIVE
    sampling.

    ezdxf's ``flattening(distance)`` is already adaptive: ``distance`` is a
    *chord-error* tolerance (max gap between the chord and the true curve) and
    ezdxf recursively subdivides MORE where the curve bends, fewer where it is
    nearly straight. The pitfall is a fixed absolute tolerance: 0.01 units is
    far too tight on a large drawing (hundreds of needless segments) and too
    coarse on a tiny one.

    Following LibreCAD's model (RS_Spline::fillDisplayPoints -- chord error
    scaled to the curve's bounding box, with a bounded segment budget), we set
    the tolerance RELATIVE to the spline's own size:

        chord_tol = clamp(_SPLINE_REL_TOL * bbox_diagonal,
                          _SPLINE_MIN_TOL, _SPLINE_MAX_TOL)

    So a 500 mm curve and a 5 mm curve both get a fidelity proportional to
    their size -- faithful to the CAD intent, without flooding the output with
    collinear vertices on straight runs.

    Returns a list of ((x,y),(x,y)) tuples, or [] (with a warning) if the
    spline cannot be sampled.
    """
    # Estimate the curve size from whatever points the spline exposes. A
    # spline built from FIT points may have no control_points (and vice
    # versa), so gather both; fall back to a coarse flatten if neither is set.
    pts_for_size = []
    for attr in ("control_points", "fit_points"):
        try:
            seq = getattr(spline, attr)
            pts_for_size.extend((p[0], p[1]) for p in seq)
        except Exception:
            pass
    if len(pts_for_size) < 2:
        try:
            pts_for_size = [(p.x, p.y) for p in spline.flattening(1.0)]
        except Exception:
            pts_for_size = []
    if len(pts_for_size) >= 2:
        xs = [p[0] for p in pts_for_size]
        ys = [p[1] for p in pts_for_size]
        diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    else:
        diag = 0.0
    if diag > 0.0:
        chord_tol = _SPLINE_REL_TOL * diag
        chord_tol = min(max(chord_tol, _SPLINE_MIN_TOL), _SPLINE_MAX_TOL)
    else:
        chord_tol = _SPLINE_MIN_TOL

    try:
        pts = [(p.x, p.y) for p in spline.flattening(chord_tol)]
    except Exception as exc:  # pragma: no cover - defensive
        report.warnings.append(
            "SPLINE on layer %r could not be converted (%s); dropped."
            % (getattr(spline.dxf, "layer", "?"), exc)
        )
        return []
    if len(pts) < 2:
        report.warnings.append(
            "SPLINE on layer %r produced < 2 points; dropped."
            % getattr(spline.dxf, "layer", "?")
        )
        return []
    segs = []
    for k in range(len(pts) - 1):
        p0, p1 = pts[k], pts[k + 1]
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 0:
            segs.append((p0, p1))
    return segs


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def _arc_angles(arc) -> Tuple[float, float]:
    """Convert an arcfit.ArcSeg to DXF (start_deg, end_deg).

    DXF arcs are ALWAYS traversed counter-clockwise from start_angle to
    end_angle. Our ArcSeg carries a cw flag; for a clockwise sweep we swap
    the endpoints so the CCW span DXF draws is the same physical arc.
    """
    cx, cy = arc.center
    a_start = math.degrees(math.atan2(arc.start[1] - cy, arc.start[0] - cx))
    a_end = math.degrees(math.atan2(arc.end[1] - cy, arc.end[0] - cx))
    if arc.cw:
        a_start, a_end = a_end, a_start
    return a_start % 360.0, a_end % 360.0


def clean_doc(doc, spline_to_arcs=False, arc_tol=0.005
              ) -> Tuple["ezdxf.document.Drawing", CleanReport]:
    """Clean an in-memory ezdxf document.

    ``spline_to_arcs`` -- when True, SPLINE entities are fitted to a G1 chain
    of circular ARCS (plus lines) via :mod:`dxfclean.arcfit` instead of being
    flattened to many short line segments. Arcs map cleanly to CNC G2/G3 and
    give the ProtoTRAK chaining workflow far fewer segments to click.
    ``arc_tol`` -- max chord deviation (drawing units) for that arc fit.

    Returns ``(new_doc, report)``. Does not mutate the input document.
    """
    report = CleanReport()
    msp = doc.modelspace()

    lines, arcs, circles, others = [], [], [], []
    # extra_line_segs holds lines synthesized from splines; they take part in
    # splitting exactly like native LINE entities.
    extra_line_segs: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []
    # fitted_arcs holds arcs synthesized from splines (spline_to_arcs mode):
    # (cx, cy, r, start_deg, end_deg, layer). Emitted directly; NOT split.
    fitted_arcs: List[Tuple[float, float, float, float, float, str]] = []

    for e in msp:
        t = e.dxftype()
        if t == "LINE":
            lines.append(e)
        elif t == "ARC":
            arcs.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius,
                         e.dxf.start_angle, e.dxf.end_angle, e.dxf.layer))
        elif t == "CIRCLE":
            circles.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius,
                            e.dxf.layer))
        elif t == "SPLINE":
            report.splines_in += 1
            ly = e.dxf.layer
            if spline_to_arcs:
                from . import arcfit
                pieces = arcfit.fit_spline(e, arc_tol)
                if pieces:
                    report.splines_converted += 1
                    for pc in pieces:
                        if isinstance(pc, arcfit.ArcSeg):
                            sa, ea = _arc_angles(pc)
                            fitted_arcs.append((pc.center[0], pc.center[1],
                                                pc.radius, sa, ea, ly))
                            report.arcs_from_splines += 1
                        else:   # LineSeg
                            extra_line_segs.append((pc.start, pc.end, ly))
                else:
                    report.warnings.append(
                        "SPLINE on layer %r could not be arc-fitted; "
                        "flattened instead." % ly)
                    for (p0, p1) in _spline_to_lines(e, report):
                        extra_line_segs.append((p0, p1, ly))
            else:
                segs = _spline_to_lines(e, report)
                if segs:
                    report.splines_converted += 1
                    for (p0, p1) in segs:
                        extra_line_segs.append((p0, p1, ly))
        else:
            others.append(e)

    report.lines_in = len(lines)
    report.arcs = len(arcs)
    report.circles = len(circles)
    report.other_dropped = len(others)
    for e in others:
        report.warnings.append(
            "Unhandled entity %s on layer %r dropped."
            % (e.dxftype(), getattr(e.dxf, "layer", "?"))
        )

    # All line segments to be split: native lines + spline-derived segments.
    line_segs = [((l.dxf.start.x, l.dxf.start.y),
                  (l.dxf.end.x, l.dxf.end.y)) for l in lines]
    line_layers = [l.dxf.layer for l in lines]
    for (p0, p1, ly) in extra_line_segs:
        line_segs.append((p0, p1))
        line_layers.append(ly)

    # NEW: merge collinear overlapping/duplicate lines into their union BEFORE
    # splitting, so the proven splitter never sees stacked duplicates. Runs
    # per-layer; gaps between colinear pieces are preserved.
    line_segs, line_layers, report.overlaps_merged = \
        merge_overlapping_lines(line_segs, line_layers)

    new_lines = []  # (p0, p1, layer)
    dropped = 0
    for i in range(len(line_segs)):
        a, b = line_segs[i]
        (ax, ay), (bx, by) = a, b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            # degenerate input line; skip (would be a zero-length segment)
            dropped += 1
            continue
        ts = set()

        # other lines: endpoints lying on this segment, and crossings
        for j, (c, d) in enumerate(line_segs):
            if j == i:
                continue
            for p in (c, d):
                px, py = p
                cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
                if abs(cross) <= 1e-6 * math.sqrt(L2 + 1):
                    t = ((px - ax) * dx + (py - ay) * dy) / L2
                    if TOL < t < 1 - TOL:
                        ts.add(t)

        # arcs
        for (cx, cy, r, sa, ea, _ly) in arcs:
            for t in line_circle_params(a, b, cx, cy, r):
                if TOL < t < 1 - TOL:
                    px, py = ax + t * dx, ay + t * dy
                    ang = math.degrees(math.atan2(py - cy, px - cx))
                    if ang_in(ang, sa, ea):
                        ts.add(t)

        # circles
        for (cx, cy, r, _ly) in circles:
            for t in line_circle_params(a, b, cx, cy, r):
                if TOL < t < 1 - TOL:
                    ts.add(t)

        # dedupe near-equal cut params so coincident intersections
        # (e.g. a tangent point shared by two entities) make ONE break,
        # not a zero-length sliver.
        cuts = sorted(ts)
        deduped = []
        for t in cuts:
            if not deduped or (t - deduped[-1]) > 1e-6:
                deduped.append(t)
        params = [0.0] + deduped + [1.0]
        pts = [(ax + t * dx, ay + t * dy) for t in params]
        seg_len = math.sqrt(L2)
        for k in range(len(pts) - 1):
            p0, p1 = pts[k], pts[k + 1]
            d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if d <= 1e-6 * (seg_len + 1):
                dropped += 1
                continue  # skip degenerate / zero-length segment
            new_lines.append((p0, p1, line_layers[i]))

    report.segments_dropped = dropped
    report.lines_out = len(new_lines)
    report.out_lines = list(new_lines)

    # Build output doc
    ndoc = ezdxf.new(doc.dxfversion)
    try:
        ndoc.units = doc.units
    except Exception:
        pass
    for name in doc.layers:
        ly = name.dxf.name
        if ly not in ndoc.layers:
            ndoc.layers.add(ly, color=getattr(name.dxf, "color", 7))
    nmsp = ndoc.modelspace()

    for (p0, p1, ly) in new_lines:
        nmsp.add_line(p0, p1, dxfattribs={"layer": ly})
    for (cx, cy, r, sa, ea, ly) in arcs:
        nmsp.add_arc((cx, cy), r, start_angle=sa, end_angle=ea,
                     dxfattribs={"layer": ly})
    for (cx, cy, r, ly) in circles:
        nmsp.add_circle((cx, cy), r, dxfattribs={"layer": ly})
    for (cx, cy, r, sa, ea, ly) in fitted_arcs:
        nmsp.add_arc((cx, cy), r, start_angle=sa, end_angle=ea,
                     dxfattribs={"layer": ly})

    return ndoc, report


def clean_file(src: str, out: str | None = None, spline_to_arcs=False,
               arc_tol=0.005) -> Tuple[str, CleanReport]:
    """Read ``src``, clean it, write to ``out`` (default ``CLEAN_<name>.dxf``).

    ``spline_to_arcs`` / ``arc_tol`` are forwarded to :func:`clean_doc`.
    Returns ``(out_path, report)``.
    """
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    if out is None:
        d = os.path.dirname(src)
        stem = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(d, "CLEAN_" + stem + ".dxf")
    doc = ezdxf.readfile(src)
    ndoc, report = clean_doc(doc, spline_to_arcs=spline_to_arcs,
                             arc_tol=arc_tol)
    ndoc.saveas(out)
    return out, report
