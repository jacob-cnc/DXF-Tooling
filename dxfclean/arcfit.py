"""Fit circular ARCS (and lines) to a spline -- the spline->arc "moonshot".

Converts a DXF SPLINE into a minimal G1-continuous chain of circular arcs
(plus line segments where the curve is straight), so the cleaned output maps
cleanly to CNC G2/G3 moves and gives the ProtoTRAK chaining workflow few
segments to click -- instead of the many short line segments the adaptive
*line* flattener produces.

Method: biarc interpolation with adaptive subdivision (Walton-Meek / Sabin
incenter joint). For a span with endpoints A0,A1 and unit tangents T0,T1:

  * intersect the tangent lines at V; the join G is the INCENTER of the
    triangle (A0, V, A1):
        G = (a0*A0 + aV*V + a1*A1) / (a0 + aV + a1)
    with a0=|V-A1|, aV=|A1-A0|, a1=|A0-V| (sides opposite each vertex).
  * each arc's centre/radius, tangent to T at endpoint A, with N = rot90(T):
        lambda = |G-A|^2 / (2 (G-A).N),   C = A + lambda*N,   r = |lambda|

We sample the TRUE curve over the span and measure the max distance to the
fitted biarc; if it exceeds the tolerance we split the span and recurse.
Near-straight spans become a LINE; spans are pre-split at inflection points
(a single biarc spans at most one curvature sign).

This module only PRODUCES geometry primitives; it does not read or write DXF.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

Vec = Tuple[float, float]


@dataclass
class ArcSeg:
    """A fitted circular arc (CCW from start to end around centre)."""
    center: Vec
    radius: float
    start: Vec
    end: Vec
    cw: bool          # True if the sweep is clockwise


@dataclass
class LineSeg:
    """A fitted straight segment."""
    start: Vec
    end: Vec


# --------------------------------------------------------------------------
# small vector helpers
# --------------------------------------------------------------------------
def _sub(a, b): return (a[0] - b[0], a[1] - b[1])
def _add(a, b): return (a[0] + b[0], a[1] + b[1])
def _mul(a, s): return (a[0] * s, a[1] * s)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1]
def _cross(a, b): return a[0] * b[1] - a[1] * b[0]
def _norm(a): return math.hypot(a[0], a[1])
def _rot90(a): return (-a[1], a[0])


def _unit(a):
    n = _norm(a)
    return (a[0] / n, a[1] / n) if n > 0 else (0.0, 0.0)


def _line_intersect(p0, d0, p1, d1):
    """Intersection of line p0+s*d0 and p1+r*d1. None if near-parallel."""
    denom = _cross(d0, d1)
    if abs(denom) < 1e-12:
        return None
    w = _sub(p1, p0)
    s = _cross(w, d1) / denom
    return _add(p0, _mul(d0, s))


# --------------------------------------------------------------------------
# single-arc-from-endpoint-and-join (closed form)
# --------------------------------------------------------------------------
def _arc_through(a: Vec, t: Vec, g: Vec) -> Optional[ArcSeg]:
    """Arc from A to G, tangent to unit direction T at A. None if degenerate
    (treat as a line)."""
    n = _rot90(t)                       # endpoint normal
    ga = _sub(g, a)
    denom = 2.0 * _dot(ga, n)
    if abs(denom) < 1e-12:
        return None                     # straight: no finite centre
    lam = _dot(ga, ga) / denom
    c = _add(a, _mul(n, lam))
    r = abs(lam)
    if r < 1e-12 or r > 1e12:
        return None
    # sweep direction: sign of cross(A-C, G-C)
    ca = _sub(a, c)
    cg = _sub(g, c)
    cw = _cross(ca, cg) < 0
    return ArcSeg(center=c, radius=r, start=a, end=g, cw=cw)


def _single_arc(a0, am, a1):
    """Circle through three points -> one ArcSeg from a0 to a1 passing am.
    None if the three points are (near) collinear."""
    ax, ay = a0
    bx, by = am
    cx, cy = a1
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    center = (ux, uy)
    r = _norm(_sub(a0, center))
    if r < 1e-9 or r > 1e12:
        return None
    # sweep direction consistent with a0 -> am -> a1
    cw = _cross(_sub(a0, center), _sub(am, center)) < 0
    arc = ArcSeg(center=center, radius=r, start=a0, end=a1, cw=cw)
    # verify the midpoint lands on the emitted sweep; flip if not.
    if not _on_arc(am, arc):
        arc = ArcSeg(center=center, radius=r, start=a0, end=a1, cw=not cw)
    return arc



def _biarc(a0, t0, a1, t1):
    """Build the incenter biarc for a span. Returns a list of ArcSeg/LineSeg
    (1 or 2 elements), or None if the span should just be a straight line."""
    chord = _sub(a1, a0)
    clen = _norm(chord)
    if clen < 1e-12:
        return None
    # Tangent lines; V is their intersection.
    v = _line_intersect(a0, t0, a1, t1)
    if v is None:
        # parallel tangents -> treat as (near) straight
        return None
    a0_side = _norm(_sub(v, a1))      # opposite A0
    av_side = _norm(_sub(a1, a0))     # opposite V
    a1_side = _norm(_sub(a0, v))      # opposite A1
    s = a0_side + av_side + a1_side
    if s < 1e-12:
        return None
    g = ((a0_side * a0[0] + av_side * v[0] + a1_side * a1[0]) / s,
         (a0_side * a0[1] + av_side * v[1] + a1_side * a1[1]) / s)
    arc1 = _arc_through(a0, t0, g)
    arc2 = _arc_through(a1, t1, g)
    # arc2 is built from A1 toward G; flip it to run G -> A1.
    out = []
    out.append(arc1 if arc1 else LineSeg(a0, g))
    if arc2:
        out.append(ArcSeg(center=arc2.center, radius=arc2.radius,
                          start=g, end=a1, cw=not arc2.cw))
    else:
        out.append(LineSeg(g, a1))
    return out


# --------------------------------------------------------------------------
# deviation of a fitted piece from the true sampled curve
# --------------------------------------------------------------------------
def _dist_to_piece(p, piece) -> float:
    if isinstance(piece, LineSeg):
        return _point_seg_dist(p, piece.start, piece.end)
    # arc: radial distance, but only if the foot is within the sweep;
    # otherwise distance to nearer endpoint.
    c, r = piece.center, piece.radius
    ang = math.atan2(p[1] - c[1], p[0] - c[0])
    foot = (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))
    if _on_arc(foot, piece):
        return abs(_norm(_sub(p, c)) - r)
    return min(_norm(_sub(p, piece.start)), _norm(_sub(p, piece.end)))


def _on_arc(p, arc: ArcSeg) -> bool:
    a0 = math.atan2(arc.start[1] - arc.center[1], arc.start[0] - arc.center[0])
    a1 = math.atan2(arc.end[1] - arc.center[1], arc.end[0] - arc.center[0])
    ap = math.atan2(p[1] - arc.center[1], p[0] - arc.center[0])
    # normalise into CCW/CW sweep
    def nrm(x):
        while x < 0:
            x += 2 * math.pi
        while x >= 2 * math.pi:
            x -= 2 * math.pi
        return x
    if arc.cw:
        a0, a1 = a1, a0
    span = nrm(a1 - a0)
    off = nrm(ap - a0)
    return off <= span + 1e-9


def _point_seg_dist(p, a, b):
    d = _sub(b, a)
    L2 = _dot(d, d)
    if L2 == 0:
        return _norm(_sub(p, a))
    t = max(0.0, min(1.0, _dot(_sub(p, a), d) / L2))
    return _norm(_sub(p, (a[0] + t * d[0], a[1] + t * d[1])))


def _max_deviation(curve_pts, pieces) -> float:
    worst = 0.0
    for p in curve_pts:
        d = min(_dist_to_piece(p, pc) for pc in pieces)
        worst = max(worst, d)
    return worst


# --------------------------------------------------------------------------
# straightness test
# --------------------------------------------------------------------------
def _is_straight(curve_pts, tol) -> bool:
    """True if all sampled points lie within tol of the chord (emit a line)."""
    if len(curve_pts) < 3:
        return True
    a, b = curve_pts[0], curve_pts[-1]
    return all(_point_seg_dist(p, a, b) <= tol for p in curve_pts[1:-1])


# --------------------------------------------------------------------------
# adaptive subdivision driver
# --------------------------------------------------------------------------
def fit_curve(eval_point, eval_tangent, u0, u1, tol,
              max_depth=24, samples=24):
    """Fit a G1 chain of arcs/lines to a parametric planar curve.

    eval_point(u)   -> (x, y) on the curve
    eval_tangent(u) -> unit tangent at u
    [u0, u1]        -- parameter span to fit
    tol             -- max allowed deviation (drawing units)

    Returns a list of ArcSeg / LineSeg.
    """
    def sample(ua, ub, n):
        return [eval_point(ua + (ub - ua) * k / n) for k in range(n + 1)]

    def recurse(ua, ub, depth):
        pts = sample(ua, ub, samples)
        a0, a1 = pts[0], pts[-1]
        # straight?
        if _is_straight(pts, tol):
            return [LineSeg(a0, a1)]
        t0 = eval_tangent(ua)
        t1 = eval_tangent(ub)
        # 1) Try a SINGLE arc through the midpoint first -- cheapest result.
        single = _single_arc(a0, pts[len(pts) // 2], a1)
        if single is not None and _max_deviation(pts, [single]) <= tol:
            return [single]
        # 2) Otherwise a biarc (matches both endpoint tangents, G1).
        pieces = _biarc(a0, t0, a1, t1)
        if pieces is None:
            return [LineSeg(a0, a1)]
        if _max_deviation(pts, pieces) <= tol:
            return pieces
        if depth >= max_depth:
            return pieces
        um = 0.5 * (ua + ub)
        return recurse(ua, um, depth + 1) + recurse(um, ub, depth + 1)

    return recurse(u0, u1, 0)


def _inflection_params(eval_point, u0, u1, samples=64):
    """Parameters where the curve's signed curvature changes sign, so each
    sub-span is single-signed (a biarc spans at most one curvature sign)."""
    us = [u0 + (u1 - u0) * k / samples for k in range(samples + 1)]
    pts = [eval_point(u) for u in us]
    splits = []
    prev = None
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        cr = _cross(_sub(b, a), _sub(c, b))     # signed turn
        s = 0 if abs(cr) < 1e-12 else (1 if cr > 0 else -1)
        if prev is not None and s != 0 and s != prev:
            splits.append(us[i])
        if s != 0:
            prev = s
    return splits


def fit_spline(spline, tol, samples_per_span=24):
    """Fit arcs/lines to an ezdxf SPLINE entity.

    Uses the spline's own construction tool for exact point/tangent
    evaluation. Pre-splits at inflection points. Returns a list of
    ArcSeg / LineSeg, or None if the spline cannot be evaluated.
    """
    try:
        ct = spline.construction_tool()
    except Exception:
        return None
    # Parameter domain (max_t is stable across ezdxf versions; knots is a
    # method in some and an attribute in others).
    try:
        kmin = 0.0
        kmax = float(ct.max_t)
    except Exception:
        kmin, kmax = 0.0, 1.0
    if kmax - kmin < 1e-12:
        return None

    def ep(u):
        p = ct.point(u)
        return (p[0], p[1])

    def et(u):
        # central difference tangent (robust, derivative API varies by version)
        du = (kmax - kmin) * 1e-5
        ua = max(kmin, u - du)
        ub = min(kmax, u + du)
        pa, pb = ct.point(ua), ct.point(ub)
        return _unit((pb[0] - pa[0], pb[1] - pa[1]))

    # pre-split at inflections
    cuts = [kmin] + _inflection_params(ep, kmin, kmax) + [kmax]
    cuts = sorted(set(cuts))
    out = []
    for i in range(len(cuts) - 1):
        out.extend(fit_curve(ep, et, cuts[i], cuts[i + 1], tol,
                             samples=samples_per_span))
    return out
