# Produce a single shareable zip for sending to coworkers:
#   dist\DXFCleanup-<date>.zip
# containing:
#   DXFCleanup.exe      -- the whole tool, nothing to install
#   READ-ME-FIRST.txt   -- plain-text first-run instructions
#   INSTALL.md          -- the fuller guide
#
# The recipient double-clicks the zip, then double-clicks DXFCleanup.exe
# inside it (or copies the exe out first). No Python / admin / internet.
#
# Usage (from the repo root, in a venv with deps installed):
#   python -m pip install -r requirements.txt -r requirements-dev.txt
#   .\package.ps1
#
# Pass -SkipBuild to zip an exe you already built this session.

param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if (-not $SkipBuild) {
    Write-Host "Building the exe first..."
    & "$here\build.ps1"
}

$exe = Join-Path $here "dist\DXFCleanup.exe"
if (-not (Test-Path $exe)) {
    throw "dist\DXFCleanup.exe not found -- run .\build.ps1 first (or drop -SkipBuild)."
}

# Stage the three files under a clean, named folder so the zip expands into
# one tidy folder rather than loose files.
$stamp   = Get-Date -Format "yyyy-MM-dd"
$name    = "DXFCleanup-$stamp"
$staging = Join-Path $here "dist\$name"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging | Out-Null

Copy-Item $exe                                   -Destination $staging
Copy-Item (Join-Path $here "packaging\READ-ME-FIRST.txt") -Destination $staging
Copy-Item (Join-Path $here "INSTALL.md")         -Destination $staging

$zip = Join-Path $here "dist\$name.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path "$staging\*" -DestinationPath $zip
Remove-Item -Recurse -Force $staging

$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "OK: $zip  ($mb MB)"
Write-Host "Send that one file. Recipient opens it and double-clicks DXFCleanup.exe."
