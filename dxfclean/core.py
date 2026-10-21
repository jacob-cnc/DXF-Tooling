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
* an entity is broken wherever another entity crosses its interior, so a
  chainable endpoint exists at every intersection. Lines are split at crossings
  with lines/arcs/circles (the original PoC); arcs are likewise split at
  crossings with lines/arcs/circles so a fillet meeting a line gets an endpoint
  there. A split arc's pieces sum to the original sweep.
* circles are copied through untouched;
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


def circle_circle_points(cx0, cy0, r0, cx1, cy1, r1):
    """Intersection POINTS of two circles, as a list of (x, y).

    Returns [] when the circles are separate, one contains the other, or they
    are coincident (infinitely many / no discrete crossings). Tangent circles
    return the single touch point.
    """
    dx, dy = cx1 - cx0, cy1 - cy0
    d2 = dx * dx + dy * dy
    if d2 <= 1e-18:
        return []                      # concentric (incl. identical)
    d = math.sqrt(d2)
    if d > r0 + r1 + 1e-9:
        return []                      # too far apart
    if d < abs(r0 - r1) - 1e-9:
        return []                      # one inside the other
    # Distance from c0 to the radical line's foot along the center line.
    a = (r0 * r0 - r1 * r1 + d2) / (2 * d)
    h2 = r0 * r0 - a * a
    h = math.sqrt(h2) if h2 > 0 else 0.0
    # Foot of the perpendicular from the centers' line.
    xm = cx0 + a * dx / d
    ym = cy0 + a * dy / d
    if h <= 1e-12:
        return [(xm, ym)]              # tangent: one point
    ox, oy = -dy * (h / d), dx * (h / d)
    return [(xm + ox, ym + oy), (xm - ox, ym - oy)]


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
    arcs_deduped: int = 0
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

    lines, arcs, circles, extra_line_segs, fitted_arcs = _collect_entities(
        msp, report, spline_to_arcs, arc_tol)

    # All line segments to be split: native lines + spline-derived segments.
    line_segs = [((l.dxf.start.x, l.dxf.start.y),
                  (l.dxf.end.x, l.dxf.end.y)) for l in lines]
    line_layers = [l.dxf.layer for l in lines]
    for (p0, p1, ly) in extra_line_segs:
        line_segs.append((p0, p1))
        line_layers.append(ly)

    # Merge collinear overlapping/duplicate lines into their union BEFORE
    # splitting, so the proven splitter never sees stacked duplicates. Runs
    # per-layer; gaps between colinear pieces are preserved.
    line_segs, line_layers, report.overlaps_merged = \
        merge_overlapping_lines(line_segs, line_layers)

    # All arcs (native + spline-fitted) take part in splitting symmetrically:
    # they cut lines, they cut each other, and they are themselves cut where
    # anything crosses their interior. This is what breaks a fillet arc at the
    # point it meets a line/arc so an endpoint exists there to chain/split.
    all_arcs = list(arcs) + list(fitted_arcs)

    # Drop exact-duplicate arcs (CAD exports often stack a fillet arc twice).
    # A duplicate makes the shared vertex a degree-4 FORK, which branches a
    # perimeter chain into the part. Do this BEFORE splitting so we don't
    # subdivide phantom copies.
    all_arcs, report.arcs_deduped = dedupe_arcs(all_arcs)

    new_lines, dropped = _split_lines_at_intersections(
        line_segs, line_layers, all_arcs, circles)

    circles_xy = [(cx, cy, r) for (cx, cy, r, _ly) in circles]
    split_arcs, arc_dropped = _split_arcs_at_intersections(
        all_arcs, line_segs, circles_xy)

    # Splitting co-circular overlaps re-creates pieces identical to arcs that
    # were already there (e.g. a wide arc cut at a nested arc's endpoints now
    # matches that nested arc). Dedupe again so those junctions stay degree-2
    # rather than becoming forks.
    split_arcs, post_dedup = dedupe_arcs(split_arcs)
    report.arcs_deduped += post_dedup

    # Break each CIRCLE that has vertices on its ring into arc pieces at those
    # intersections (lines + the split arcs), so each piece is independently
    # selectable. A circle with no intersections stays whole.
    circle_arc_pieces, kept_circles = _split_circles_at_intersections(
        circles, line_segs, split_arcs)
    split_arcs.extend(circle_arc_pieces)
    split_arcs, c_dedup = dedupe_arcs(split_arcs)
    report.arcs_deduped += c_dedup

    report.segments_dropped = dropped + arc_dropped
    report.lines_out = len(new_lines)
    report.out_lines = list(new_lines)

    ndoc = _build_output_doc(doc, new_lines, split_arcs, kept_circles, [])
    return ndoc, report


