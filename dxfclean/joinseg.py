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
# Endpoint coincidence tolerance (drawing units). Biarc-fitted arc endpoints
# carry floating-point error well above 1e-4, and two segments that visibly
# meet can differ by ~1e-3..1e-2 after fitting, so 1e-4 wrongly rejected real
# chains. 1e-3 mm is still far tighter than any CAD/CNC positioning tolerance.
JOIN_TOL = 1e-3


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

    The chain grows from BOTH ends: the first entity can sit anywhere in the
    path, and neighbours are attached at whichever end they meet, flipping an
    entity's orientation (and negating its bulge) when it joins reversed. A
    previous version only extended forward from item 0's tail, so a selection
    whose first entity was interior was wrongly rejected.
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
    used[0] = True
    sp, ep_, b = items[0]
    # A deque of (point, bulge_to_next). We grow at both the head and the tail.
    chain = [(sp, b), (ep_, 0.0)]

    def head():
        return chain[0][0]

    def tail():
        return chain[-1][0]

    # Repeatedly attach any unused entity that meets either open end.
    progress = True
    while progress and not all(used):
        progress = False
        for j in range(len(items)):
            if used[j]:
                continue
            q0, q1, qb = items[j]
            t = tail()
            h = head()
            # --- attach at the TAIL ---
            if _dist(t, q0) <= tol:
                # tail -> q0..q1 ; bulge from tail onward becomes qb
                chain[-1] = (chain[-1][0], qb)
                chain.append((q1, 0.0))
                used[j] = True; progress = True; break
            if _dist(t, q1) <= tol:
                chain[-1] = (chain[-1][0], -qb)   # entity reversed
                chain.append((q0, 0.0))
                used[j] = True; progress = True; break
            # --- attach at the HEAD ---
            if _dist(h, q1) <= tol:
                # q0..q1 -> head ; bulge from q0 to head is qb
                chain.insert(0, (q0, qb))
                used[j] = True; progress = True; break
            if _dist(h, q0) <= tol:
                chain.insert(0, (q1, -qb))        # entity reversed
                used[j] = True; progress = True; break

    if not all(used):
        return None       # gap / disjoint / branching selection
    return chain
