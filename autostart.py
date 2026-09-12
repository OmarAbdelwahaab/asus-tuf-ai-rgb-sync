import os
import sys

STARTUP_DIR = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")
SHORTCUT_VBS = os.path.join(STARTUP_DIR, "AsusTufAiRgbSync.vbs")

def get_script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def is_autostart_enabled() -> bool:
    return os.path.exists(SHORTCUT_VBS)

def enable_autostart() -> bool:
    """
    Creates a silent launcher VBS script in Windows Startup folder.
    Runs pythonw.exe main.py without displaying any command prompt window.
    """
    script_dir = get_script_dir()
    main_py = os.path.join(script_dir, "main.py")
    
    # Locate pythonw.exe in current environment
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable

    vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "{script_dir}"
WshShell.Run """{pythonw}"" ""{main_py}""", 0, False
'''
    try:
        with open(SHORTCUT_VBS, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        return True
    except Exception as e:
        print(f"Failed to enable autostart: {e}")
        return False

def disable_autostart() -> bool:
    try:
        if os.path.exists(SHORTCUT_VBS):
            os.remove(SHORTCUT_VBS)
        return True
    except Exception as e:
        print(f"Failed to disable autostart: {e}")
        return False

if __name__ == "__main__":
    print("Startup folder:", STARTUP_DIR)
    print("Currently enabled:", is_autostart_enabled())
