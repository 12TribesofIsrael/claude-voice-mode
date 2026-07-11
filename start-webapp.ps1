# start-webapp.ps1 — launch the Claude Voice Mode control panel in your browser.
# Serves a local dashboard (127.0.0.1) to toggle voice on/off, switch between the
# free Windows voice and premium ElevenLabs, pick a voice, and watch your credits.

$ErrorActionPreference = 'Stop'
$server = Join-Path $PSScriptRoot 'webapp\server.py'
$port   = if ($env:VOICE_PANEL_PORT) { $env:VOICE_PANEL_PORT } else { '8770' }

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Error 'Python not found. Install Python 3 and try again.'; return }

Write-Host "Starting Claude Voice Mode panel at http://127.0.0.1:$port/ ..." -ForegroundColor Cyan
Start-Process $py -ArgumentList @($server)
Start-Sleep -Milliseconds 900
Start-Process "http://127.0.0.1:$port/"
Write-Host "Panel opened in your browser. Close the python window to stop it." -ForegroundColor Green
