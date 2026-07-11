# speak-response.ps1
# Claude Code "Stop" hook: reads the hook JSON from stdin, cleans the
# assistant's final message, and speaks it via Windows System.Speech.
# Fires the speech DETACHED + HIDDEN so Claude Code is never blocked and
# no console window flashes. Only speaks when the toggle flag file exists.

$ErrorActionPreference = 'SilentlyContinue'

# 1. Toggle gate -- only speak when the flag file is present.
$flag = Join-Path $env:TEMP 'claude-voice-enabled'
if (-not (Test-Path $flag)) { exit 0 }

# 2. Read the hook JSON from stdin.
$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }

try { $data = $raw | ConvertFrom-Json } catch { exit 0 }

$text = $data.last_assistant_message

# Fallback: some Claude Code builds/surfaces don't populate last_assistant_message
# on the Stop payload. If it's empty, read the reply from the transcript file --
# walk the JSONL backward to the most recent assistant message that has text.
if ([string]::IsNullOrWhiteSpace($text) -and $data.transcript_path) {
    $tp = $data.transcript_path
    if (Test-Path -LiteralPath $tp) {
        $lines = Get-Content -LiteralPath $tp -Encoding UTF8
        for ($i = $lines.Count - 1; $i -ge 0; $i--) {
            $line = $lines[$i]
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            try { $entry = $line | ConvertFrom-Json } catch { continue }
            if ($entry.type -ne 'assistant' -and $entry.message.role -ne 'assistant') { continue }
            $content = $entry.message.content
            if (-not $content) { continue }
            $buf = ''
            if ($content -is [string]) { $buf = $content }
            else { foreach ($b in $content) { if ($b.type -eq 'text' -and $b.text) { $buf += $b.text + ' ' } } }
            if (-not [string]::IsNullOrWhiteSpace($buf)) { $text = $buf.Trim(); break }
        }
    }
}

if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }   # guards /clear-style empties

# 3. Strip markdown / code / URLs / file paths so only prose is spoken.
$text = [regex]::Replace($text, '(?s)```.*?```', ' ')                 # fenced code blocks
$text = [regex]::Replace($text, '`([^`]*)`', '$1')                    # inline code
$text = [regex]::Replace($text, '!?\[([^\]]*)\]\([^)]*\)', '$1')      # md links/images -> label
$text = [regex]::Replace($text, 'https?://\S+', ' ')                  # bare URLs
$text = [regex]::Replace($text, '[A-Za-z]:\\[^\s]+', ' ')             # Windows paths C:\...
$text = [regex]::Replace($text, '(?<=\s|^)[~./][^\s]*/[^\s]+', ' ')   # unix-ish paths
$text = [regex]::Replace($text, '(?m)^\s{0,3}#{1,6}\s*', '')          # headers
$text = [regex]::Replace($text, '(?m)^\s*[-*+]\s+', '')               # bullets
$text = [regex]::Replace($text, '[*_>#|`~]', ' ')                     # stray md punctuation
$text = [regex]::Replace($text, '\s+', ' ').Trim()                    # collapse whitespace
if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }

# 4. Trim to ~6000 chars on a word boundary.
if ($text.Length -gt 6000) {
    $text = $text.Substring(0, 6000)
    $sp = $text.LastIndexOf(' ')
    if ($sp -gt 5400) { $text = $text.Substring(0, $sp) }
}

# 5. Write the cleaned text to a temp file and hand it to the worker script.
#    Plain text + a named .ps1 file avoids Norton's IDP.HELU "command line
#    detection" heuristic (which flags base64 -EncodedCommand and WMI spawns).
$txtFile = Join-Path $env:TEMP ('claude-voice-' + [guid]::NewGuid().ToString('N') + '.txt')
Set-Content -LiteralPath $txtFile -Value $text -Encoding UTF8

# 6. Launch the worker hidden and detached so the hook never blocks and no
#    window flashes. Ordinary "powershell -File <script> <arg>" — nothing
#    obfuscated for the antivirus to trip on.
$worker = Join-Path $PSScriptRoot 'speak-worker.ps1'
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-File', $worker, $txtFile
)

exit 0
