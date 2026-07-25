# read-document.ps1
# Reads a PDF out loud, page by page, like an audiobook. Reuses the same voice
# stack as the rest of claude-voice-mode:
#   FREE  (default) -> Windows System.Speech (offline, UNLIMITED). This is the
#                      right choice for long documents -- a whole book costs $0.
#   PREMIUM (-Premium) -> ElevenLabs via the installed speak-worker.ps1. Natural
#                      voice, but every character counts against your ElevenLabs
#                      quota, so it's only sane for short docs. You get a warning.
#
# Extraction is done by pdftotext (Poppler), which marks page breaks with a form
# feed (0x0C) so we can track "Page X of Y" and resume where you left off.
#
# Playback controls (FREE voice only): while it's reading, press
#   p = pause / resume     n = skip to next page     q = quit
#
# Usage:
#   powershell -NoProfile -File scripts\read-document.ps1
#       -> reads the newest PDF in documents\, from where you left off
#   powershell -NoProfile -File scripts\read-document.ps1 -File documents\book.pdf -StartPage 12
#   powershell -NoProfile -File scripts\read-document.ps1 -Premium      (natural voice, uses quota)
#   powershell -NoProfile -File scripts\read-document.ps1 -List         (list PDFs and exit)

[CmdletBinding()]
param(
    [string]$File,
    [int]$StartPage = 0,        # 0 = auto (resume, or page 1 if no saved progress)
    [int]$EndPage   = 0,        # 0 = to the end
    [switch]$Premium,           # use ElevenLabs instead of the free Windows voice
    [switch]$NoResume,          # ignore saved progress, always start at page 1
    [switch]$List               # just list PDFs in documents\ and exit
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$docsDir  = Join-Path $repoRoot 'documents'
$progFile = Join-Path $docsDir '.read-progress.json'

function Write-Info($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Write-Warn2($msg) { Write-Host $msg -ForegroundColor Yellow }

# ---- List mode -------------------------------------------------------------
if ($List) {
    $pdfs = Get-ChildItem -LiteralPath $docsDir -Filter *.pdf -File | Sort-Object LastWriteTime -Descending
    if (-not $pdfs) { Write-Warn2 "No PDFs in $docsDir"; exit 0 }
    Write-Info "PDFs in documents\ (newest first):"
    $pdfs | ForEach-Object { "  {0,-45} {1:yyyy-MM-dd}" -f $_.Name, $_.LastWriteTime | Write-Host }
    exit 0
}

# ---- Resolve the target PDF ------------------------------------------------
if (-not $File) {
    $newest = Get-ChildItem -LiteralPath $docsDir -Filter *.pdf -File |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newest) { Write-Warn2 "No PDF given and none found in $docsDir"; exit 1 }
    $File = $newest.FullName
}
if (-not (Test-Path -LiteralPath $File)) { Write-Warn2 "File not found: $File"; exit 1 }
$File = (Resolve-Path -LiteralPath $File).Path
$docName = Split-Path -Leaf $File

# ---- Find pdftotext --------------------------------------------------------
# Poppler ships inside Git for Windows (mingw64\bin), which is NOT on PowerShell's
# PATH by default -- so probe the common install spots and derive it from git.exe.
$pdftotext = (Get-Command pdftotext -ErrorAction SilentlyContinue).Source
if (-not $pdftotext) {
    $cands = @(
        (Join-Path $env:ProgramFiles 'Git\mingw64\bin\pdftotext.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\mingw64\bin\pdftotext.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\mingw64\bin\pdftotext.exe')
    )
    $git = (Get-Command git -ErrorAction SilentlyContinue).Source
    if ($git) { $cands += (Join-Path (Split-Path (Split-Path $git -Parent) -Parent) 'mingw64\bin\pdftotext.exe') }
    $pdftotext = $cands | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}
if (-not $pdftotext) {
    Write-Warn2 "pdftotext not found. It ships with Git for Windows (mingw64\bin) -- install Git, or add Poppler to your PATH, then retry."
    exit 1
}

# ---- Extract to text; pages are separated by form feed (0x0C) --------------
Write-Info "Extracting text from $docName ..."
$tmpTxt = Join-Path $env:TEMP ('read-doc-' + [guid]::NewGuid().ToString('N') + '.txt')
& $pdftotext -enc UTF-8 -q -- $File $tmpTxt
if (-not (Test-Path -LiteralPath $tmpTxt)) { Write-Warn2 "Extraction failed."; exit 1 }
$raw = Get-Content -LiteralPath $tmpTxt -Raw -Encoding UTF8
Remove-Item -LiteralPath $tmpTxt -Force -ErrorAction SilentlyContinue
$formFeed = [char]0x0C
$pages = $raw -split $formFeed
$totalPages = $pages.Count
Write-Info "$totalPages page(s) of text."

# ---- Decide the starting page (arg > resume > 1) ---------------------------
$progress = @{}
if (Test-Path -LiteralPath $progFile) {
    try { (Get-Content -LiteralPath $progFile -Raw | ConvertFrom-Json).PSObject.Properties |
          ForEach-Object { $progress[$_.Name] = $_.Value } } catch { $progress = @{} }
}
if ($StartPage -le 0) {
    if (-not $NoResume -and $progress.ContainsKey($docName)) {
        $StartPage = [int]$progress[$docName]
        if ($StartPage -lt 1) { $StartPage = 1 }
        if ($StartPage -gt 1) { Write-Info "Resuming at page $StartPage (use -NoResume to start over)." }
    } else { $StartPage = 1 }
}
if ($EndPage -le 0 -or $EndPage -gt $totalPages) { $EndPage = $totalPages }

# ---- Text cleanup: make PDF text speakable ---------------------------------
# De-hyphenate line-wrapped words, drop bare page numbers, flatten newlines, and
# convert typographic punctuation to ASCII so the SAPI voice pauses instead of
# literally saying "em dash" (same fix as the Stop hook).
$emDash=[char]0x2014; $enDash=[char]0x2013; $horizBar=[char]0x2015
$lsquo=[char]0x2018; $rsquo=[char]0x2019; $ldquo=[char]0x201C; $rdquo=[char]0x201D
$ellipsis=[char]0x2026; $bullet=[char]0x2022; $nbsp=[char]0x00A0
$minusSign=[char]0x2212; $prime=[char]0x2032; $ligFi=[char]0xFB01; $ligFl=[char]0xFB02

function Format-Speakable([string]$t) {
    if ([string]::IsNullOrWhiteSpace($t)) { return '' }
    $t = $t -replace "$ligFi", 'fi' -replace "$ligFl", 'fl'
    # join words split across a line break by a hyphen: "meta-\nbolism" -> "metabolism"
    $t = [regex]::Replace($t, "-\s*\r?\n\s*", '')
    # drop lines that are just a page number
    $t = [regex]::Replace($t, "(?m)^\s*\d{1,4}\s*$", ' ')
    $t = [regex]::Replace($t, "\r?\n", ' ')            # remaining newlines -> spaces
    $t = $t -replace "(?<=\w)[$emDash$enDash$horizBar](?=\w)", '-'
    $t = $t -replace "\s*[$emDash$enDash$horizBar]\s*", ', '
    $t = $t -replace "[$lsquo$rsquo$prime]", "'"
    $t = $t -replace "[$ldquo$rdquo]", '"'
    $t = $t -replace "$ellipsis", '. '
    $t = $t -replace "[$bullet]", ' '
    $t = $t -replace "[$nbsp]", ' '
    $t = $t -replace "$minusSign", '-'
    $t = [regex]::Replace($t, '\s+', ' ').Trim()
    return $t
}

# ---- Split a page into ~1200-char chunks on sentence boundaries -------------
function Split-Chunks([string]$t, [int]$max = 1200) {
    $chunks = New-Object System.Collections.Generic.List[string]
    if ([string]::IsNullOrWhiteSpace($t)) { return $chunks }
    $sentences = [regex]::Split($t, '(?<=[.!?])\s+')
    $buf = ''
    foreach ($s in $sentences) {
        if (($buf.Length + $s.Length + 1) -gt $max -and $buf.Length -gt 0) {
            $chunks.Add($buf.Trim()); $buf = ''
        }
        $buf += ($s + ' ')
    }
    if ($buf.Trim().Length -gt 0) { $chunks.Add($buf.Trim()) }
    return $chunks
}

function Save-Progress([int]$page) {
    $progress[$docName] = $page
    try { $progress | ConvertTo-Json -Compress | Set-Content -LiteralPath $progFile -Encoding UTF8 } catch {}
}

# =====================  PREMIUM PATH (ElevenLabs)  ==========================
if ($Premium) {
    $worker = Join-Path $env:USERPROFILE '.claude\hooks\speak-worker.ps1'
    if (-not (Test-Path -LiteralPath $worker)) { $worker = Join-Path $repoRoot 'hooks\speak-worker.ps1' }
    # rough character count for the quota warning
    $charEst = 0; for ($p = $StartPage; $p -le $EndPage; $p++) { $charEst += (Format-Speakable $pages[$p-1]).Length }
    Write-Warn2 ("PREMIUM voice: ~{0:N0} characters will be sent to ElevenLabs (pages {1}-{2})." -f $charEst, $StartPage, $EndPage)
    Write-Warn2 "That counts against your ElevenLabs quota. Ctrl+C now to cancel; starting in 4s..."
    Start-Sleep -Seconds 4
    for ($p = $StartPage; $p -le $EndPage; $p++) {
        $clean = Format-Speakable $pages[$p-1]
        if (-not $clean) { Save-Progress ($p+1); continue }
        Write-Info ("Page {0} of {1} (premium)..." -f $p, $totalPages)
        foreach ($chunk in (Split-Chunks $clean 2400)) {
            $txt = Join-Path $env:TEMP ('read-doc-' + [guid]::NewGuid().ToString('N') + '.txt')
            Set-Content -LiteralPath $txt -Value $chunk -Encoding UTF8
            & powershell.exe -NoProfile -File $worker $txt | Out-Null   # synchronous: worker deletes the file
        }
        Save-Progress ($p+1)
    }
    Write-Info "Done."
    exit 0
}

# =====================  FREE PATH (Windows System.Speech)  ==================
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0

# Match the voice chosen in the control panel (voice-config.json windowsVoice),
# else voice-name.txt, else the system default.
$want = $null
foreach ($h in @((Join-Path $env:USERPROFILE '.claude\hooks'), (Join-Path $repoRoot 'hooks'))) {
    $cfgFile = Join-Path $h 'voice-config.json'
    if (-not $want -and (Test-Path -LiteralPath $cfgFile)) {
        try { $c = Get-Content -LiteralPath $cfgFile -Raw | ConvertFrom-Json; if ($c.windowsVoice) { $want = ([string]$c.windowsVoice).Trim() } } catch {}
    }
    $vn = Join-Path $h 'voice-name.txt'
    if (-not $want -and (Test-Path -LiteralPath $vn)) { $want = (Get-Content -LiteralPath $vn -Raw).Trim() }
}
if ($want) {
    $match = $synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Name -like "*$want*" } | Select-Object -First 1
    if ($match) { $synth.SelectVoice($match.VoiceInfo.Name) }
}

