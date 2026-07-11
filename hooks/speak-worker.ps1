# speak-worker.ps1
# Speaks a chunk of plain text, then deletes the temp file. Launched hidden by
# speak-response.ps1. Kept as a plain named script (no encoded/obfuscated
# command line) so antivirus leaves it alone.
#
# Two voices:
#   PREMIUM  -> ElevenLabs (natural). Used only when voice-config.json has
#               premium=true, an apiKey, and a voiceId. Falls back automatically
#               to the Windows voice on any error (offline, bad key, no credits).
#   DEFAULT  -> Windows System.Speech (free, offline). Always the fallback.
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

function Play-AudioFile([string]$path) {
    # Try WPF MediaPlayer first, then Windows Media Player COM as a fallback.
    $len = (Get-Item -LiteralPath $path).Length
    $estMs = [int](($len / 16000.0) * 1000) + 700   # ~128 kbps mp3 => ~16 KB/s
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

# ---- 1. Try premium; on any failure fall through to the Windows voice ------
if (Speak-Premium $text $cfg) { exit }

# ---- 2. Windows System.Speech (free, offline) — the reliable fallback ------
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
