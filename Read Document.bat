@echo off
REM Double-click to read the newest PDF in the documents\ folder out loud.
REM Uses the free Windows voice (unlimited). While it reads:  p = pause  n = next page  q = quit
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\read-document.ps1"
echo.
pause
