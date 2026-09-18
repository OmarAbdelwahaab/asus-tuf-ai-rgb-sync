@echo off
setlocal

:: Determine script directory
set "SCRIPT_DIR=%~dp0"
if not exist "%SCRIPT_DIR%autostart.py" (
    if exist "D:\Keyboard_lights_Sync\autostart.py" (
        set "SCRIPT_DIR=D:\Keyboard_lights_Sync\"
    )
)

cd /d "%SCRIPT_DIR%"

echo =======================================================
echo   ASUS AI RGB Sync - Auto-Start Setup
echo =======================================================
echo.

python -c "import sys, os; sys.path.insert(0, r'%SCRIPT_DIR%'); from autostart import enable_autostart, is_autostart_enabled, disable_autostart, cleanup_stray_startup_files; cleanup_stray_startup_files(); (disable_autostart() if is_autostart_enabled() else enable_autostart()); print('Auto-start is now:', 'ENABLED' if is_autostart_enabled() else 'DISABLED')"

echo.
echo NOTE: Auto-start runs silently in the background with no console window.
echo Do NOT copy this .bat file to the Windows Startup folder.
echo.
pause
