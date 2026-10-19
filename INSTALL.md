# Installing DXF Cleanup

A simple Windows tool that cleans up a DXF drawing so it runs cleanly on the
**ProtoTRAK DPM RMX** control: it removes splines and breaks every line at the
points where other lines cross it, so the control can chain the geometry.

**There is nothing to install.** It is a single file. You do not need Python,
admin rights, or an internet connection.

---

## 1. Get the file

You need one file:

```
DXFCleanup.exe
```

Copy it anywhere you like — your Desktop, a `Tools` folder, a USB stick. It runs
from wherever you put it.

## 2. Run it

**Double-click `DXFCleanup.exe`.**

- The **first** launch takes a few seconds (it unpacks itself the first time) —
  this is normal, just wait.
- Windows may show a blue **"Windows protected your PC"** box the first time,
  because the file isn't signed by a big publisher. It is safe. Click
  **More info → Run anyway**. You only have to do this once per PC.

## 3. Use it

1. Click **Choose DXF…** and pick your drawing.
2. You'll see a **Before** preview on the left.
3. Click **Clean + Save** and choose where to save. It suggests
   `<yourfile>_clean.dxf` next to the original.
4. The **After** preview and a short report appear. Load the `_clean.dxf` onto
   the mill.

That's it. The original file is never changed — a new cleaned copy is written.

---

## Sharing it with a colleague

Just send them the one file, `DXFCleanup.exe` (email, Teams, a shared drive, or
a USB stick). They double-click it the same way. Nothing else to install.

## Common questions

**Does it need the internet?** No. It runs fully offline and sends nothing
anywhere.

**Does it change my original drawing?** No. It writes a new `_clean.dxf` and
leaves the original untouched.

**Windows SmartScreen blocked it / "unknown publisher".** Expected for an
unsigned in-house tool. Click **More info → Run anyway**. If your IT policy
blocks unsigned apps entirely, ask IT to allow this one file.

**It's slow to open.** Only the first launch — it's unpacking once. After that
it opens quickly.

**Antivirus flagged it.** Single-file PyInstaller apps are sometimes
false-flagged because they unpack themselves. It is a false positive; allow it,
or (for the person who builds it) use the folder build instead — see the
developer `README.md`.

**I'm a developer / want to rebuild it.** See `README.md` in this repository for
the source, dependencies, acceptance test, and the PyInstaller command.
