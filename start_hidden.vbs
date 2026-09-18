Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

pythonw = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe")
Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw.exe"
End If

' Run with pythonw.exe completely hidden (no console window)
WshShell.Run """" & pythonw & """ main.py", 0, False
