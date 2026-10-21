"""Small value types for the GUI's interactive-selection state.

Replaces error-prone parallel lists (a coordinate list and an index-aligned
owner list that had to be kept in lockstep) with one list of self-describing
records.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class Seam:
    """One latent parent-seam dot on a joined child polyline.

    ``point``  -- the (x, y) coordinate of the interior vertex (where the dot
                  is drawn and hit-tested).
    ``poly``   -- index of the owning joined child in the GUI's ``_polylines``.
    ``vertex`` -- the vertex index within that child, i.e. the cut location a
                  Split at this seam uses.
    """
    point: Point
    poly: int
    vertex: int

    @property
    def owner(self) -> Tuple[int, int]:
        """The ``(poly_index, vertex_index)`` pair a split arms on."""
        return (self.poly, self.vertex)
