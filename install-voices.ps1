# install-voices.ps1 -- adds the two natural voice engines to Claude Voice Mode.
#
#   Piper   : neural speech that runs offline on your CPU. Free forever, no API
#             key, no internet, safe to ship commercially. This is also the
#             engine you would later fine-tune on your own recorded voice.
#   Neural  : Microsoft's online neural voices -- the same Andrew and Ava you can
#             install for Narrator. Windows keeps the Narrator copies locked to
#             Narrator (they ship model data but no speech engine and register
#             no COM class), so we reach the same voices through Microsoft's
#             free read-aloud service instead. No API key, but it needs internet.
#
# Safe to re-run. Downloads about 250 MB the first time for the three starter
# Piper voices (a high-quality male, a female, and a British male). Every other
# English voice Piper publishes - about 40 - can be added later from the
# control panel: Voice Panel.bat, then "More voices" under the Piper dropdown.
#
# Usage:
#   .\install-voices.ps1                      # starter set of three voices
#   .\install-voices.ps1 -PiperVoice en_US-lessac-medium
#   .\install-voices.ps1 -PiperVoice en_US-ryan-high, en_US-amy-medium
#   .\install-voices.ps1 -SkipPiper           # neural voices only, no download

param(
    [string[]]$PiperVoice = @('en_US-ryan-high', 'en_US-hfc_female-medium', 'en_GB-alan-medium'),
    [switch]$SkipPiper
)

$ErrorActionPreference = 'Stop'

$hooksDir = Join-Path $env:USERPROFILE '.claude\hooks'
$piperDir = Join-Path $hooksDir 'piper'
$cfgPath  = Join-Path $hooksDir 'voice-config.json'

New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null

# --- Python ----------------------------------------------------------------
$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py.exe -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    Write-Host "Python not found. Install Python 3 from python.org, then re-run." -ForegroundColor Red
    exit 1
}
Write-Host "Using $python" -ForegroundColor DarkGray

function Install-Package([string]$name) {
    # Some Python installs ship a certificate-verification bug that makes every
    # pip download die with a recursion error. Retry with legacy certificate
    # handling before giving up, so a broken interpreter is not a dead end.
    & $python -m pip install --quiet --disable-pip-version-check $name 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { return $true }
    Write-Host "  retrying $name with legacy certificate handling..." -ForegroundColor DarkYellow
    & $python -m pip install --quiet --disable-pip-version-check --use-deprecated=legacy-certs $name 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# --- Engines ---------------------------------------------------------------
Write-Host ""
Write-Host "Installing Microsoft neural voice support (edge-tts)..." -ForegroundColor Cyan
$neuralOk = Install-Package 'edge-tts'
if ($neuralOk) { Write-Host "  ok" -ForegroundColor Green }
else { Write-Host "  failed -- neural voices will stay off" -ForegroundColor Yellow }

$piperOk = $false
$modelPath = ''
if (-not $SkipPiper) {
    Write-Host ""
    Write-Host "Installing offline neural voice support (piper-tts)..." -ForegroundColor Cyan
    $piperOk = Install-Package 'piper-tts'
    if ($piperOk) {
        Write-Host "  ok" -ForegroundColor Green
        New-Item -ItemType Directory -Force -Path $piperDir | Out-Null
        $got = @()
        foreach ($v in $PiperVoice) {
            $path = Join-Path $piperDir "$v.onnx"
            if (Test-Path -LiteralPath $path) {
                Write-Host "  voice $v already downloaded" -ForegroundColor DarkGray
                $got += $path
                continue
            }
            Write-Host "  downloading voice $v (60-140 MB, one time)..." -ForegroundColor Cyan
            & $python -m piper.download_voices $v --data-dir $piperDir 2>&1 | Out-Null
            if (Test-Path -LiteralPath $path) {
                Write-Host "  downloaded" -ForegroundColor Green
                $got += $path
            } else {
                Write-Host "  download of $v failed -- skipping it" -ForegroundColor Yellow
            }
        }
        if ($got.Count -eq 0) {
            Write-Host "  no voice downloaded -- Piper will stay off" -ForegroundColor Yellow
            $piperOk = $false
        } else {
            # First requested voice that made it becomes the default pick, unless a
            # pick already exists and still points at a real file.
            $modelPath = $got[0]
        }
    } else {
        Write-Host "  failed -- Piper will stay off" -ForegroundColor Yellow
    }
}

# --- Merge into voice-config.json ------------------------------------------
# Read-modify-write so an existing ElevenLabs key and voice pick survive.
$cfg = @{}
if (Test-Path -LiteralPath $cfgPath) {
    try {
        (Get-Content -LiteralPath $cfgPath -Raw | ConvertFrom-Json).PSObject.Properties |
            ForEach-Object { $cfg[$_.Name] = $_.Value }
    } catch { $cfg = @{} }
}

$cfg['neural'] = $neuralOk
if (-not $cfg.ContainsKey('neuralVoice') -or -not $cfg['neuralVoice']) {
    $cfg['neuralVoice'] = 'en-US-AndrewNeural'
}
$cfg['piper'] = $piperOk
if ($piperOk) {
    $keep = $cfg.ContainsKey('piperModel') -and $cfg['piperModel'] -and (Test-Path -LiteralPath $cfg['piperModel'])
    if (-not $keep) { $cfg['piperModel'] = $modelPath }
    $cfg['piperDir'] = $piperDir
}
if (-not $cfg.ContainsKey('ttsPort')) { $cfg['ttsPort'] = 8771 }
$cfg['python'] = $python

$json = $cfg | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($cfgPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ""
Write-Host "Updated $cfgPath" -ForegroundColor Cyan

# --- Report ----------------------------------------------------------------
Write-Host ""
Write-Host "Engines now available, best first:" -ForegroundColor Green
Write-Host ("  ElevenLabs : " + $(if ($cfg['apiKey']) { 'key saved' } else { 'no key (off)' }))
Write-Host ("  Neural     : " + $(if ($neuralOk) { "on  -> $($cfg['neuralVoice'])  (needs internet)" } else { 'off' }))
Write-Host ("  Piper      : " + $(if ($piperOk)  { "on  -> $([IO.Path]::GetFileNameWithoutExtension($cfg['piperModel']))  (offline, $($got.Count) voice(s) on disk)" } else { 'off' }))
Write-Host  "  Windows    : always on as the last-resort fallback"
Write-Host ""
Write-Host "Run .\install.ps1 to refresh the installed hooks, then open the Voice Panel to switch engines." -ForegroundColor Green
Write-Host "Want more offline voices? Voice Panel -> 'More voices' under the Piper dropdown lists all ~40." -ForegroundColor Green
