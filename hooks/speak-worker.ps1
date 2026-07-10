# speak-worker.ps1
# Speaks a chunk of plain text via Windows System.Speech, then deletes the
# temp file. Launched hidden by speak-response.ps1. Kept as a plain named
# script (no encoded/obfuscated command line) so antivirus leaves it alone.
param([string]$File)

$ErrorActionPreference = 'SilentlyContinue'

if (-not $File -or -not (Test-Path -LiteralPath $File)) { exit }

$text = Get-Content -LiteralPath $File -Raw
Remove-Item -LiteralPath $File -Force
if ([string]::IsNullOrWhiteSpace($text)) { exit }

Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 1

# Optional voice preference: put a name (or part of one, e.g. "Mark", "Zira")
# in voice-name.txt next to this script. Falls back to the default voice if
# the file is missing or the name isn't installed.
$voiceFile = Join-Path $PSScriptRoot 'voice-name.txt'
if (Test-Path -LiteralPath $voiceFile) {
    $want = (Get-Content -LiteralPath $voiceFile -Raw).Trim()
    if ($want) {
        $match = $s.GetInstalledVoices() |
            Where-Object { $_.Enabled -and $_.VoiceInfo.Name -like "*$want*" } |
            Select-Object -First 1
        if ($match) { $s.SelectVoice($match.VoiceInfo.Name) }
    }
}

$s.Speak($text)
