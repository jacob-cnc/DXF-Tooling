# DXF-Tooling

Lightweight DXF cleanup for chaining geometry on a **ProtoTRAK DPM RMX** mill
control. Takes a messy / CAD-exported DXF and produces a *machinable* DXF where:

1. Curves are real arcs/circles, not splines, and
2. Every line is broken at each point another entity touches it, so no entity
   runs through another's intersection or overlaps a colinear line.

This is a productization of a proven, machine-validated proof-of-concept. The
core splitting algorithm (`dxfclean/core.py`) is a direct port of the original
`split_lines_at_intersections.py` and its results are preserved exactly.

## What it does

- **Splines → arcs (default) or lines.** With **Convert splines to arcs** on
  (the default), `SPLINE` entities are fitted to a G1-continuous chain of true
  circular `ARC`s (plus lines where straight) via biarc interpolation
  (`dxfclean/arcfit.py`) within a chord tolerance (default 0.005 mm). Arcs map
  directly to CNC `G2`/`G3` and give the ProtoTRAK chaining workflow far fewer
  segments to click. With the toggle off, splines are instead flattened to
  line segments with **curvature-adaptive sampling** (chord error ≈0.1% of the
  curve's bounding box). Either way, no spline survives in the output; anything
  that can't be fitted/sampled is flagged and dropped.
- **Breaks every line at each intersection / touch point** (other line
  endpoints and crossings, and `ARC` / `CIRCLE` intersections on the arc's
  active sweep).
- **Drops zero-length / degenerate segments** (e.g. two coincident tangent
  points produce one break, not a sliver).
- **Preserves geometry exactly** — only *subdivides*; never moves, trims, or
  merges. Arcs and circles pass through untouched.
- **Preserves layers and units.**
- Local only. No network, no accounts.

## Requirements / environment (Windows — read this)

> **Use the real Python interpreter, not the `python` on PATH.**
> On this machine the bare `python` command is the **Microsoft Store stub**,
> which does not work. Always invoke the full path:
>
> ```
> C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe
> ```

Dependencies (pinned to the versions validated on the machine — see
`requirements.txt`):

- `ezdxf==1.4.5`
- `matplotlib==3.11.2`

Install them into the **real** interpreter only:

```powershell
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" -m pip install -r requirements.txt
```

Drag-and-drop in the GUI is optional and needs `tkinterdnd2`; without it the app
falls back to a "Choose DXF…" file-picker button. Tkinter itself ships with
Python and needs nothing extra.

## Run the app

```powershell
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" app.py
```

Pick (or drag) a DXF in. The workflow is three explicit steps:

1. **Clean** -- runs cleanup **in memory** (no file written), shows the
   before/after preview, the coordinate-points table, and a report (entity
   counts in/out, lines split, overlaps merged, splines converted/arc-fitted,
   warnings). The cleaned result is now interactive and selectable.
2. **Join selected** *(optional)* -- select adjacent cleaned segments (click
   them, or click-and-drag a rubber-band **window select**), then Join fuses a
   single connected chain into one `LWPOLYLINE` so the ProtoTRAK chains the
   whole run in a single pick. A disjoint/branching selection is rejected.
3. **Save As...** -- writes the current in-memory result (including any joins)
   to a `CLEAN_<name>.dxf` of your choosing.

## Command line (headless / scripting)

```powershell
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" -m dxfclean.cli "in.dxf" "out.dxf"
```

Omit the output path to write `<name>_clean.dxf` next to the input.

### Coordinate points table

List every **de-duplicated** intersection & vertex of the cleaned drawing as a
numbered `X | Y` table (1, 2, 3, …). Points cover all three classes — line
endpoints/vertices, line↔arc/circle intersections, and arc endpoints + circle
centre/quadrants — collapsed so a corner shared by several entities is **one**
numbered row. Numbering is stable (ascending Y, then X), so the same drawing
always yields the same numbers.

In the **GUI**, the table appears on the right after you click *Clean + Save*,
with a **Save points CSV…** button. Headless:

```powershell
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" -m dxfclean.cli points "in.dxf" "points.csv"
```

Prints the table; the optional second argument also writes it as CSV
(`index,x,y,kind`).

## Tests

Install the dev dependencies (test runner + packaging), then run the suite:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

The full suite (65+ tests across `tests/`) covers the cleanup engine, arc
fitting, overlap merging, spline conversion, the pure edit-geometry
(`dxfclean/editgeom.py`) and join/split surgery (`dxfclean/editops.py`), plus
the GUI's selection/join/split behavior. The three GUI tests run for real when
a display is available and skip cleanly when headless. Every file is also
runnable standalone (e.g. `python tests\test_acceptance.py`) via its `__main__`
block.

CI runs `pytest` on every push and pull request to `main`
(`.github/workflows/ci.yml`, Windows runner — matches the target platform and
ships Tk so the GUI tests execute).

### Gating acceptance fixture

The regression fixture `fixtures/delrin_peg_ARCS_unsplit.dxf` (6 lines + 2 arcs
+ 1 circle) must clean to **11 line segments + 2 arcs + 1 circle**, with **zero**
zero-length segments and **no** line having another entity cross its interior.
Before/after PNGs are written to `docs/`.

```powershell
python -m pytest tests\test_acceptance.py
```

## Repository layout

```
dxfclean/
  core.py      core cleanup (ported split algorithm + spline handling + report)
  render.py    DXF -> PNG renderer (ported from render_dxf.py)
  points.py    coordinate extraction / numbering
  arcfit.py    biarc spline-to-arc fitting
  joinseg.py   chain ordering (longest connected path)
  editgeom.py  pure hit-test + chain-split geometry (no Tk/matplotlib)
  editops.py   join/split DXF modelspace surgery
  cli.py       command-line entry point
app.py         Tkinter GUI
tests/         pytest suite (engine + GUI behavior)
fixtures/      known-good regression fixtures
docs/          before.png / after.png (rendered by the acceptance test)
examples/      cleaned fixture output
requirements.txt       runtime deps (pinned)
requirements-dev.txt   test + packaging deps (pinned)
DXFCleanup.spec        PyInstaller build recipe (version-controlled)
build.ps1              one-command exe build
pytest.ini             test discovery config
.github/workflows/     CI (pytest on push / PR)
```

## Non-goals

- No toolpath / G-code generation. This only produces clean, chainable DXF
  geometry.
- The proven split logic's results are not changed to "improve" them without a
  regression test proving the acceptance case still passes.

## Packaging to a double-clickable .exe

**Built and smoke-tested** against Python 3.15.0 with PyInstaller 6.22.3. The
shipped build is a **single self-contained file** — one `DXFCleanup.exe` a
colleague can double-click with nothing else installed (no Python, no admin). End-user
instructions are in [`INSTALL.md`](INSTALL.md).

Rebuild from source. The PyInstaller recipe is version-controlled in
`DXFCleanup.spec` (bundles the `dxfclean` submodules and ezdxf's data files),
and `build.ps1` wraps the whole build in one command:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
.\build.ps1
```

Output: `dist\DXFCleanup.exe` (~44 MB, self-contained). `build.ps1` cleans the
previous `build\`/`dist\` and runs `python -m PyInstaller --noconfirm
DXFCleanup.spec`, so a fresh clone reproduces the same exe.

### Package for sharing with coworkers

`package.ps1` builds the exe (via `build.ps1`) and bundles it with the
first-run instructions into one zip ready to send:

```powershell
.\package.ps1                 # build + package
.\package.ps1 -SkipBuild      # package an exe already built this session
```

Output: `dist\DXFCleanup-<date>.zip` (~45 MB) containing `DXFCleanup.exe`,
`READ-ME-FIRST.txt`, and `INSTALL.md`. Send that one file (Teams, email, shared
drive); the recipient opens it and double-clicks `DXFCleanup.exe` — no Python,
admin rights, or internet. The only one-time prompt is Windows SmartScreen
(*More info → Run anyway*), which the bundled instructions explain.

> **Trade-offs.** `--onefile` unpacks to a temp dir on each launch, so the
> **first** start is a few seconds and antivirus occasionally false-flags it.
> For a fixed shop-floor PC you can instead use `--windowed` **without**
> `--onefile`, which produces a faster-starting `dist\DXFCleanup\` folder (exe +
> `_internal\`) that must be copied whole. We ship onefile for low-friction
> sharing with colleagues.
