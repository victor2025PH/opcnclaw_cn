' OpenClaw AI Voice Assistant Launcher
' Double-click to start OpenClaw (no black window)

Set oWS = WScript.CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
sDir = fso.GetParentFolderName(WScript.ScriptFullName) & "\"

' Find Python - check common locations
Dim sPy
sPy = ""
Dim pyList(7)
pyList(0) = sDir & "python\pythonw.exe"
pyList(1) = oWS.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe")
pyList(2) = oWS.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe")
pyList(3) = oWS.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe")
pyList(4) = oWS.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe")
pyList(5) = "C:\Python313\pythonw.exe"
pyList(6) = "C:\Python312\pythonw.exe"
pyList(7) = "C:\Python311\pythonw.exe"

Dim i
For i = 0 To 7
    If fso.FileExists(pyList(i)) Then
        sPy = pyList(i)
        Exit For
    End If
Next

If sPy = "" Then
    ' Try pythonw.exe from PATH
    On Error Resume Next
    oWS.Run "where pythonw", 0, True
    If Err.Number = 0 Then sPy = "pythonw.exe"
    On Error GoTo 0
End If

If sPy = "" Then
    MsgBox "Python not found! Please run install_full.bat first." & Chr(13) & Chr(10) & Chr(13) & Chr(10) & _
           "Dir: " & sDir, 16, "OpenClaw - Startup Failed"
    WScript.Quit 1
End If

' Start launcher.py (hidden window, no wait)
oWS.CurrentDirectory = sDir
oWS.Run """" & sPy & """ """ & sDir & "launcher.py""", 0, False
