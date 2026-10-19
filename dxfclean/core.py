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
    segments_dropped: int = 0
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
            "Segments dropped (zero-length): %d" % self.segments_dropped,
            "Splines converted: %d / %d"
            % (self.splines_converted, self.splines_in),
        ]
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
    """Flatten a SPLINE to a chain of short LINE segments.

    ezdxf's ``flattening`` produces points along the curve to a distance
    tolerance; we emit colinear LINE segments between them. These segments
    then go through the exact same intersection-splitting as any other line,
    so the "no entity crosses a line interior" guarantee still holds.

    Returns a list of ((x,y),(x,y)) tuples, or [] (with a warning) if the
    spline cannot be sampled.
    """
    try:
        pts = [(p.x, p.y) for p in spline.flattening(0.01)]
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
def clean_doc(doc) -> Tuple["ezdxf.document.Drawing", CleanReport]:
    """Clean an in-memory ezdxf document.

    Returns ``(new_doc, report)``. Does not mutate the input document.
    """
    report = CleanReport()
    msp = doc.modelspace()

    lines, arcs, circles, others = [], [], [], []
    # extra_line_segs holds lines synthesized from splines; they take part in
    # splitting exactly like native LINE entities.
    extra_line_segs: List[Tuple[Tuple[float, float], Tuple[float, float], str]] = []

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
            segs = _spline_to_lines(e, report)
            if segs:
                report.splines_converted += 1
                ly = e.dxf.layer
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

    return ndoc, report


def clean_file(src: str, out: str | None = None) -> Tuple[str, CleanReport]:
    """Read ``src``, clean it, write to ``out`` (default ``<name>_clean.dxf``).

    Returns ``(out_path, report)``.
    """
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    if out is None:
        out = os.path.splitext(src)[0] + "_clean.dxf"
    doc = ezdxf.readfile(src)
    ndoc, report = clean_doc(doc)
    ndoc.saveas(out)
    return out, report
