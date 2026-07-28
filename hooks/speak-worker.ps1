# speak-worker.ps1
# Speaks a chunk of plain text, then deletes the temp file. Launched hidden by
# speak-response.ps1. Kept as a plain named script (no encoded/obfuscated
# command line) so antivirus leaves it alone.
#
# Four engines, tried in order, each falling through to the next on any error:
#   PREMIUM  -> ElevenLabs (natural, cloud). Used only when voice-config.json has
#               premium=true, an apiKey, and a voiceId.
#   NEURAL   -> Microsoft's neural voices, Andrew and Ava and friends (natural,
#               free, online). Used when neural=true. The copies Windows
#               downloads for Narrator are locked to Narrator, so these come
#               from Microsoft's free read-aloud service instead.
#   PIPER    -> Local neural voice (natural, offline, free). Used when
#               piper=true and a voice model is installed.
#
#   NEURAL and PIPER both go through tts-server.py, a small local server that
#   keeps the voice model warm so we pay the load cost once per session rather
#   than once per reply. The worker starts it on first use.
#   DEFAULT  -> Windows System.Speech (robotic, offline). Always the last resort,
#               because it is the one thing that cannot fail.
param([string]$File)

$ErrorActionPreference = 'SilentlyContinue'
$dbg = Join-Path $env:TEMP 'claude-voice-debug.log'

if (-not $File -or -not (Test-Path -LiteralPath $File)) { exit }
$text = Get-Content -LiteralPath $File -Raw
Remove-Item -LiteralPath $File -Force
if ([string]::IsNullOrWhiteSpace($text)) { exit }

# ---- Load optional premium config -----------------------------------------
$cfg = $null
$cfgFile = Join-Path $PSScriptRoot 'voice-config.json'
if (Test-Path -LiteralPath $cfgFile) {
    try { $cfg = Get-Content -LiteralPath $cfgFile -Raw | ConvertFrom-Json } catch { $cfg = $null }
}

function Get-WavDurationMs([string]$path) {
    # Read the byte rate out of the RIFF header (bytes 28..31) so the fallback
    # wait is exact for any sample rate a voice model happens to use.
    try {
        $fs = [System.IO.File]::OpenRead($path)
        try {
            $hdr = New-Object byte[] 44
            if ($fs.Read($hdr, 0, 44) -lt 44) { return 0 }
            $byteRate = [BitConverter]::ToUInt32($hdr, 28)
            if ($byteRate -le 0) { return 0 }
            return [int](((New-Object System.IO.FileInfo $path).Length - 44) / $byteRate * 1000)
        } finally { $fs.Dispose() }
    } catch { return 0 }
}

function Play-AudioFile([string]$path) {
    # Try WPF MediaPlayer first, then Windows Media Player COM as a fallback.
    $len = (Get-Item -LiteralPath $path).Length
    if ($path -like '*.wav') {
        $estMs = (Get-WavDurationMs $path) + 700
        if ($estMs -le 700) { $estMs = [int](($len / 44100.0) * 1000) + 700 }
    } else {
        $estMs = [int](($len / 16000.0) * 1000) + 700   # ~128 kbps mp3 => ~16 KB/s
    }
    try {
        Add-Type -AssemblyName presentationCore -ErrorAction Stop
        $mp = New-Object System.Windows.Media.MediaPlayer
        $mp.Volume = 1.0
        $mp.Open([uri]$path)
        $n = 0
        while (-not $mp.NaturalDuration.HasTimeSpan -and $n -lt 60) { Start-Sleep -Milliseconds 50; $n++ }
        $mp.Play()
        if ($mp.NaturalDuration.HasTimeSpan) {
            Start-Sleep -Milliseconds ([int]$mp.NaturalDuration.TimeSpan.TotalMilliseconds + 400)
        } else {
            Start-Sleep -Milliseconds $estMs
        }
        $mp.Stop(); $mp.Close()
        return $true
    } catch {
        Add-Content -LiteralPath $dbg -Value ("  MediaPlayer failed: {0}" -f $_.Exception.Message)
    }
    try {
        $wmp = New-Object -ComObject WMPlayer.OCX.7
        $wmp.settings.volume = 100
        $wmp.URL = $path
        $wmp.controls.play()
        $waited = 0
        while ($wmp.playState -ne 3 -and $waited -lt 20) { Start-Sleep -Milliseconds 50; $waited++ }   # wait to start
        $waited = 0
        while (($wmp.playState -eq 3) -and $waited -lt 1200) { Start-Sleep -Milliseconds 100; $waited++ } # wait to finish
        $wmp.close()
        return $true
    } catch {
        Add-Content -LiteralPath $dbg -Value ("  WMP COM failed: {0}" -f $_.Exception.Message)
    }
    return $false
}

