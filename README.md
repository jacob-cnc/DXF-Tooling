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

- **No splines in output.** `SPLINE` entities are flattened to short line
  segments, which then take part in the same intersection-splitting. Anything
  that can't be sampled is flagged in the report and dropped.
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

Pick (or drag) a DXF in → it writes `<name>_clean.dxf`, shows a **before/after**
preview, and a short report: entity counts in/out, lines split, segments
dropped, splines converted, and any warnings.

## Command line (headless / scripting)

```powershell
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" -m dxfclean.cli "in.dxf" "out.dxf"
```

Omit the output path to write `<name>_clean.dxf` next to the input.

## Acceptance test

The regression fixture `fixtures/delrin_peg_ARCS_unsplit.dxf` (6 lines + 2 arcs
+ 1 circle) must clean to **11 line segments + 2 arcs + 1 circle**, with **zero**
zero-length segments and **no** line having another entity cross its interior.
Before/after PNGs are written to `docs/`.

```powershell
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" tests\test_acceptance.py
```

(Also runnable under `pytest` if installed:
`… -m pytest tests\test_acceptance.py`.)

## Repository layout

```
dxfclean/
  core.py      core cleanup (ported split algorithm + spline handling + report)
  render.py    DXF -> PNG renderer (ported from render_dxf.py)
  cli.py       command-line entry point
app.py         Tkinter GUI
tests/
  test_acceptance.py   the gating regression test
fixtures/
  delrin_peg_ARCS_unsplit.dxf   known-good regression fixture
docs/          before.png / after.png (rendered by the acceptance test)
examples/      cleaned fixture output
requirements.txt
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

Rebuild from source (install PyInstaller into the **real** interpreter first,
mind the MS Store python-stub trap above):

```powershell
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" -m pip install pyinstaller
& "C:\Users\jhonick\AppData\Local\Python\pythoncore-3.15-64\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name DXFCleanup app.py
```

Output: `dist\DXFCleanup.exe` (~44 MB, self-contained).

> **Trade-offs.** `--onefile` unpacks to a temp dir on each launch, so the
> **first** start is a few seconds and antivirus occasionally false-flags it.
> For a fixed shop-floor PC you can instead use `--windowed` **without**
> `--onefile`, which produces a faster-starting `dist\DXFCleanup\` folder (exe +
> `_internal\`) that must be copied whole. We ship onefile for low-friction
> sharing with colleagues.
