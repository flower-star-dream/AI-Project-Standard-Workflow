#!/usr/bin/env pwsh
# AIPSW CLI wrapper (Windows PowerShell 5.1+ / pwsh).
# Keep this file ASCII-only: PowerShell 5.1 decodes BOM-less scripts as ANSI,
# and a mojibake comment can swallow the next line and leave the path empty.
$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $here) { $here = Split-Path -Parent $PSCommandPath }
$py = Join-Path $here 'aipsw.py'
if (-not (Test-Path $py)) {
    Write-Error "aipsw.py not found next to this wrapper: $here"
    exit 2
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $py @args
    exit $LASTEXITCODE
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py $py @args
    exit $LASTEXITCODE
} else {
    Write-Error "Python 3.8+ not found. Install Python and make sure 'python' or 'py' is on PATH."
    exit 2
}
