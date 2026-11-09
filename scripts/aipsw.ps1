#!/usr/bin/env pwsh
# AIPSW 命令行包装（PowerShell）
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here "aipsw.py"
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $py @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py $py @args
} else {
    Write-Error "找不到 python，请先安装 Python 3.8+"
    exit 2
}
