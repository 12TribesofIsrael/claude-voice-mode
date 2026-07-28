# sapi-to-wav.ps1
# Speaks text into a WAV file instead of out of the speakers.
#
# The document reader needs audio it can hand to a browser, but every other
# Windows-voice path in this project plays straight to the sound card and returns
# nothing. SetOutputToWaveFile is the one call that redirects it to a file.
#
# Kept as a plain named script, with no encoded or obfuscated command line, for
# the same reason speak-worker.ps1 is: Norton's command-line heuristic flags
# base64 -EncodedCommand and leaves ordinary script files alone.
#
# Usage:
#   powershell -NoProfile -File sapi-to-wav.ps1 -TextFile in.txt -OutFile out.wav
#                                               [-Voice "Zira"] [-Rate 0]
param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [string]$Voice = '',
    [int]$Rate = 0
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $TextFile)) {
    Write-Error "Text file not found: $TextFile"
    exit 1
}

# Read as UTF-8 explicitly. Get-Content without -Encoding uses the ANSI codepage,
# which turns every non-ASCII character into mojibake the voice then reads aloud.
$text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) {
    Write-Error 'Empty text'
    exit 1
}

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.Rate = $Rate

    if ($Voice) {
        $match = $synth.GetInstalledVoices() |
            Where-Object { $_.Enabled -and $_.VoiceInfo.Name -like "*$Voice*" } |
            Select-Object -First 1
        if ($match) { $synth.SelectVoice($match.VoiceInfo.Name) }
    }

    $synth.SetOutputToWaveFile($OutFile)
    $synth.Speak($text)
    # Release the file handle before we exit, or the caller reads a locked,
    # half-flushed WAV.
    $synth.SetOutputToNull()
}
finally {
    $synth.Dispose()
}

if (-not (Test-Path -LiteralPath $OutFile)) {
    Write-Error 'No audio produced'
    exit 1
}
exit 0
