# unlock-voices.ps1 — makes Windows' OneCore voices (e.g. Microsoft Mark)
# visible to the classic speech engine that this project uses.
#
# It copies the voice registration keys from the OneCore location into the
# SAPI location. This needs Administrator rights, so the script re-launches
# itself elevated (you'll see a UAC prompt — click Yes).
#
# Run it once. Then restart your terminals / Claude Code and the new voices
# show up. Pick one with:  voice-set Mark

# Re-launch elevated if we're not already admin.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "Requesting administrator rights..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList @(
        '-NoProfile', '-File', "`"$PSCommandPath`""
    )
    return
}

$src = 'HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens'
$dsts = @(
    'HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens',                 # 64-bit apps
    'HKLM\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens'      # 32-bit apps
)

$tokens = Get-ChildItem "Registry::$src" | ForEach-Object { Split-Path $_.Name -Leaf }
Write-Host "Found OneCore voices: $($tokens -join ', ')" -ForegroundColor Cyan

foreach ($t in $tokens) {
    foreach ($dst in $dsts) {
        # reg copy handles the whole key tree; /f = no prompt.
        reg copy "$src\$t" "$dst\$t" /s /f | Out-Null
    }
}

Write-Host ""
Write-Host "Done. Restart your terminals and Claude Code." -ForegroundColor Green
Write-Host "Then choose a voice, e.g.:  voice-set Mark" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to close"
