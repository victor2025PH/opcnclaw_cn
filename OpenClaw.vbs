' 十三香小龙虾 启动器
' 双击启动；如果启动失败，会弹出提示。

Set oWS = WScript.CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
sDir = fso.GetParentFolderName(WScript.ScriptFullName) & "\"

' ----- Checker mode: wait then verify server, show message if failed -----
If WScript.Arguments.Count >= 1 Then
    If WScript.Arguments(0) = "check" Then
    WScript.Sleep 8000
    On Error Resume Next
    Set req = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    req.open "GET", "http://127.0.0.1:8766/", False
    req.setTimeouts 3000, 3000, 3000, 3000
    req.send
    If Err.Number <> 0 Or req.Status <> 200 Then
        r = MsgBox("App may not have started." & Chr(13) & Chr(10) & Chr(13) & Chr(10) & "Open debug window to see error? (Yes=open)", vbYesNo + vbQuestion, "Startup Check")
        If r = vbYes Then
            oWS.CurrentDirectory = sDir
            oWS.Run "cmd /c start ""Debug"" """ & sDir & "openclaw_debug.bat""", 1, False
        End If
    End If
    WScript.Quit 0
    End If
End If

' ----- Normal mode: find Python and start launcher -----
Dim sPy
sPy = ""
Dim pf, pf86, localApp
pf = oWS.ExpandEnvironmentStrings("%ProgramFiles%")
pf86 = oWS.ExpandEnvironmentStrings("%ProgramFiles(x86)%")
localApp = oWS.ExpandEnvironmentStrings("%LOCALAPPDATA%")

Dim pyList(19), j
j = 0
' Bundled Python (always check first)
pyList(j) = sDir & "python\pythonw.exe" : j = j + 1
' User-installed Python
pyList(j) = localApp & "\Programs\Python\Python313\pythonw.exe" : j = j + 1
pyList(j) = localApp & "\Programs\Python\Python312\pythonw.exe" : j = j + 1
pyList(j) = localApp & "\Programs\Python\Python311\pythonw.exe" : j = j + 1
pyList(j) = localApp & "\Programs\Python\Python310\pythonw.exe" : j = j + 1
' System-wide Python
pyList(j) = pf & "\Python313\pythonw.exe" : j = j + 1
pyList(j) = pf & "\Python312\pythonw.exe" : j = j + 1
pyList(j) = pf & "\Python311\pythonw.exe" : j = j + 1
pyList(j) = pf & "\Python310\pythonw.exe" : j = j + 1
pyList(j) = pf86 & "\Python313\pythonw.exe" : j = j + 1
pyList(j) = pf86 & "\Python312\pythonw.exe" : j = j + 1
pyList(j) = pf86 & "\Python311\pythonw.exe" : j = j + 1
pyList(j) = pf86 & "\Python310\pythonw.exe" : j = j + 1
' Root installs
pyList(j) = "C:\Python313\pythonw.exe" : j = j + 1
pyList(j) = "C:\Python312\pythonw.exe" : j = j + 1
pyList(j) = "C:\Python311\pythonw.exe" : j = j + 1
pyList(j) = "C:\Python310\pythonw.exe" : j = j + 1

Dim i
For i = 0 To j - 1
    If fso.FileExists(pyList(i)) Then
        sPy = pyList(i)
        Exit For
    End If
Next

If sPy = "" Then
    On Error Resume Next
    If fso.FileExists(oWS.ExpandEnvironmentStrings("%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe")) Then
        sPy = oWS.ExpandEnvironmentStrings("%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe")
    End If
    On Error GoTo 0
End If

If sPy = "" Then
    MsgBox "找不到 Python！" & Chr(13) & Chr(10) & Chr(13) & Chr(10) & _
           "安装目录中的内嵌 Python 丢失或损坏。" & Chr(13) & Chr(10) & _
           "请重新运行安装程序修复。" & Chr(13) & Chr(10) & Chr(13) & Chr(10) & _
           "安装目录: " & sDir, 48, "十三香小龙虾 - 启动失败"
    oWS.CurrentDirectory = sDir
    oWS.Run "cmd /k cd /d """ & sDir & """ && echo Python not found. && echo Please reinstall. && pause", 1, False
    WScript.Quit 1
End If

' Verify launcher.py exists
If Not fso.FileExists(sDir & "launcher.py") Then
    MsgBox "启动文件 launcher.py 不存在！" & Chr(13) & Chr(10) & Chr(13) & Chr(10) & _
           "安装可能不完整，请重新运行安装程序。" & Chr(13) & Chr(10) & _
           "安装目录: " & sDir, 48, "十三香小龙虾 - 启动失败"
    WScript.Quit 1
End If

oWS.CurrentDirectory = sDir

' Bundled Python uses python.exe (with console) so errors are visible
Dim useConsole, winStyle
useConsole = (InStr(LCase(sPy), LCase(sDir & "python\")) > 0)
If useConsole Then
    sPy = Replace(sPy, "pythonw.exe", "python.exe")
    winStyle = 1
Else
    winStyle = 0
End If

' Start checker in background (will pop message if server not up after 8s)
oWS.Run "wscript.exe """ & WScript.ScriptFullName & """ check", 0, False

' Start launcher with error handling
On Error Resume Next
oWS.Run """" & sPy & """ """ & sDir & "launcher.py""", winStyle, False
If Err.Number <> 0 Then
    MsgBox "启动失败！" & Chr(13) & Chr(10) & Chr(13) & Chr(10) & _
           "错误: " & Err.Description & Chr(13) & Chr(10) & _
           "Python: " & sPy & Chr(13) & Chr(10) & _
           "启动文件: " & sDir & "launcher.py" & Chr(13) & Chr(10) & Chr(13) & Chr(10) & _
           "请尝试用调试模式启动：双击 openclaw_debug.bat", 48, "十三香小龙虾 - 启动失败"
    oWS.Run "cmd /k cd /d """ & sDir & """ && """ & sPy & """ launcher.py", 1, False
End If
On Error GoTo 0
