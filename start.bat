@echo off
setlocal
cd /d "%~dp0"

echo Starting ASUS TUF AI RGB Sync Daemon in background...
start "" wscript.exe "%~dp0start_hidden.vbs"
echo Daemon running in system tray.
