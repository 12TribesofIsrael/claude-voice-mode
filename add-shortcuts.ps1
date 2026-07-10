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
# Type these in any PowerShell / VS Code terminal:
#   voice-on / voice-off   turn the spoken replies on or off
#   voice-list             list the voices installed on this PC
#   voice-set <name>       pick a voice, e.g. voice-set Zira
function voice-on  { New-Item -ItemType File -Force "$env:TEMP\claude-voice-enabled" | Out-Null; Write-Host 'Voice mode ON  - Claude will read replies aloud.' -ForegroundColor Green }
function voice-off { Remove-Item -Force "$env:TEMP\claude-voice-enabled" -ErrorAction SilentlyContinue; Write-Host 'Voice mode OFF - Claude will stay silent.' -ForegroundColor Yellow }
function voice-set { param([Parameter(Mandatory)][string]$Name) Set-Content -Path "$env:USERPROFILE\.claude\hooks\voice-name.txt" -Value $Name -Encoding UTF8; Write-Host "Voice set to '$Name' (takes effect on the next reply)." -ForegroundColor Green }
function voice-list { Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name } }
# === end Claude Voice Mode ===
'@

Add-Content -Path $profilePath -Value $block -Encoding UTF8
Write-Host "Added voice-on / voice-off to $profilePath" -ForegroundColor Green
Write-Host "Open a new terminal (or run '. `$PROFILE') and type voice-on to use them." -ForegroundColor Cyan
