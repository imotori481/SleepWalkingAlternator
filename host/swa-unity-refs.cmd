@echo off
REM swa-unity-refs <project> <unity-project-dir>
REM The work is in swa-unity-refs.ps1; this only lets it be typed by
REM name once host is on PATH, like swa and swa-import.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0swa-unity-refs.ps1" %*
exit /b %errorlevel%
