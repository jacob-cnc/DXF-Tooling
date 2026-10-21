"""dxfclean -- lightweight DXF cleanup for ProtoTRAK DPM RMX chaining.

Public API:
    clean_file(src, out=None) -> (out_path, CleanReport)
    clean_doc(doc)            -> (new_doc, CleanReport)
    render(src, out)          -> list of skipped entity type names
    collect_points(doc)       -> (list[Point], CleanReport)
    CleanReport               -- structured counts + warnings
    Point                     -- one numbered coordinate (index, x, y, kinds)
"""
from .core import clean_doc, clean_file, CleanReport, TOL, merge_overlapping_lines
from .render import render, draw_dxf
from .points import (collect_points, collect_points_from_report, Point,
                     points_as_table, points_as_csv, write_csv)
from .joinseg import order_chain, longest_chain
from .editgeom import (close, dist2, point_seg_distance, point_arc_distance,
                       angle_in_sweep, sub_distance, poly_distance,
                       sub_endpoints_bulge, subs_to_lwpoly_points,
                       split_chain_subs, chain_vertices)
from .editops import (entity_matches_any, polyline_matches, emit_subs,
                      join_in_modelspace, split_in_modelspace, JoinResult)

__all__ = ["clean_doc", "clean_file", "CleanReport", "TOL", "render", "draw_dxf",
           "merge_overlapping_lines", "order_chain", "longest_chain",
           "collect_points", "collect_points_from_report", "Point",
           "points_as_table", "points_as_csv", "write_csv",
           "close", "dist2", "point_seg_distance", "point_arc_distance",
           "angle_in_sweep", "sub_distance", "poly_distance",
           "sub_endpoints_bulge", "subs_to_lwpoly_points", "split_chain_subs",
           "chain_vertices",
           "entity_matches_any", "polyline_matches", "emit_subs",
           "join_in_modelspace", "split_in_modelspace", "JoinResult"]
__version__ = "0.1.0"
