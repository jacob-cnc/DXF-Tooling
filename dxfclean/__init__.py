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
from .render import render
from .points import (collect_points, collect_points_from_report, Point,
                     points_as_table, points_as_csv, write_csv)

__all__ = ["clean_doc", "clean_file", "CleanReport", "TOL", "render",
           "merge_overlapping_lines",
           "collect_points", "collect_points_from_report", "Point",
           "points_as_table", "points_as_csv", "write_csv"]
__version__ = "0.1.0"