function Speak-Premium([string]$text, $cfg) {
    if (-not $cfg) { return $false }
    if (-not $cfg.premium) { return $false }
    if ([string]::IsNullOrWhiteSpace($cfg.apiKey)) { return $false }
    if ([string]::IsNullOrWhiteSpace($cfg.voiceId)) { return $false }
    try {
        $model = if ($cfg.modelId) { $cfg.modelId } else { 'eleven_turbo_v2_5' }
        $stab  = if ($null -ne $cfg.stability)  { [double]$cfg.stability }  else { 0.5 }
        $sim   = if ($null -ne $cfg.similarity) { [double]$cfg.similarity } else { 0.75 }
        $voiceId = $cfg.voiceId
        $uri = "https://api.elevenlabs.io/v1/text-to-speech/$voiceId" + '?output_format=mp3_44100_128'
        $bodyObj = @{
            text           = $text
            model_id       = $model
            voice_settings = @{ stability = $stab; similarity_boost = $sim }
        }
        $body  = $bodyObj | ConvertTo-Json -Depth 5 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
        $mp3   = Join-Path $env:TEMP ('claude-voice-' + [guid]::NewGuid().ToString('N') + '.mp3')
        $headers = @{ 'xi-api-key' = $cfg.apiKey; 'Content-Type' = 'application/json'; 'Accept' = 'audio/mpeg' }
        Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $bytes -OutFile $mp3 -TimeoutSec 90
        if (-not (Test-Path -LiteralPath $mp3) -or (Get-Item -LiteralPath $mp3).Length -lt 400) {
            Add-Content -LiteralPath $dbg -Value '  Premium: empty/failed audio'; return $false
        }
        $ok = Play-AudioFile $mp3
        Remove-Item -LiteralPath $mp3 -Force -ErrorAction SilentlyContinue
        Add-Content -LiteralPath $dbg -Value ("  Premium spoke ok={0} voice={1} model={2}" -f $ok, $voiceId, $model)
        return $ok
    } catch {
        Add-Content -LiteralPath $dbg -Value ("  Premium error -> falling back: {0}" -f $_.Exception.Message)
        return $false
    }
}

