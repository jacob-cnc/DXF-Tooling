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
    vertex is 0), or None if NO chain of >=2 entities can be formed. Kept for
    back-compat; prefer ``longest_chain`` which also reports leftovers.
    """
    chain, _used, leftover, _reason = longest_chain(geoms, tol)
    if chain is None or leftover:
        # Strict callers want all-or-nothing; a leftover means not a clean path.
        return chain if (chain is not None and not leftover) else None
    return chain


def _branch_nodes(items, tol):
    """Return the count of entity-endpoints incident on each clustered node,
    so a node touched by >=3 endpoints is a branch (fork)."""
    nodes = []          # representative points
    counts = []
    def node_of(p):
        for i, q in enumerate(nodes):
            if _dist(p, q) <= tol:
                return i
        nodes.append(p); counts.append(0)
        return len(nodes) - 1
    for (p0, p1, _b) in items:
        counts[node_of(p0)] += 1
        counts[node_of(p1)] += 1
    return nodes, counts


def longest_chain(geoms, tol: float = JOIN_TOL):
    """Build the LONGEST single connected path through the selected geoms.

    Returns ``(chain, used_geoms, leftover_geoms, reason)`` where:
      * ``chain``   -- list of ``(point, bulge_to_next)`` vertices, or None if
                       fewer than 2 entities could be chained;
      * ``used_geoms``    -- the geoms that went into the chain, in input form;
      * ``leftover_geoms``-- geoms NOT in the chain (a branch stub, a
                             disconnected piece, or the far side of a fork);
      * ``reason``  -- short human string describing any leftover / failure.

    Policy: a fork (a point where 3+ selected segments meet) cannot be one
    polyline, so we take the longest path THROUGH it and leave the branch out,
    rather than rejecting the whole selection. A genuinely disconnected piece
    is likewise left over.
    """
    items = []
    for g in geoms:
        ep = _endpoints(g)
        if ep is None:
            return None, [], list(geoms), "a selected item is not a line or arc"
        items.append(ep)      # (p0, p1, bulge)
    if len(items) < 2:
        return None, [], list(geoms), "select at least two touching segments"

    _nodes, counts = _branch_nodes(items, tol)
    has_fork = any(c >= 3 for c in counts)

    # Greedily grow a chain from item 0 outward at BOTH ends. At a fork we stop
    # growing that end (ambiguous), which naturally leaves the branch out.
    def build_from(seed):
        used = [False] * len(items)
        used[seed] = True
        sp, ep_, b = items[seed]
        chain = [(sp, b), (ep_, 0.0)]
        progress = True
        while progress:
            progress = False
            tailp, headp = chain[-1][0], chain[0][0]
            # candidates meeting each open end
            for j in range(len(items)):
                if used[j]:
                    continue
                q0, q1, qb = items[j]
                if _dist(tailp, q0) <= tol:
                    chain[-1] = (chain[-1][0], qb); chain.append((q1, 0.0))
                    used[j] = True; progress = True; break
                if _dist(tailp, q1) <= tol:
                    chain[-1] = (chain[-1][0], -qb); chain.append((q0, 0.0))
                    used[j] = True; progress = True; break
                if _dist(headp, q1) <= tol:
                    chain.insert(0, (q0, qb)); used[j] = True
                    progress = True; break
                if _dist(headp, q0) <= tol:
                    chain.insert(0, (q1, -qb)); used[j] = True
                    progress = True; break
        return chain, used

    # Try growing from every seed; keep the chain that consumes the most edges.
    best = None
    for s in range(len(items)):
        chain, used = build_from(s)
        n = sum(used)
        if best is None or n > best[0]:
            best = (n, chain, used)
    n_used, chain, used = best
    if n_used < 2:
        return None, [], list(geoms), "the segments do not touch end-to-end"

    used_geoms = [geoms[i] for i in range(len(items)) if used[i]]
    leftover = [geoms[i] for i in range(len(items)) if not used[i]]
    if leftover:
        if has_fork:
            reason = ("%d segment(s) form a branch off the main path and "
                      "can't be part of one polyline -- joined the longest "
                      "run and left the branch out" % len(leftover))
        else:
            reason = ("%d segment(s) are not connected to the main run and "
                      "were left out" % len(leftover))
    else:
        reason = ""
    return chain, used_geoms, leftover, reason
