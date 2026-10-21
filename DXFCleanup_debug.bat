@echo off
REM Launch DXF Cleanup with drag-event logging ON.
REM Do ONE bad top-down drag, then CLOSE THE WINDOW with the X (not Alt-F4
REM kill) so the log flushes. The trace lands on your Desktop as:
REM     dxfcleanup_drag_log.txt
set DXFCLEANUP_DEBUG=1
start "" "%~dp0DXFCleanup.exe"
