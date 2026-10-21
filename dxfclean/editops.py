"""DXF entity operations for interactive join/split -- the modelspace surgery
that used to sit inside the Tk App class.

These functions take an ezdxf modelspace and plain geom tuples; they contain no
Tk or matplotlib code. The GUI keeps the user-facing parts (message boxes,
report text, canvas refresh) and calls in here to mutate the document.

Geom tuple shapes (same as editgeom / joinseg):
  * LINE sub-geom : ``("line", (x0, y0), (x1, y1))``
  * ARC  sub-geom : ``("arc", cx, cy, r, start_deg, end_deg)``
  * a chain vertex list is ``[(point, bulge_to_next), ...]`` (last bulge 0)
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from . import editgeom as eg
from .joinseg import longest_chain


# --------------------------------------------------------------------------
# Matching a live cleaned entity back to a geom tuple
# --------------------------------------------------------------------------
def entity_matches_any(e, geoms: Sequence) -> bool:
    """True if a live cleaned LINE/ARC entity ``e`` corresponds to one of
    ``geoms`` (order-independent for lines)."""
    t = e.dxftype()
    for g in geoms:
        if g[0] == "line" and t == "LINE":
            p0, p1 = g[1], g[2]
            s = (e.dxf.start.x, e.dxf.start.y)
            en = (e.dxf.end.x, e.dxf.end.y)
            if (eg.close(s, p0) and eg.close(en, p1)) or \
               (eg.close(s, p1) and eg.close(en, p0)):
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


def polyline_matches(e, verts_list: Sequence) -> bool:
    """True if polyline entity ``e`` has one of the given vertex sequences,
    matched endpoint-to-endpoint and order-independent (forward or reversed)."""
    try:
        epts = [(p[0], p[1]) for p in e.get_points("xy")]
    except Exception:
        return False
    for verts in verts_list:
        if len(epts) != len(verts):
            continue
        if all(eg.close(epts[k], verts[k]) for k in range(len(verts))) or \
           all(eg.close(epts[k], verts[-1 - k]) for k in range(len(verts))):
            return True
    return False


# --------------------------------------------------------------------------
# Emit sub-geoms as DXF entities
# --------------------------------------------------------------------------
def emit_subs(msp, subs: Sequence, layer: str) -> None:
    """Emit a chain of sub-geoms as one LWPOLYLINE (>=2 subs) or a plain
    LINE/ARC (exactly 1 sub). Bulge math lives in editgeom."""
    if not subs:
        return
    attribs = {"layer": layer}
    if len(subs) == 1:
        s = subs[0]
        if s[0] == "line":
            _, p0, p1 = s
            msp.add_line(p0, p1, dxfattribs=attribs)
        else:
            _, cx, cy, r, sa, ea = s
            msp.add_arc((cx, cy), r, sa, ea, dxfattribs=attribs)
        return
    pts = eg.subs_to_lwpoly_points(subs)
    msp.add_lwpolyline(pts, format="xyseb", dxfattribs=attribs)


# --------------------------------------------------------------------------
# Join: fuse / extend a chain
# --------------------------------------------------------------------------
class JoinResult:
    """Outcome of :func:`join_in_modelspace`.

    ``ok``        -- a polyline was written.
    ``vertices``  -- the new chain's vertex points (for seam/endpoint dots).
    ``n_used``    -- how many segments were fused.
    ``extended``  -- True when an existing child was grown (vs a fresh join).
    ``leftover``  -- True when a branch/disconnected piece was left in place.
    ``reason``    -- human string describing any leftover.
    ``error``     -- set instead of ok when the selection could not be joined;
                     ``error_kind`` is 'too_few' or 'not_connected'.
    """

    def __init__(self, ok=False, vertices=None, n_used=0, extended=False,
                 leftover=False, reason="", error="", error_kind=""):
        self.ok = ok
        self.vertices = vertices or []
        self.n_used = n_used
        self.extended = extended
        self.leftover = leftover
        self.reason = reason
        self.error = error
        self.error_kind = error_kind


def join_in_modelspace(msp, sel_geoms: Sequence, polylines: Sequence,
                       geom_key) -> JoinResult:
    """Fuse the selected geoms into one LWPOLYLINE, extending any selected
    joined children in the process.

    Parameters
    ----------
    msp        : ezdxf modelspace to mutate.
    sel_geoms  : the selected geom tuples; a joined child is ``("poly", i)``.
    polylines  : the GUI's ``_polylines`` cache; each entry has ``subs`` and
                 ``verts`` keys.
    geom_key   : callable turning a geom tuple into its de-dup signature.

    Returns a :class:`JoinResult`. On success the modelspace has the old
    consumed entities removed and a new LWPOLYLINE added.
    """
    loose = [g for g in sel_geoms if g and g[0] != "poly"]
    poly_idx = [g[1] for g in sel_geoms if g and g[0] == "poly"]
    poly_subs: List = []
    for i in poly_idx:
        if 0 <= i < len(polylines):
            poly_subs.extend(polylines[i]["subs"])
    members = loose + poly_subs
    if len(members) < 2 or (not loose and len(poly_idx) < 2):
        return JoinResult(error="too_few", error_kind="too_few")

    chain, used_geoms, leftover, reason = longest_chain(members)
    if chain is None:
        return JoinResult(error=reason or "not connected",
                          error_kind="not_connected", reason=reason)

    layer = "0"
    to_delete = []
    for e in msp:
        if e.dxftype() in ("LINE", "ARC") and entity_matches_any(e, used_geoms):
            to_delete.append(e)
            try:
                layer = e.dxf.layer
            except Exception:
                pass
    used_set = set(geom_key(g) for g in used_geoms)
    consumed_poly_verts = []
    for i in poly_idx:
        subs = polylines[i]["subs"]
        if any(geom_key(s) in used_set for s in subs):
            consumed_poly_verts.append(polylines[i]["verts"])
    for e in list(msp):
        if e.dxftype() in ("LWPOLYLINE", "POLYLINE"):
            if polyline_matches(e, consumed_poly_verts):
                to_delete.append(e)
    for e in to_delete:
        try:
            msp.delete_entity(e)
        except Exception:
            pass

    verts = [v[0] for v in chain]
    pts = [(v[0][0], v[0][1], 0.0, 0.0, v[1]) for v in chain]
    msp.add_lwpolyline(pts, format="xyseb", dxfattribs={"layer": layer})

    return JoinResult(ok=True, vertices=verts, n_used=len(used_geoms),
                      extended=bool(poly_idx), leftover=bool(leftover),
                      reason=reason)


# --------------------------------------------------------------------------
# Split: cut a joined child at an interior vertex
# --------------------------------------------------------------------------
def split_in_modelspace(msp, subs: Sequence, verts: Sequence,
                        vertex_index: int) -> bool:
    """Cut the joined child (``subs``/``verts``) at interior ``vertex_index``.

    Deletes the original LWPOLYLINE and emits the two resulting sides (each a
    shorter polyline, or a plain LINE/ARC when a side has a single segment).
    Returns True on success, False when the index is not a valid interior cut.
    """
    left_subs, right_subs = eg.split_chain_subs(subs, vertex_index)
    if left_subs is None:
        return False
    layer = "0"
    for e in list(msp):
        if e.dxftype() in ("LWPOLYLINE", "POLYLINE") \
                and polyline_matches(e, [verts]):
            try:
                layer = e.dxf.layer
            except Exception:
                pass
            try:
                msp.delete_entity(e)
            except Exception:
                pass
            break
    for side in (left_subs, right_subs):
        emit_subs(msp, side, layer)
    return True
