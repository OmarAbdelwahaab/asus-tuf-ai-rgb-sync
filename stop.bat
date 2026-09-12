@echo off
setlocal
cd /d "%~dp0"

echo Stopping ASUS TUF AI RGB Sync Daemon...
powershell -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Resetting keyboard backlight to default profile...
python -c "from tuf_lighting import AsusTufKeyboard; kb = AsusTufKeyboard(); kb.set_default(force=True); kb.close()"

echo Done.