def _collect_entities(msp, report: CleanReport, spline_to_arcs: bool,
                      arc_tol: float):
    """Pass over the modelspace, classifying entities and converting splines.

    Returns ``(lines, arcs, circles, extra_line_segs, fitted_arcs)`` where
    ``lines`` are native LINE entities, ``arcs``/``circles`` are value tuples,
    ``extra_line_segs`` are ``(p0, p1, layer)`` lines synthesized from splines
    (which take part in splitting like native lines), and ``fitted_arcs`` are
    ``(cx, cy, r, start_deg, end_deg, layer)`` arcs fitted from splines (emitted
    directly, NOT split). Populates the entity-count and spline fields of
    ``report``.
    """
    lines, arcs, circles, others = [], [], [], []
    extra_line_segs: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []
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
    return lines, arcs, circles, extra_line_segs, fitted_arcs


def _split_lines_at_intersections(line_segs, line_layers, arcs, circles):
    """Break every line segment wherever another entity touches its interior.

    This is the proven, machine-validated split algorithm (ported verbatim
    from ``split_lines_at_intersections.py``); its results must not change.
    Returns ``(new_lines, dropped)`` where ``new_lines`` is a list of
    ``(p0, p1, layer)`` and ``dropped`` counts zero-length/degenerate pieces.
    """
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
    return new_lines, dropped


def _norm_angle(deg):
    a = deg % 360.0
    return a + 360.0 if a < 0 else a


def dedupe_arcs(arcs, tol=1e-4, ang_tol=1e-2):
    """Drop exact-duplicate arcs, keeping one of each.

    CAD exports frequently stack the SAME fillet arc twice (identical centre,
    radius and sweep). A duplicate arc makes the shared vertex degree-4, which
    the chainer sees as a FORK -- so chaining a perimeter branches into the
    part. Two arcs are the same when they share a centre, radius and sweep
    (either orientation: start/end swapped is the same curve). Returns
    ``(unique_arcs, n_removed)``. Only arc-vs-arc exact matches are removed; an
    arc that merely lies on a full circle's ring is left alone.
    """
    kept = []
    removed = 0
    for a in arcs:
        cx, cy, r, sa, ea = a[0], a[1], a[2], a[3], a[4]
        s, e = _norm_angle(sa), _norm_angle(ea)
        dup = False
        for k in kept:
            kcx, kcy, kr, ksa, kea = k[0], k[1], k[2], k[3], k[4]
            if (abs(cx - kcx) <= tol and abs(cy - kcy) <= tol
                    and abs(r - kr) <= tol):
                ks, ke = _norm_angle(ksa), _norm_angle(kea)
                # An arc is DIRECTIONAL (CCW start->end). Two arcs on the same
                # circle are the same only when their start AND end match --
                # NOT when swapped: 0->180 (top half) and 180->360 (bottom
                # half) share endpoints but are different arcs. A true stacked
                # duplicate has identical start and end.
                same = (abs(s - ks) <= ang_tol and abs(e - ke) <= ang_tol)
                if same:
                    dup = True
                    break
        if dup:
            removed += 1
        else:
            kept.append(a)
    return kept, removed


def _split_arcs_at_intersections(arcs, line_segs, circles):
    """Break each arc wherever another entity crosses its interior, the
    symmetric counterpart of the line splitter.

    ``arcs`` is a list of ``(cx, cy, r, start_deg, end_deg, layer)``. Cutters
    are the given line segments, the OTHER arcs (as their underlying circles),
    and the circles. An arc is subdivided at the angles of those crossings
    that fall strictly inside its CCW sweep -- never moved or trimmed. Returns
    a new list of ``(cx, cy, r, start_deg, end_deg, layer)`` arc pieces plus a
    count of zero-sweep pieces dropped.
    """
    out = []
    dropped = 0
    for i, (cx, cy, r, sa, ea, ly) in enumerate(arcs):
        sweep = (ea - sa) % 360.0
        if sweep <= 1e-9:
            sweep = 360.0               # full-ish arc; treat as complete sweep
        # Collect candidate crossing POINTS on this arc's circle.
        pts = []
        # arc x line
        for (a, b) in line_segs:
            for t in line_circle_params(a, b, cx, cy, r):
                if -1e-9 <= t <= 1 + 1e-9:   # on the (finite) line segment
                    (ax, ay), (bx, by) = a, b
                    pts.append((ax + t * (bx - ax), ay + t * (by - ay)))
        # arc x other arcs
        for j, (ox, oy, orr, osa, oea, _l) in enumerate(arcs):
            if j == i:
                continue
            same_circle = (abs(ox - cx) <= 1e-4 and abs(oy - cy) <= 1e-4
                           and abs(orr - r) <= 1e-4)
            if same_circle:
                # Co-circular arcs never "cross" (circle_circle_points returns
                # nothing for a coincident circle), but a shorter arc nested in
                # a longer one must still break the longer one at its ENDPOINTS
                # -- otherwise the long arc runs through those junctions
                # undivided (the fillet-overlap case). Add the other arc's two
                # endpoints as candidate cut points.
                for ang in (osa, oea):
                    rad = math.radians(ang)
                    pts.append((cx + r * math.cos(rad),
                                cy + r * math.sin(rad)))
                continue
            for (px, py) in circle_circle_points(cx, cy, r, ox, oy, orr):
                # Keep only points that also lie on the OTHER arc's sweep.
                oang = math.degrees(math.atan2(py - oy, px - ox))
                if ang_in(oang, osa, oea):
                    pts.append((px, py))
        # arc x circles (full circles cross the whole ring)
        for (ox, oy, orr) in circles:
            for (px, py) in circle_circle_points(cx, cy, r, ox, oy, orr):
                pts.append((px, py))

        # Convert crossing points to sweep-relative angles strictly interior.
        rels = []
        for (px, py) in pts:
            ang = math.degrees(math.atan2(py - cy, px - cx))
            rel = (ang - sa) % 360.0
            if TOL * 360.0 < rel < sweep - TOL * 360.0:
                rels.append(rel)
        rels.sort()
        # Dedupe near-equal angles (coincident crossings -> one break).
        deduped = []
        for rel in rels:
            if not deduped or (rel - deduped[-1]) > 1e-4:
                deduped.append(rel)
        bounds = [0.0] + deduped + [sweep]
        for k in range(len(bounds) - 1):
            w = bounds[k + 1] - bounds[k]
            if w <= 1e-6:
                dropped += 1
                continue
            out.append((cx, cy, r, _norm_angle(sa + bounds[k]),
                        _norm_angle(sa + bounds[k + 1]), ly))
    return out, dropped


