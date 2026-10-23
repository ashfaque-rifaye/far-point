<#
Record the screen (and a microphone, if you name one) for the demo video. Output goes to
E:\farpoint-runtime\recordings, outside the repo. Stop with q in this window.

  .\scripts\record_demo.ps1                       # list audio devices, then record screen only
  .\scripts\record_demo.ps1 -Mic "Microphone Array (Realtek(R) Audio)"
  .\scripts\record_demo.ps1 -Seconds 180

The webcam is NOT recorded here: Far Point's live mode is using it. Film the "glasses off" shots with a phone.
#>
param(
    [string]$Mic = "",
    [int]$Seconds = 0,
    [int]$Fps = 30,
    [string]$OutDir = "E:\farpoint-runtime\recordings"
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "ffmpeg not found. Install it: winget install Gyan.FFmpeg" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$ErrorActionPreference = "Continue"  # ffmpeg logs to stderr

if (-not $Mic) {
    Write-Host "Audio devices (pass one with -Mic to record narration):"
    ffmpeg -hide_banner -list_devices true -f dshow -i dummy 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match '"(.+)" \(audio\)' } | ForEach-Object { "  " + $Matches[1] }
}

$out = Join-Path $OutDir ("farpoint-demo-{0:yyyyMMdd-HHmmss}.mp4" -f (Get-Date))
$ffArgs = @("-hide_banner", "-y", "-f", "gdigrab", "-framerate", "$Fps", "-draw_mouse", "1", "-i", "desktop")
if ($Mic) { $ffArgs += @("-f", "dshow", "-i", "audio=$Mic") }
if ($Seconds -gt 0) { $ffArgs += @("-t", "$Seconds") }
$ffArgs += @("-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2")
if ($Mic) { $ffArgs += @("-c:a", "aac", "-b:a", "160k") }
$ffArgs += $out

Write-Host "Recording to $out  (press q here to stop)"
& ffmpeg @ffArgs
Write-Host "Saved $out"
