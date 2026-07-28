@echo off
rem ===================================================================
rem  Claude Voice Mode - Document Reader
rem  Double-click to open the reader in your browser. Drop in a
rem  Markdown, text or PDF file and it reads it aloud with play/pause.
rem  Separate from the voice that reads Claude's replies - changing the
rem  voice here does not change that one.
rem
rem  Shares the same local server as the control panel, so if the panel
rem  is already running this just opens the reader page in it.
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
echo   Opening the Document Reader at http://127.0.0.1:%PORT%/reader
echo   Keep the "Claude Voice Mode" window that opens running while you
echo   listen. Close it when you are done to stop the server.
echo.

rem --- launch the server; harmless if one is already up -------------
rem  server.py refuses to bind a port already in use and exits with a
rem  message, so double-launching never steals the port from a panel
rem  that is already serving.
start "Claude Voice Mode" %PY% "%~dp0webapp\server.py"

rem --- give it a moment to come up, then open the reader ------------
rem  (ping is used as a portable ~2s sleep; timeout fails when stdin is redirected)
ping -n 3 127.0.0.1 >nul
start "" "http://127.0.0.1:%PORT%/reader"

exit /b 0
