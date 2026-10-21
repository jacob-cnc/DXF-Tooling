"""pytest configuration: put the repo root on sys.path so ``import dxfclean``
and ``import app`` resolve when pytest is run from anywhere in the tree.

The individual test files also do this themselves (so each stays runnable as a
standalone script via its ``__main__`` block), but doing it here means a plain
``pytest`` from the repo root works with no PYTHONPATH fiddling.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
