"""Command-line cleanup entry point.

Usage:
    <real python> -m dxfclean.cli <in.dxf> [out.dxf]

If out.dxf is omitted, writes <name>_clean.dxf next to the input. Prints the
same report the GUI shows.
"""
import sys

from .core import clean_file


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
