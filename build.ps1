# Build dist\DXFCleanup.exe from the committed PyInstaller spec.
#
# Usage (from the repo root, in a venv with the deps installed):
#   python -m pip install -r requirements.txt -r requirements-dev.txt
#   .\build.ps1
#
# Produces a single-file, windowed executable at dist\DXFCleanup.exe.
# The recipe (hidden imports, bundled ezdxf data) lives in DXFCleanup.spec,
# which is version-controlled so this build is reproducible from a clean clone.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "Cleaning previous build output..."
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }

Write-Host "Building DXFCleanup.exe from DXFCleanup.spec..."
python -m PyInstaller --noconfirm DXFCleanup.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)" }

$exe = Join-Path $here "dist\DXFCleanup.exe"
if (-not (Test-Path $exe)) { throw "Expected $exe was not produced." }
Write-Host "OK: $exe"
