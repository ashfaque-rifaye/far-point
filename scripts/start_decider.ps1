# Start the local Strands Decider server on 127.0.0.1:8099 (no auth: localhost only).
# Keeps every cache on E:, and raises the server process to High priority, which the
# Phase 1 spike measured as the difference between ~715 ms and ~490 ms p50 on a busy laptop.
#
#   .\scripts\start_decider.ps1            # text mode
#   .\scripts\start_decider.ps1 -Vision    # image mode (keeps Qwen3.5's vision tower)
param(
    [switch]$Vision,
    [string]$Runtime = "E:\farpoint-runtime",
    [int]$Port = 8099
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# Stop any running Decider server first.
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'strands-decider(\.exe)?"?\s+serve' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$env:HF_HOME = "$Runtime\hf"
$env:TORCH_HOME = "$Runtime\torch"
$env:TRITON_CACHE_DIR = "$Runtime\triton-cache"
$env:TORCHINDUCTOR_CACHE_DIR = "$Runtime\inductor-cache"
$env:UV_CACHE_DIR = "$Runtime\uv-cache"
$env:PIP_CACHE_DIR = "$Runtime\pip-cache"
$env:HF_HUB_OFFLINE = "1"
New-Item -ItemType Directory -Force -Path "$Runtime\logs" | Out-Null

$serveArgs = @("serve", "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610", "--device", "cuda", "--host", "127.0.0.1", "--port", "$Port")
if ($Vision) { $serveArgs += "--vision" }
$p = Start-Process -FilePath "$root\.venv\Scripts\strands-decider.exe" -ArgumentList $serveArgs `
    -RedirectStandardOutput "$Runtime\logs\decider.out" -RedirectStandardError "$Runtime\logs\decider.err" `
    -WindowStyle Hidden -PassThru

$up = $false
for ($i = 0; $i -lt 90; $i++) {
    try { Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 3 | Out-Null; $up = $true; break } catch { Start-Sleep -Seconds 5 }
}
if (-not $up) { throw "Decider did not come up; see $Runtime\logs\decider.err" }

# The launcher exe spawns python.exe children; raise all of them.
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'strands-decider(\.exe)?"?\s+serve' -and $_.Name -eq 'python.exe' } |
    ForEach-Object { (Get-Process -Id $_.ProcessId).PriorityClass = 'High' }
Write-Output "Decider up on 127.0.0.1:$Port (vision=$Vision, launcher pid $($p.Id))"
Write-Output "First request after a fresh Triton cache can take ~2-3 min while kernels autotune."
