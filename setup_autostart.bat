@echo off
setlocal
cd /d "%~dp0"

echo =======================================================
echo   ASUS TUF AI RGB Sync - Auto-Start Setup
echo =======================================================
echo.

python -c "from autostart import enable_autostart, is_autostart_enabled, disable_autostart; import sys; (disable_autostart() if is_autostart_enabled() else enable_autostart()); print('Auto-start is now:', 'ENABLED' if is_autostart_enabled() else 'DISABLED')"

echo.
pause
