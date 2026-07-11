# voice-guard.ps1
# Claude Code "UserPromptSubmit" hook: when voice mode is ON (flag file
# present), inject a reminder so Claude keeps spoken replies short and plain.
# Emits nothing when voice mode is off, so normal turns are unaffected.

$flag = Join-Path $env:TEMP 'claude-voice-enabled'
if (Test-Path $flag) {
    Write-Output 'Voice mode is ON. Write plain prose suitable to be read aloud: full, clear sentences a listener can follow. Be as complete as the answer needs (a few short paragraphs is fine); favor clarity over brevity, but do not pad. No tables, code blocks, bullet lists, headers, URLs, or file paths.'
}
exit 0
