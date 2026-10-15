# MBAACC action GIF export (transparent background + effects)
# Usage: powershell -ExecutionPolicy Bypass -File run_full.ps1 [-Jobs 10]
#
# This file is intentionally ASCII-only: Windows PowerShell 5.1 parses .ps1
# files as ANSI when there is no BOM, so non-ASCII text here would break the
# parser. The Chinese progress text comes from python itself.
#
# Do NOT pipe python's output through PowerShell -- the byte stream would be
# decoded and re-encoded, which turns it into mojibake. Let python write to the
# console directly; the log file is written by python in UTF-8 (see --log).

param([int]$Jobs = 10)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

Remove-Item Env:\PYTHONIOENCODING -ErrorAction SilentlyContinue
$env:PYTHONUNBUFFERED = "1"

$Host.UI.RawUI.WindowTitle = "MBAACC GIF Export"

$sw = [System.Diagnostics.Stopwatch]::StartNew()

Write-Host "=================================================="
Write-Host " MBAACC action GIF export (transparent + effects)"
Write-Host (" jobs={0}   out=out\gifs   log=out\run.log" -f $Jobs)
Write-Host (" start " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Host "=================================================="
Write-Host ""

python -u mbaa_gif.py -c all --effects -j $Jobs --no-sheet --format gif --alpha-cutoff 128 -o out\gifs --log out\run.log

$code = $LASTEXITCODE
$sw.Stop()
$n = (Get-ChildItem -Recurse -File out\gifs -Filter *.gif -ErrorAction SilentlyContinue |
      Measure-Object).Count
Write-Host ""
Write-Host "=================================================="
Write-Host (" done: {0} gifs   elapsed {1:hh\:mm\:ss}   exit={2}" -f $n, $sw.Elapsed, $code)
Write-Host " window stays open - close it when finished."
Write-Host "=================================================="
