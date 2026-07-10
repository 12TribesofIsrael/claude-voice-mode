# add-shortcuts.ps1 — adds `voice-on` and `voice-off` commands you can type in
# any PowerShell / VS Code terminal. Appends them to your PowerShell profile.
# Safe to re-run; it won't add duplicates.

$ErrorActionPreference = 'Stop'

$profilePath = $PROFILE.CurrentUserAllHosts
$dir = Split-Path $profilePath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
if (-not (Test-Path $profilePath)) { New-Item -ItemType File -Force $profilePath | Out-Null }

$existing = Get-Content $profilePath -Raw -ErrorAction SilentlyContinue
if ($existing -match 'claude-voice-enabled') {
    Write-Host "Shortcuts already present in $profilePath" -ForegroundColor DarkGray
    return
}

$block = @'

# === Claude Voice Mode shortcuts ===
# Type `voice-on` or `voice-off` in any PowerShell / VS Code terminal.
function voice-on  { New-Item -ItemType File -Force "$env:TEMP\claude-voice-enabled" | Out-Null; Write-Host 'Voice mode ON  - Claude will read replies aloud.' -ForegroundColor Green }
function voice-off { Remove-Item -Force "$env:TEMP\claude-voice-enabled" -ErrorAction SilentlyContinue; Write-Host 'Voice mode OFF - Claude will stay silent.' -ForegroundColor Yellow }
# === end Claude Voice Mode ===
'@

Add-Content -Path $profilePath -Value $block -Encoding UTF8
Write-Host "Added voice-on / voice-off to $profilePath" -ForegroundColor Green
Write-Host "Open a new terminal (or run '. `$PROFILE') and type voice-on to use them." -ForegroundColor Cyan
