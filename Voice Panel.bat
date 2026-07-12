@echo off
rem ===================================================================
rem  Claude Voice Mode - double-click launcher
rem  Opens the control panel in your browser. From the panel you can
rem  turn voice on/off, switch free vs premium, pick a voice, etc.
rem  No PowerShell, no manual scripts - just double-click this file.
rem ===================================================================
setlocal
cd /d "%~dp0"

rem --- find Python 3 -------------------------------------------------
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if not defined PY (
  echo.
  echo   Python 3 is required but was not found on this PC.
  echo   Install it from https://www.python.org/downloads/ and
  echo   then double-click this file again.
  echo.
  pause
  exit /b 1
)

set "PORT=8770"
if defined VOICE_PANEL_PORT set "PORT=%VOICE_PANEL_PORT%"

echo.
echo   Starting the Claude Voice Mode panel at http://127.0.0.1:%PORT%/
echo   Keep the "Claude Voice Mode" window that opens running while you
echo   use the panel. Close it when you are done to stop the server.
echo.

rem --- launch the local server in its own window --------------------
start "Claude Voice Mode" %PY% "%~dp0webapp\server.py"

rem --- give it a moment to come up, then open the panel -------------
rem  (ping is used as a portable ~2s sleep; timeout fails when stdin is redirected)
ping -n 3 127.0.0.1 >nul
start "" "http://127.0.0.1:%PORT%/"

exit /b 0