function Get-PythonExe($cfg) {
    if ($cfg -and $cfg.python -and (Test-Path -LiteralPath $cfg.python)) { return $cfg.python }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Test-TtsServer([string]$base) {
    try {
        $h = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 2 -ErrorAction Stop
        return [bool]$h.ok
    } catch { return $false }
}

function Start-TtsServer($cfg, [string]$base) {
    # The server keeps the voice model warm. Launching it costs a couple of
    # seconds once per session; every reply after that is near-instant.
    $script = Join-Path $PSScriptRoot 'tts-server.py'
    if (-not (Test-Path -LiteralPath $script)) {
        Add-Content -LiteralPath $dbg -Value '  tts-server.py missing'; return $false
    }
    $python = Get-PythonExe $cfg
    if (-not $python) {
        Add-Content -LiteralPath $dbg -Value '  no python on PATH'; return $false
    }
    # pythonw runs with no console window, so nothing flashes on screen.
    $pythonw = Join-Path (Split-Path $python -Parent) 'pythonw.exe'
    if (Test-Path -LiteralPath $pythonw) { $python = $pythonw }

    try {
        Start-Process -FilePath $python -ArgumentList @("`"$script`"") `
            -WindowStyle Hidden -ErrorAction Stop | Out-Null
    } catch {
        Add-Content -LiteralPath $dbg -Value ("  tts server launch failed: {0}" -f $_.Exception.Message)
        return $false
    }

    # Python start plus model load is about two seconds; allow generous headroom
    # on a cold disk before giving up and falling back.
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 400
        if (Test-TtsServer $base) { return $true }
    }
    Add-Content -LiteralPath $dbg -Value '  tts server never came up'
    return $false
}

function Speak-Local([string]$text, $cfg, [string]$engine) {
    # engine: 'neural' (Microsoft online voices) or 'piper' (offline, on-CPU).
    $port = if ($cfg.ttsPort) { [int]$cfg.ttsPort } else { 8771 }
    $base = "http://127.0.0.1:$port"

    if (-not (Test-TtsServer $base)) {
        if (-not (Start-TtsServer $cfg $base)) { return $false }
    }

    try {
        $payload = @{ text = $text; engine = $engine }
        if ($engine -eq 'neural' -and $cfg.neuralVoice) { $payload.voice = $cfg.neuralVoice }
        $body = [System.Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
        $ext  = if ($engine -eq 'neural') { '.mp3' } else { '.wav' }
        $out  = Join-Path $env:TEMP ('claude-voice-' + [guid]::NewGuid().ToString('N') + $ext)

        Invoke-RestMethod -Uri "$base/say" -Method Post -ContentType 'application/json' `
            -Body $body -OutFile $out -TimeoutSec 90 -ErrorAction Stop

        if (-not (Test-Path -LiteralPath $out) -or (Get-Item -LiteralPath $out).Length -lt 400) {
            Add-Content -LiteralPath $dbg -Value "  $engine : empty audio"
            Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
            return $false
        }
        $ok = Play-AudioFile $out
        Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
        Add-Content -LiteralPath $dbg -Value ("  {0} spoke ok={1}" -f $engine, $ok)
        return $ok
    } catch {
        Add-Content -LiteralPath $dbg -Value ("  {0} error -> falling back: {1}" -f $engine, $_.Exception.Message)
        return $false
    }
}

# ---- Engines in order of preference. Each falls through on any failure, and
#      the Windows voice at the bottom is the one that cannot fail. -----------
if (Speak-Premium $text $cfg) { exit }

# Microsoft neural voices (Andrew, Ava and friends). Natural and free, but they
# are an online service, so no internet means we drop to the next engine.
if ($cfg -and $cfg.neural) {
    if (Speak-Local $text $cfg 'neural') { exit }
}

# Piper: offline, on-CPU, free, and the engine we would fine-tune on your own
# recorded voice later. Works with no network at all.
if ($cfg -and $cfg.piper) {
    if (Speak-Local $text $cfg 'piper') { exit }
}

# ---- 2. Windows System.Speech (free, offline) -- the reliable fallback ------
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 1

# Voice preference: config windowsVoice, else voice-name.txt, else default.
$want = $null
if ($cfg -and $cfg.windowsVoice) { $want = ([string]$cfg.windowsVoice).Trim() }
if (-not $want) {
    $voiceFile = Join-Path $PSScriptRoot 'voice-name.txt'
    if (Test-Path -LiteralPath $voiceFile) { $want = (Get-Content -LiteralPath $voiceFile -Raw).Trim() }
}
if ($want) {
    $match = $s.GetInstalledVoices() |
        Where-Object { $_.Enabled -and $_.VoiceInfo.Name -like "*$want*" } |
        Select-Object -First 1
    if ($match) { $s.SelectVoice($match.VoiceInfo.Name) }
}

$s.Speak($text)
