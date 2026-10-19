"""Collect the numbered coordinate points of a cleaned DXF.

Given a cleaned document (lines already broken at every intersection, plus
arcs and circles), this returns a de-duplicated, deterministically numbered
list of the geometry's notable points:

* **line endpoints / vertices** -- every endpoint of every output segment;
  because the cleanup step breaks lines at every crossing, this set already
  contains all line-line intersection points;
* **line <-> arc / line <-> circle intersections** -- the point where a line
  meets a curve (computed with the same math the splitter uses);
* **arc endpoints and circle "vertices"** -- the two sweep endpoints of each
  arc, and the four quadrant points + centre of each circle, so curved
  features are represented in the table too.

All points are de-duplicated within the project tolerance (coincident points
-- e.g. a corner shared by three segments -- collapse to ONE row) and then
numbered 1, 2, 3, ... in a stable order (ascending Y, then ascending X), so
the same drawing always yields the same numbering.

This module only READS geometry; it never changes the cleanup result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from .core import TOL, ang_in, line_circle_params


@dataclass(frozen=True)
class Point:
    """One numbered coordinate in the table."""

    index: int          # 1-based label shown to the user
    x: float
    y: float
    kinds: Tuple[str, ...]   # why this point exists, e.g. ("vertex", "arc-int")


# Absolute snap distance for de-duplication. The core uses a *relative*
# tolerance while splitting one line; for merging points across the whole
# drawing we need an absolute grid. 1e-6 drawing units is well below any
# machinable feature and safely above float noise.
_SNAP = 1e-6


def _curve_line_intersections(line_segs, arcs, circles):
    """Points where a line segment crosses an arc (on its sweep) or circle."""
    out = []
    for (a, b) in line_segs:
        (ax, ay), (bx, by) = a, b
        dx, dy = bx - ax, by - ay
        for (cx, cy, r, sa, ea, _ly) in arcs:
            for t in line_circle_params(a, b, cx, cy, r):
                if -_SNAP <= t <= 1 + _SNAP:
                    px, py = ax + t * dx, ay + t * dy
                    ang = math.degrees(math.atan2(py - cy, px - cx))
                    if ang_in(ang, sa, ea):
                        out.append((px, py, "arc-int"))
        for (cx, cy, r, _ly) in circles:
            for t in line_circle_params(a, b, cx, cy, r):
                if -_SNAP <= t <= 1 + _SNAP:
                    out.append((ax + t * dx, ay + t * dy, "circle-int"))
    return out


def _arc_endpoints(arcs):
    out = []
    for (cx, cy, r, sa, ea, _ly) in arcs:
        for ang in (sa, ea):
            rad = math.radians(ang)
            out.append((cx + r * math.cos(rad), cy + r * math.sin(rad),
                        "arc-end"))
    return out


def _circle_points(circles):
    out = []
    for (cx, cy, r, _ly) in circles:
        out.append((cx, cy, "circle-center"))
        for ang in (0.0, 90.0, 180.0, 270.0):
            rad = math.radians(ang)
            out.append((cx + r * math.cos(rad), cy + r * math.sin(rad),
                        "circle-quad"))
    return out


def collect_points_from_report(report, arcs, circles, extra=None) -> List[Point]:
    """Build the numbered point list from a :class:`CleanReport` and the
    cleaned arcs/circles.

    ``report.out_lines`` is the list of cleaned ``(p0, p1, layer)`` segments.
    ``arcs``   -- list of ``(cx, cy, r, start_angle, end_angle, layer)``.
    ``circles``-- list of ``(cx, cy, r, layer)``.
    ``extra``  -- optional list of ``(x, y, kind)`` points to fold in (e.g.
                  native DXF ``POINT`` entities).
    """
    line_segs = [(p0, p1) for (p0, p1, _ly) in report.out_lines]

    raw: List[Tuple[float, float, str]] = []
    # vertices = every endpoint of every cleaned segment
    for (p0, p1) in line_segs:
        raw.append((p0[0], p0[1], "vertex"))
        raw.append((p1[0], p1[1], "vertex"))
    raw.extend(_curve_line_intersections(line_segs, arcs, circles))
    raw.extend(_arc_endpoints(arcs))
    raw.extend(_circle_points(circles))
    if extra:
        raw.extend(extra)

    # De-duplicate on a snap grid, merging the "kinds" of coincident points.
    merged: dict = {}
    for (x, y, kind) in raw:
        key = (round(x / _SNAP), round(y / _SNAP))
        if key in merged:
            mx, my, kinds = merged[key]
            kinds.add(kind)
        else:
            merged[key] = (x, y, {kind})

    # Stable numbering: ascending Y, then ascending X.
    items = sorted(merged.values(), key=lambda v: (round(v[1], 6),
                                                    round(v[0], 6)))
    points = []
    for i, (x, y, kinds) in enumerate(items, start=1):
        points.append(Point(index=i, x=x, y=y,
                            kinds=tuple(sorted(kinds))))
    return points


def collect_points(doc) -> Tuple[List[Point], "object"]:
    """Convenience: clean ``doc`` and return ``(points, report)``.

    Cleans a copy via :func:`dxfclean.core.clean_doc` and collects points from
    the result, so the numbering matches the machinable output exactly. Also
    folds in any native ``POINT`` entities from the SOURCE drawing (the cleaner
    drops those as unhandled, but they are real coordinates the operator placed
    and belong in the table).
    """
    from .core import clean_doc

    # Native POINT entities from the source (cleaner discards them).
    dxf_points = []
    try:
        for e in doc.modelspace():
            if e.dxftype() == "POINT":
                loc = e.dxf.location
                dxf_points.append((loc.x, loc.y, "dxf-point"))
    except Exception:
        pass

    ndoc, report = clean_doc(doc)
    nmsp = ndoc.modelspace()
    arcs, circles = [], []
    for e in nmsp:
        t = e.dxftype()
        if t == "ARC":
            arcs.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius,
                         e.dxf.start_angle, e.dxf.end_angle, e.dxf.layer))
        elif t == "CIRCLE":
            circles.append((e.dxf.center.x, e.dxf.center.y, e.dxf.radius,
                            e.dxf.layer))
    return (collect_points_from_report(report, arcs, circles,
                                       extra=dxf_points), report)


def points_as_table(points: List[Point]) -> str:
    """Render points as a fixed-width ``#  | X | Y`` text table."""
    rows = ["  #  |        X        |        Y        | kind",
            "-----+-----------------+-----------------+------"]
    for p in points:
        rows.append("%4d | %15.6f | %15.6f | %s"
                     % (p.index, p.x, p.y, ",".join(p.kinds)))
    return "\n".join(rows)


def points_as_csv(points: List[Point]) -> str:
    """Render points as CSV: ``index,x,y,kind``."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["index", "x", "y", "kind"])
    for p in points:
        w.writerow([p.index, "%.6f" % p.x, "%.6f" % p.y, "|".join(p.kinds)])
    return buf.getvalue()


def write_csv(points: List[Point], path: str) -> str:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(points_as_csv(points))
    return path
