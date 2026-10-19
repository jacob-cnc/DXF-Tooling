"""Command-line entry point.

Clean (default):
    <real python> -m dxfclean.cli <in.dxf> [out.dxf]
    If out.dxf is omitted, writes <name>_clean.dxf next to the input.

Coordinate points table:
    <real python> -m dxfclean.cli points <in.dxf> [out.csv]
    Prints the numbered X|Y table of every intersection & vertex. If out.csv
    is given, also writes the table as CSV.
"""
import sys

import ezdxf

from .core import clean_file
from .points import collect_points, points_as_table, write_csv


def _run_points(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    src = argv[2]
    try:
        doc = ezdxf.readfile(src)
    except IOError:
        print("ERROR: not found:", src)
        return 1
    points, report = collect_points(doc)
    print(points_as_table(points))
    print("\n%d points." % len(points))
    if len(argv) > 3:
        out = write_csv(points, argv[3])
        print("WROTE", out)
    return 0


def _run_clean(argv):
    src = argv[1]
    out = argv[2] if len(argv) > 2 else None
    try:
        out, report = clean_file(src, out)
    except FileNotFoundError:
        print("ERROR: not found:", src)
        return 1
    print(report.as_text())
    print("WROTE", out)
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "points":
        return _run_points(argv)
    return _run_clean(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
