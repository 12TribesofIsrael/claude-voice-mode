# Turn voice mode ON: create the flag file the hook looks for.
New-Item -ItemType File -Force "$env:TEMP\claude-voice-enabled" | Out-Null
Write-Host "Voice mode is ON. Claude will read replies aloud." -ForegroundColor Green
