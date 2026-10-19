"""dxfclean -- lightweight DXF cleanup for ProtoTRAK DPM RMX chaining.

Public API:
    clean_file(src, out=None) -> (out_path, CleanReport)
    clean_doc(doc)            -> (new_doc, CleanReport)
    render(src, out)          -> list of skipped entity type names
    CleanReport               -- structured counts + warnings
"""
from .core import clean_doc, clean_file, CleanReport, TOL
from .render import render

__all__ = ["clean_doc", "clean_file", "CleanReport", "TOL", "render"]
__version__ = "0.1.0"
