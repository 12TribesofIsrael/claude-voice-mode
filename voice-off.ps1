# Turn voice mode OFF: delete the flag file so the hook stays silent.
Remove-Item -Force "$env:TEMP\claude-voice-enabled" -ErrorAction SilentlyContinue
Write-Host "Voice mode is OFF. Claude will stay silent." -ForegroundColor Yellow
