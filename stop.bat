@echo off
setlocal
cd /d "%~dp0"

echo Stopping ASUS TUF AI RGB Sync Daemon...
powershell -Command "Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*main.py*' } | Stop-Process -Force"

echo Resetting keyboard backlight to default profile...
python -c "from tuf_lighting import AsusTufKeyboard; kb = AsusTufKeyboard(); kb.set_default(force=True); kb.close()"

echo Done.