def _split_circles_at_intersections(circles, line_segs, arcs):
    """Break each full CIRCLE into ARC pieces at the points where other
    geometry crosses its ring, so each piece is independently selectable /
    chainable. A circle with NO intersections is left whole (returned in the
    ``kept_circles`` list) -- we only subdivide circles that actually have
    vertices on them, never blindly quarter every circle.

    ``circles`` is ``[(cx, cy, r, layer), ...]``; cutters are the line
    segments and the arcs. Returns ``(arc_pieces, kept_circles)`` where
    ``arc_pieces`` is ``[(cx, cy, r, start_deg, end_deg, layer), ...]`` and
    ``kept_circles`` keeps the ``(cx, cy, r, layer)`` shape.
    """
    arc_pieces = []
    kept_circles = []
    for (cx, cy, r, ly) in circles:
        angs = []
        # circle x lines
        for (a, b) in line_segs:
            for t in line_circle_params(a, b, cx, cy, r):
                if -1e-9 <= t <= 1 + 1e-9:
                    (ax, ay), (bx, by) = a, b
                    px, py = ax + t * (bx - ax), ay + t * (by - ay)
                    angs.append(math.degrees(math.atan2(py - cy, px - cx)))
        # circle x arcs. A co-circular arc (same centre+radius) never "crosses"
        # this ring, but its ENDPOINTS are real vertices on it, so the circle
        # must be cut there (same as the arc splitter's co-circular case).
        # A non-co-circular arc contributes its genuine crossing points.
        for (ox, oy, orr, osa, oea, _l) in arcs:
            if abs(ox - cx) <= 1e-4 and abs(oy - cy) <= 1e-4 \
                    and abs(orr - r) <= 1e-4:
                for ang in (osa, oea):
                    angs.append(ang)
                continue
            for (px, py) in circle_circle_points(cx, cy, r, ox, oy, orr):
                oang = math.degrees(math.atan2(py - oy, px - ox))
                if ang_in(oang, osa, oea):
                    angs.append(math.degrees(math.atan2(py - cy, px - cx)))
        # circle x other circles
        for (ox, oy, orr, _l) in circles:
            if abs(ox - cx) <= 1e-4 and abs(oy - cy) <= 1e-4 \
                    and abs(orr - r) <= 1e-4:
                continue
            for (px, py) in circle_circle_points(cx, cy, r, ox, oy, orr):
                angs.append(math.degrees(math.atan2(py - cy, px - cx)))

        # Normalise, sort and dedupe the cut angles.
        norm = sorted(_norm_angle(a) for a in angs)
        cuts = []
        for a in norm:
            if not cuts or (a - cuts[-1]) > 1e-3:
                cuts.append(a)
        # Merge an angle near 360 back onto the 0 cut (same point).
        if cuts and (360.0 - cuts[-1]) < 1e-3:
            cuts.pop()

        if not cuts:
            kept_circles.append((cx, cy, r, ly))   # no vertices -> stay a circle
            continue
        # Build CCW arc pieces between consecutive cut angles, wrapping around.
        ring = cuts + [cuts[0] + 360.0]
        for k in range(len(ring) - 1):
            sa = _norm_angle(ring[k])
            ea = _norm_angle(ring[k + 1])
            if ((ea - sa) % 360.0) <= 1e-6:
                continue
            arc_pieces.append((cx, cy, r, sa, ea, ly))
    return arc_pieces, kept_circles


def _build_output_doc(doc, new_lines, arcs, circles, fitted_arcs):
    """Create a fresh ezdxf document carrying the cleaned geometry: the split
    lines, the original arcs/circles, and any spline-fitted arcs. Copies the
    source's DXF version, units and layer table."""
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
    return ndoc


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
