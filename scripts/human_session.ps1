# Guided human session for Far Point (about 8-10 minutes). See scripts/human_session.py.
#
#   .\scripts\human_session.ps1               # parts A-D (E runs once web/dist exists: -Parts abcde)
#   .\scripts\human_session.ps1 -Parts b      # re-run one part
param(
    [string]$Parts = "abcd",
    [string]$Runtime = $(if ($env:FARPOINT_RUNTIME) { $env:FARPOINT_RUNTIME } else { "E:\farpoint-runtime" })
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:FARPOINT_RUNTIME = $Runtime
$env:HF_HOME = "$Runtime\hf"
$env:TORCH_HOME = "$Runtime\torch"
$env:UV_CACHE_DIR = "$Runtime\uv-cache"
$env:PIP_CACHE_DIR = "$Runtime\pip-cache"
$Host.UI.RawUI.WindowTitle = "Far Point guided session"
Set-Location $root
& "$root\.venv\Scripts\python.exe" "$root\scripts\human_session.py" --parts $Parts
