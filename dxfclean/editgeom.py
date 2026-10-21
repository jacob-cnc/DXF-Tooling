"""Pure geometry for interactive editing: hit-testing and chain splitting.

Extracted out of the Tk GUI so it is independently unit-testable with no
matplotlib or tkinter import. Everything here works on plain tuples:

  * a LINE sub-geom is ``("line", (x0, y0), (x1, y1))``
  * an ARC  sub-geom is ``("arc", cx, cy, r, start_deg, end_deg)`` (CCW DXF
    convention, degrees)

The GUI keeps the matplotlib artist bookkeeping and the actual
``msp.add_line / add_arc / add_lwpolyline`` calls; it calls into here for the
math (distance from a click to a segment/arc/polyline) and for turning a
sub-geom chain into the data a split or join needs.

Bulge convention matches ``joinseg``:  b = tan(sweep / 4), signed + for CCW.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]


# --------------------------------------------------------------------------
# Point helpers
# --------------------------------------------------------------------------
def close(a: Point, b: Point, tol: float = 1e-4) -> bool:
    """Point equality within ``tol``."""
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def dist2(a: Point, b: Point) -> float:
    """Squared distance between two (x, y) points."""
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


# --------------------------------------------------------------------------
# Distance from a click to geometry (hit-testing)
# --------------------------------------------------------------------------
def point_seg_distance(px: float, py: float, a: Point, b: Point) -> float:
    """Shortest distance from point (px, py) to the segment a-b."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def angle_in_sweep(deg: float, start_deg: float, end_deg: float) -> bool:
    """True if angle ``deg`` lies on the CCW sweep start->end (DXF convention)."""
    a = deg % 360.0
    s = start_deg % 360.0
    e = end_deg % 360.0
    if s <= e:
        return s - 1e-9 <= a <= e + 1e-9
    return a >= s - 1e-9 or a <= e + 1e-9


def point_arc_distance(px: float, py: float, cx: float, cy: float, r: float,
                       start_deg: float, end_deg: float) -> float:
    """Distance from (px, py) to an arc. If the click's angle is within the
    sweep it is the radial distance ``|dist-to-centre - r|``; otherwise it is
    the distance to the nearer arc endpoint."""
    d = math.hypot(px - cx, py - cy)
    ang = math.degrees(math.atan2(py - cy, px - cx))
    if angle_in_sweep(ang, start_deg, end_deg):
        return abs(d - r)
    best: Optional[float] = None
    for a_deg in (start_deg, end_deg):
        rad = math.radians(a_deg)
        ex, ey = cx + r * math.cos(rad), cy + r * math.sin(rad)
        dd = math.hypot(px - ex, py - ey)
        best = dd if best is None else min(best, dd)
    return best if best is not None else abs(d - r)


def sub_distance(px: float, py: float, sub) -> float:
    """Distance from (px, py) to one line/arc sub-geom tuple."""
    if sub[0] == "line":
        return point_seg_distance(px, py, sub[1], sub[2])
    _, cx, cy, r, sa, ea = sub
    return point_arc_distance(px, py, cx, cy, r, sa, ea)


def poly_distance(px: float, py: float, subs: Sequence) -> Optional[float]:
    """Shortest distance from (px, py) to any sub-geom of a joined polyline."""
    best: Optional[float] = None
    for sub in subs:
        d = sub_distance(px, py, sub)
        if best is None or d < best:
            best = d
    return best


# --------------------------------------------------------------------------
# Chain <-> DXF data
# --------------------------------------------------------------------------
def sub_endpoints_bulge(sub) -> Tuple[Point, Point, float]:
    """Return ``(start_pt, end_pt, bulge_start_to_end)`` for one sub-geom."""
    if sub[0] == "line":
        _, p0, p1 = sub
        return (p0[0], p0[1]), (p1[0], p1[1]), 0.0
    _, cx, cy, r, sa, ea = sub
    a = (cx + r * math.cos(math.radians(sa)), cy + r * math.sin(math.radians(sa)))
    b = (cx + r * math.cos(math.radians(ea)), cy + r * math.sin(math.radians(ea)))
    sweep = (ea - sa) % 360.0
    bulge = math.tan(math.radians(sweep) / 4.0)   # + for CCW
    return a, b, bulge


def subs_to_lwpoly_points(subs: Sequence,
                          tol2: float = 1e-10) -> List[Tuple[float, float,
                                                             float, float,
                                                             float]]:
    """Turn an ordered chain of line/arc sub-geoms into LWPOLYLINE vertices.

    Returns a list of ``(x, y, start_width, end_width, bulge)`` tuples ready
    for ``msp.add_lwpolyline(pts, format="xyseb")``. Each sub is oriented to
    keep the chain continuous (flipping and negating its bulge when joined
    reversed), so the caller may pass subs in path order without pre-aligning
    their individual directions.
    """
    pts: List[List[float]] = []
    for sub in subs:
        a, b, bulge = sub_endpoints_bulge(sub)
        # Orient so the chain is continuous: the first sub sets the direction.
        if pts and dist2((pts[-1][0], pts[-1][1]), a) > tol2 \
                and dist2((pts[-1][0], pts[-1][1]), b) <= tol2:
            a, b = b, a
            bulge = -bulge
        if not pts:
            pts.append([a[0], a[1], 0.0, 0.0, bulge])
        else:
            pts[-1][4] = bulge
        pts.append([b[0], b[1], 0.0, 0.0, 0.0])
    return [tuple(p) for p in pts]


def split_chain_subs(subs: Sequence, vertex_index: int):
    """Split a sub-geom chain at the interior vertex ``vertex_index`` into
    ``(left_subs, right_subs)``.

    Sub ``j`` spans the chain vertices ``j -> j+1``, so cutting at vertex
    ``vi`` yields ``subs[:vi]`` on the left and ``subs[vi:]`` on the right.
    Returns ``(None, None)`` when the index is not a valid interior cut.
    """
    n_verts = len(subs) + 1
    if vertex_index <= 0 or vertex_index >= n_verts - 1:
        return None, None
    return list(subs[:vertex_index]), list(subs[vertex_index:])


def chain_vertices(subs: Sequence) -> List[Point]:
    """The ordered vertex list of a chain (one more than the sub count)."""
    pts = subs_to_lwpoly_points(subs)
    return [(p[0], p[1]) for p in pts]
