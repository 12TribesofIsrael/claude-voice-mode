# install.ps1 — sets up Claude Code Voice Mode on this Windows machine.
# What it does:
#   1. Copies the three hook scripts into %USERPROFILE%\.claude\hooks
#   2. Adds the Stop + UserPromptSubmit hooks to %USERPROFILE%\.claude\settings.json
#      (keeping any hooks you already have)
# Safe to re-run. Makes a backup of settings.json before touching it.

$ErrorActionPreference = 'Stop'

$claudeDir = Join-Path $env:USERPROFILE '.claude'
$hooksDir  = Join-Path $claudeDir 'hooks'
$settings  = Join-Path $claudeDir 'settings.json'
$srcHooks  = Join-Path $PSScriptRoot 'hooks'

# 1. Copy the hook scripts.
New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
foreach ($f in 'speak-response.ps1','speak-worker.ps1','voice-guard.ps1') {
    Copy-Item (Join-Path $srcHooks $f) (Join-Path $hooksDir $f) -Force
    Write-Host "  copied $f" -ForegroundColor Cyan
}

# 2. Load or create settings.json.
if (Test-Path $settings) {
    Copy-Item $settings "$settings.bak" -Force
    Write-Host "  backed up settings.json -> settings.json.bak" -ForegroundColor DarkGray
    $json = Get-Content $settings -Raw | ConvertFrom-Json
} else {
    $json = [pscustomobject]@{}
}

# Ensure a .hooks object exists.
if (-not $json.PSObject.Properties['hooks']) {
    $json | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{})
}

# Build the two hook entries with real absolute paths.
$speak = "powershell -NoProfile -File `"$hooksDir\speak-response.ps1`""
$guard = "powershell -NoProfile -File `"$hooksDir\voice-guard.ps1`""

$stopHook   = @(@{ hooks = @(@{ type = 'command'; command = $speak; timeout = 10 }) })
$promptHook = @(@{ hooks = @(@{ type = 'command'; command = $guard }) })

# Assign (overwrites any prior Stop/UserPromptSubmit voice entries; leaves others).
$json.hooks | Add-Member -NotePropertyName Stop            -NotePropertyValue $stopHook   -Force
$json.hooks | Add-Member -NotePropertyName UserPromptSubmit -NotePropertyValue $promptHook -Force

# Write UTF-8 WITHOUT a BOM. Windows PowerShell 5.1's "Set-Content -Encoding UTF8"
# prepends a BOM, which Claude Code (Node.js) refuses to parse -- it then silently
# ignores the whole settings.json and no hooks fire. Use .NET to write BOM-less.
$out = $json | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText($settings, $out, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "  wrote hooks into settings.json (UTF-8, no BOM)" -ForegroundColor Cyan

Write-Host ""
Write-Host "Done. Restart Claude Code, then run .\voice-on.ps1 to start hearing replies." -ForegroundColor Green
