"""Join adjacent cleaned entities into one continuous polyline chain.

For the ProtoTRAK chaining workflow: several adjacent line/arc segments that
form an unbroken path are fused into a single LWPOLYLINE so the control chains
the whole run in ONE pick instead of one pick per segment.

Each selected entity is reduced to an ordered list of
``(point, bulge_to_next)`` vertices. A LINE contributes a zero bulge; an ARC
contributes the DXF bulge  b = tan(sweep/4)  (signed: + for CCW, - for CW).
``order_chain`` walks the entities end-to-end, flipping each as needed, and
refuses a selection that is not a single connected path.

Pure geometry -- no DXF or GUI dependencies; the caller builds the actual
LWPOLYLINE from the returned vertex list.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

Vec = Tuple[float, float]
JOIN_TOL = 1e-4   # endpoint coincidence tolerance (drawing units)


def _dist(a: Vec, b: Vec) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _arc_point(cx, cy, r, deg) -> Vec:
    rad = math.radians(deg)
    return (cx + r * math.cos(rad), cy + r * math.sin(rad))


def _arc_endpoints_and_bulge(geom):
    """For an ('arc', cx, cy, r, start_deg, end_deg) tuple return
    (start_pt, end_pt, bulge) where the arc runs CCW start->end (DXF)."""
    _, cx, cy, r, sa, ea = geom
    p0 = _arc_point(cx, cy, r, sa)
    p1 = _arc_point(cx, cy, r, ea)
    sweep = (ea - sa) % 360.0           # CCW sweep magnitude in [0,360)
    bulge = math.tan(math.radians(sweep) / 4.0)   # + for CCW
    return p0, p1, bulge


def _endpoints(geom):
    """Return (p_start, p_end, bulge_start_to_end) for a line/arc geom."""
    if geom[0] == "line":
        _, p0, p1 = geom
        return (p0, p1, 0.0)
    if geom[0] == "arc":
        return _arc_endpoints_and_bulge(geom)
    return None


def order_chain(geoms, tol: float = JOIN_TOL):
    """Order the selected geoms into one connected chain.

    Returns a list of ``(point, bulge_to_next)`` vertices (bulge of the LAST
    vertex is 0), or None if the selection is NOT a single unbroken path
    (disjoint, branching, or with a gap larger than ``tol``).
    """
    items = []
    for g in geoms:
        ep = _endpoints(g)
        if ep is None:
            return None
        items.append(ep)      # (p0, p1, bulge)
    if len(items) < 2:
        return None

    used = [False] * len(items)
    # Start from item 0 in its given orientation.
    used[0] = True
    p0, p1, b = items[0]
    chain = [(p0, b)]         # (vertex, bulge_to_next)
    tail = p1                 # current open end

    for _ in range(len(items) - 1):
        found = False
        for j, (q0, q1, qb) in enumerate(items):
            if used[j]:
                continue
            if _dist(tail, q0) <= tol:
                chain.append((q0, qb))
                tail = q1
                used[j] = True
                found = True
                break
            if _dist(tail, q1) <= tol:
                # entity runs the other way: flip it (reverse bulge sign)
                chain.append((q1, -qb))
                tail = q0
                used[j] = True
                found = True
                break
        if not found:
            return None       # gap / disjoint selection
    if not all(used):
        return None
    chain.append((tail, 0.0))  # closing vertex, no bulge after it
    return chain
