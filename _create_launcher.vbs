' 创建 OpenClaw 启动文件
' 由 Inno Setup 安装程序调用

Dim fso, oWS, sDir
Set fso = CreateObject("Scripting.FileSystemObject")
Set oWS = WScript.CreateObject("WScript.Shell")
sDir = fso.GetParentFolderName(WScript.ScriptFullName) & "\"

' ── 创建 OpenClaw.vbs（无黑窗启动器）────────────────────────────
Dim vbsPath
vbsPath = sDir & "OpenClaw.vbs"

If Not fso.FileExists(vbsPath) Then
    Dim f
    Set f = fso.CreateTextFile(vbsPath, True, False)

    f.WriteLine "' OpenClaw AI 语音助手启动器"
    f.WriteLine "' 双击此文件启动 OpenClaw（无黑窗）"
    f.WriteLine ""
    f.WriteLine "Set oWS = WScript.CreateObject(""WScript.Shell"")"
    f.WriteLine "Set fso = CreateObject(""Scripting.FileSystemObject"")"
    f.WriteLine "sDir = fso.GetParentFolderName(WScript.ScriptFullName) & ""\"""
    f.WriteLine ""
    f.WriteLine "' 按优先级查找 Python"
    f.WriteLine "Dim sPy"
    f.WriteLine "sPy = """
    f.WriteLine "Dim pyList(6)"
    f.WriteLine "pyList(0) = sDir & ""python\pythonw.exe"""
    f.WriteLine "pyList(1) = oWS.ExpandEnvironmentStrings(""%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"")"
    f.WriteLine "pyList(2) = oWS.ExpandEnvironmentStrings(""%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"")"
    f.WriteLine "pyList(3) = oWS.ExpandEnvironmentStrings(""%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"")"
    f.WriteLine "pyList(4) = oWS.ExpandEnvironmentStrings(""%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"")"
    f.WriteLine "pyList(5) = ""C:\Python313\pythonw.exe"""
    f.WriteLine "pyList(6) = ""C:\Python311\pythonw.exe"""
    f.WriteLine "Dim i"
    f.WriteLine "For i = 0 To 6"
    f.WriteLine "    If fso.FileExists(pyList(i)) Then"
    f.WriteLine "        sPy = pyList(i)"
    f.WriteLine "        Exit For"
    f.WriteLine "    End If"
    f.WriteLine "Next"
    f.WriteLine "If sPy = """" Then"
    f.WriteLine "    MsgBox ""未找到 Python！请先运行 install_full.bat 安装依赖。"" & Chr(13) & Chr(10) & Chr(13) & Chr(10) & ""路径: "" & sDir, 16, ""OpenClaw 启动失败"""
    f.WriteLine "    WScript.Quit 1"
    f.WriteLine "End If"
    f.WriteLine ""
    f.WriteLine "' 启动（0=隐藏窗口，False=不等待）"
    f.WriteLine "oWS.CurrentDirectory = sDir"
    f.WriteLine "oWS.Run """""" & sPy & """" """" & sDir & ""launcher.py"", 0, False"
    f.Close
End If

' ── 创建 openclaw_debug.bat（调试版，有黑窗）─────────────────────
Dim batPath
batPath = sDir & "openclaw_debug.bat"
If Not fso.FileExists(batPath) Then
    Dim fb
    Set fb = fso.CreateTextFile(batPath, True, False)
    fb.WriteLine "@echo off"
    fb.WriteLine "chcp 65001 >nul"
    fb.WriteLine "title OpenClaw AI 调试模式"
    fb.WriteLine "cd /d ""%~dp0"""
    fb.WriteLine "echo 正在启动 OpenClaw AI..."
    fb.WriteLine "python launcher.py %*"
    fb.WriteLine "if errorlevel 1 ("
    fb.WriteLine "    echo."
    fb.WriteLine "    echo 启动失败！请检查："
    fb.WriteLine "    echo   1. 是否已运行 install_full.bat"
    fb.WriteLine "    echo   2. 是否已配置 AI Key"
    fb.WriteLine "    echo   3. 查看日志: logs\openclaw.log"
    fb.WriteLine "    pause"
    fb.WriteLine ")"
    fb.Close
End If
