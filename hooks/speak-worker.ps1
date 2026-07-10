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
$s.Speak($text)
