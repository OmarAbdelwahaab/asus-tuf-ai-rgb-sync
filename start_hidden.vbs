Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' Run with pythonw.exe completely hidden (no console window)
WshShell.Run "pythonw.exe main.py", 0, False