Write-Info ("Reading '{0}' with the free Windows voice ({1})." -f $docName, $synth.Voice.Name)

# Key controls only work with a real interactive console. If stdin is redirected
# (e.g. launched from a pipe), Console.KeyAvailable throws -- detect that once and
# just play straight through without controls.
$canKeys = $true
try { $null = [Console]::KeyAvailable } catch { $canKeys = $false }
if ($canKeys) { Write-Info "Controls:  p = pause/resume   n = next page   q = quit" }
else { Write-Warn2 "(No interactive console - playing straight through, no key controls.)" }

$quit = $false
for ($p = $StartPage; $p -le $EndPage -and -not $quit; $p++) {
    $clean = Format-Speakable $pages[$p-1]
    if (-not $clean) { Save-Progress ($p+1); continue }
    Write-Host ("`nPage {0} of {1}" -f $p, $totalPages) -ForegroundColor Green
    $chunks = Split-Chunks $clean 1200
    $skipPage = $false
    foreach ($chunk in $chunks) {
        if ($quit -or $skipPage) { break }
        $synth.SpeakAsync($chunk) | Out-Null
        # poll for key presses while this chunk plays
        while ($synth.State -eq 'Speaking' -or $synth.State -eq 'Paused') {
            if ($canKeys -and [Console]::KeyAvailable) {
                $k = [Console]::ReadKey($true).Key
                switch ($k) {
                    'P' { if ($synth.State -eq 'Paused') { $synth.Resume(); Write-Host '  [resume]' -ForegroundColor DarkGray }
                          else { $synth.Pause(); Write-Host '  [paused - press p to resume]' -ForegroundColor DarkGray } }
                    'N' { $synth.SpeakAsyncCancelAll(); $skipPage = $true; Write-Host '  [next page]' -ForegroundColor DarkGray }
                    'Q' { $synth.SpeakAsyncCancelAll(); $quit = $true; Write-Host '  [quit]' -ForegroundColor DarkGray }
                }
            }
            Start-Sleep -Milliseconds 80
        }
    }
    if (-not $quit) { Save-Progress ($p+1) } else { Save-Progress $p }
}
$synth.Dispose()
if ($quit) { Write-Info "Stopped. Run again to resume from here." } else { Write-Info "Finished the document." }
