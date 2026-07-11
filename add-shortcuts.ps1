# add-shortcuts.ps1 — adds `voice-on`, `voice-off`, `voice-set`, `voice-list`,
# and `voice-panel` commands you can type in any PowerShell / VS Code terminal.
# Appends them to your PowerShell profile. Safe to re-run: it only adds the
# block if it's missing, and refreshes it if this repo moved.

$ErrorActionPreference = 'Stop'

$profilePath = $PROFILE.CurrentUserAllHosts
$dir = Split-Path $profilePath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
if (-not (Test-Path $profilePath)) { New-Item -ItemType File -Force $profilePath | Out-Null }

$repo = $PSScriptRoot
$panel = Join-Path $repo 'start-webapp.ps1'

$block = @"

# === Claude Voice Mode shortcuts ===
# Type these in any PowerShell / VS Code terminal:
#   voice-on / voice-off   turn the spoken replies on or off
#   voice-list             list the free Windows voices installed on this PC
#   voice-set <name>       pick a Windows voice, e.g. voice-set Zira
#   voice-panel            open the visual control panel (premium ElevenLabs)
function voice-on    { New-Item -ItemType File -Force "`$env:TEMP\claude-voice-enabled" | Out-Null; Write-Host 'Voice mode ON  - Claude will read replies aloud.' -ForegroundColor Green }
function voice-off   { Remove-Item -Force "`$env:TEMP\claude-voice-enabled" -ErrorAction SilentlyContinue; Write-Host 'Voice mode OFF - Claude will stay silent.' -ForegroundColor Yellow }
function voice-set   { param([Parameter(Mandatory)][string]`$Name) Set-Content -Path "`$env:USERPROFILE\.claude\hooks\voice-name.txt" -Value `$Name -Encoding UTF8; Write-Host "Voice set to '`$Name' (takes effect on the next reply)." -ForegroundColor Green }
function voice-list  { Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | ForEach-Object { `$_.VoiceInfo.Name } }
function voice-panel { & '$panel' }
# === end Claude Voice Mode ===
"@

$existing = Get-Content $profilePath -Raw -ErrorAction SilentlyContinue
if ($existing -match '# === Claude Voice Mode shortcuts ===') {
    # Strip every existing block, then append one fresh block. Using a
    # MatchEvaluator (not a substitution string) so `$_`, `$env:` etc. inside
    # the block are never treated as regex replacement tokens.
    $pattern = '(?s)\r?\n?# === Claude Voice Mode shortcuts ===.*?# === end Claude Voice Mode ==='
    $stripped = [regex]::Replace($existing, $pattern, { param($m) '' })
    $stripped = $stripped.TrimEnd("`r", "`n")
    Set-Content -Path $profilePath -Value ($stripped + "`r`n" + $block) -Encoding UTF8
    Write-Host "Refreshed Claude Voice Mode shortcuts in $profilePath (voice-panel added)." -ForegroundColor Green
} else {
    Add-Content -Path $profilePath -Value $block -Encoding UTF8
    Write-Host "Added voice-on / voice-off / voice-panel to $profilePath" -ForegroundColor Green
}
Write-Host "Open a new terminal (or run '. `$PROFILE') to use them." -ForegroundColor Cyan
