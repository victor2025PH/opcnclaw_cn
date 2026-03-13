; ╔══════════════════════════════════════════════════════════════╗
; ║   OpenClaw AI v3.2 — Inno Setup 安装脚本（双版本）          ║
; ║   最小安装（云端）≈ 50MB  /  完整安装（本地GPU）≈ 1.5GB     ║
; ╚══════════════════════════════════════════════════════════════╝
;
; 编译命令（CMD）:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; 生成文件: dist\installer\OpenClaw-v3.2-Setup.exe

#define AppName       "OpenClaw AI 语音助手"
#define AppVersion    "3.2.0"
#define AppPublisher  "OpenClaw Team"
#define AppURL        "https://github.com/openclaw/voice"
#define AppExeName    "OpenClaw.vbs"
#define SourceDir     "."

[Setup]
AppId={{C3D4E5F6-A7B8-9012-CDEF-123456789ABC}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\OpenClaw
DefaultGroupName=OpenClaw AI 语音助手
AllowNoIcons=yes
LicenseFile=
; 输出目录和文件名
OutputDir=dist\installer
OutputBaseFilename=OpenClaw-v3.2-Setup
; 图标
SetupIconFile=assets\icon.ico
; 压缩（lzma2/ultra 最高压缩率）
Compression=lzma2/ultra64
SolidCompression=yes
CompressionThreads=auto
; 界面风格
WizardStyle=modern
WizardSizePercent=120
; 权限（不要求管理员，避免UAC弹窗）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 版本信息
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=全双工本地部署 AI 语音助手
VersionInfoProductName={#AppName}
; 关闭运行中的程序
CloseApplications=yes
CloseApplicationsFilter=*OpenClaw*,*launcher*
; 安装后重启设置
RestartIfNeededByRun=no
; 最低 Windows 版本：Windows 10
MinVersion=10.0

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english";     MessagesFile: "compiler:Default.isl"

[Types]
Name: "minimal"; Description: "最小安装（云端模式，约 50MB，推荐低配电脑）"
Name: "full";    Description: "完整安装（含本地 GPU 模型，约 1.5GB，推荐高配电脑）"
Name: "custom";  Description: "自定义安装"; Flags: iscustom

[Components]
Name: "core";     Description: "核心组件（必选）";           Types: minimal full custom; Flags: fixed
Name: "localai";  Description: "本地 AI 引擎（PyTorch + 语音模型，需 GPU）"; Types: full
Name: "vision";   Description: "视觉控制（OCR + 屏幕识别）"; Types: full

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式";     GroupDescription: "附加图标:"; Flags: checkedonce
Name: "startmenu";   Description: "创建开始菜单快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce
Name: "autostart";   Description: "开机自动启动";          GroupDescription: "开机行为:"

[Files]
; ── 核心应用文件 ──────────────────────────────────────────────
Source: "launcher.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt";      DestDir: "{app}"; Flags: ignoreversion
Source: "requirements-full.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.template";         DestDir: "{app}"; DestName: ".env.template"; Flags: ignoreversion
Source: "安装说明.md";            DestDir: "{app}"; Flags: ignoreversion
Source: "OpenClaw使用说明书.md";  DestDir: "{app}"; Flags: ignoreversion
Source: "start.bat";             DestDir: "{app}"; Flags: ignoreversion
Source: "OpenClaw.vbs";          DestDir: "{app}"; Flags: ignoreversion
Source: "openclaw_debug.bat";    DestDir: "{app}"; Flags: ignoreversion
Source: "_create_launcher.vbs";  DestDir: "{app}"; Flags: ignoreversion
Source: "config.ini";            DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

; ── 源代码目录 ────────────────────────────────────────────────
Source: "src\*";               DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "skills\*";            DestDir: "{app}\skills"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── 图标资源 ──────────────────────────────────────────────────
Source: "assets\icon.ico";     DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\icon.png";     DestDir: "{app}\assets"; Flags: ignoreversion

; ── 安装辅助脚本（安装完成后自动运行） ────────────────────────
Source: "install_full.bat";    DestDir: "{app}"; Flags: ignoreversion

; ── 创建必要的空目录 ──────────────────────────────────────────
Source: "assets\icon.ico";     DestDir: "{app}\data";   Flags: ignoreversion; AfterInstall: CreateDirs
Source: "assets\icon.ico";     DestDir: "{app}\models"; Flags: ignoreversion; AfterInstall: CreateDirs
Source: "assets\icon.ico";     DestDir: "{app}\logs";   Flags: ignoreversion; AfterInstall: CreateDirs
Source: "assets\icon.ico";     DestDir: "{app}\ssl";    Flags: ignoreversion; AfterInstall: CreateDirs

[Icons]
; 桌面快捷方式
Name: "{autodesktop}\OpenClaw AI助手";    Filename: "{app}\OpenClaw.vbs"; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\assets\icon.ico"; \
  Comment: "OpenClaw AI 语音助手 — 全双工对话"; \
  Tasks: desktopicon

; 开始菜单
Name: "{group}\OpenClaw AI助手";          Filename: "{app}\OpenClaw.vbs"; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\assets\icon.ico"; \
  Tasks: startmenu
Name: "{group}\命令行模式（调试）";        Filename: "{app}\openclaw_debug.bat"; \
  WorkingDir: "{app}"; \
  Tasks: startmenu
Name: "{group}\使用说明";                 Filename: "{app}\OpenClaw使用说明书.md"; \
  Tasks: startmenu
Name: "{group}\卸载 OpenClaw";            Filename: "{uninstallexe}"; \
  Tasks: startmenu

[Registry]
; 开机自启（写入注册表）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "OpenClawAI"; \
  ValueData: "wscript.exe ""{app}\OpenClaw.vbs"""; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
; 安装完成后弹出"立即启动"选项
Filename: "{app}\OpenClaw.vbs"; \
  Description: "立即启动 OpenClaw AI 助手"; \
  Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\src\__pycache__"
Type: filesandordirs; Name: "{app}\skills\__pycache__"
; 保留用户数据（注释掉以下行则卸载时保留）
; Type: filesandordirs; Name: "{app}\data"
; Type: filesandordirs; Name: "{app}\.env"

[Code]
var
  LogFile: String;

// ─── 日志 ──────────────────────────────────────────────
procedure LogMsg(Msg: String);
begin
  SaveStringToFile(LogFile,
    '[' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0) + '] ' + Msg + #13#10, True);
end;

// ─── 检测 Python ───────────────────────────────────────
function FindPython(): String;
var
  LocalAppData: String;
  I: Integer;
  Paths: array[0..5] of String;
  ResultCode: Integer;
begin
  Result := '';
  LocalAppData := GetEnv('LOCALAPPDATA');

  Paths[0] := LocalAppData + '\Programs\Python\Python313\python.exe';
  Paths[1] := LocalAppData + '\Programs\Python\Python312\python.exe';
  Paths[2] := LocalAppData + '\Programs\Python\Python311\python.exe';
  Paths[3] := 'C:\Python313\python.exe';
  Paths[4] := 'C:\Python312\python.exe';
  Paths[5] := 'C:\Python311\python.exe';

  for I := 0 to 5 do
  begin
    if FileExists(Paths[I]) then
    begin
      Result := Paths[I];
      LogMsg('Found Python: ' + Result);
      Exit;
    end;
  end;

  if Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
    begin
      Result := 'python';
      LogMsg('Found Python in PATH');
    end;
  end;
end;

// ─── 用 PowerShell 下载文件 ────────────────────────────
function DownloadFile(URL, DestPath: String): Boolean;
var
  ResultCode: Integer;
begin
  LogMsg('Downloading: ' + URL);
  Exec('powershell', '-Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile(''' + URL + ''', ''' + DestPath + ''')"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := FileExists(DestPath);
  if Result then
    LogMsg('Download OK: ' + DestPath)
  else
    LogMsg('Download FAILED: ' + URL);
end;

// ─── 运行 pip install（可选弹出窗口） ─────────────────
function RunPip(PythonExe, Args: String; Visible: Boolean): Integer;
var
  ShowMode, ResultCode: Integer;
begin
  if Visible then
    ShowMode := SW_SHOWNORMAL
  else
    ShowMode := SW_HIDE;

  LogMsg('pip> ' + PythonExe + ' -m pip ' + Args);

  if Exec(PythonExe, '-m pip ' + Args, ExpandConstant('{app}'), ShowMode, ewWaitUntilTerminated, ResultCode) then
    Result := ResultCode
  else
    Result := -1;

  LogMsg('pip exit code: ' + IntToStr(Result));
end;

// ─── 生成 SSL 证书（CA + Server，含局域网 IP）─────────
procedure GenerateSSL(PythonExe, AppDir: String);
var
  Script, ScriptPath: String;
  ResultCode: Integer;
begin
  ScriptPath := AppDir + '\logs\_gen_ssl.py';
  Script :=
    'import sys, os' + #13#10 +
    'os.chdir(sys.argv[1] if len(sys.argv) > 1 else ".")' + #13#10 +
    'sys.path.insert(0, ".")' + #13#10 +
    'try:' + #13#10 +
    '    import subprocess' + #13#10 +
    '    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)' + #13#10 +
    '    from src.server.certs import ensure_certs' + #13#10 +
    '    ca, crt, key = ensure_certs("certs")' + #13#10 +
    '    print(f"SSL OK: CA={ca} Cert={crt} Key={key}")' + #13#10 +
    'except Exception as e:' + #13#10 +
    '    print(f"certs.py failed ({e}), using fallback...")' + #13#10 +
    '    try:' + #13#10 +
    '        from cryptography import x509' + #13#10 +
    '        from cryptography.x509.oid import NameOID' + #13#10 +
    '        from cryptography.hazmat.primitives import hashes, serialization' + #13#10 +
    '        from cryptography.hazmat.primitives.asymmetric import rsa' + #13#10 +
    '        import datetime, ipaddress, socket' + #13#10 +
    '        os.makedirs("certs", exist_ok=True)' + #13#10 +
    '        san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]' + #13#10 +
    '        try:' + #13#10 +
    '            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)' + #13#10 +
    '            s.connect(("8.8.8.8", 80))' + #13#10 +
    '            san.append(x509.IPAddress(ipaddress.IPv4Address(s.getsockname()[0])))' + #13#10 +
    '            s.close()' + #13#10 +
    '        except: pass' + #13#10 +
    '        key = rsa.generate_private_key(65537, 2048)' + #13#10 +
    '        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OpenClaw Voice Server")])' + #13#10 +
    '        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)' + #13#10 +
    '            .public_key(key.public_key()).serial_number(x509.random_serial_number())' + #13#10 +
    '            .not_valid_before(datetime.datetime.utcnow())' + #13#10 +
    '            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))' + #13#10 +
    '            .add_extension(x509.SubjectAlternativeName(san), critical=False)' + #13#10 +
    '            .sign(key, hashes.SHA256()))' + #13#10 +
    '        open("certs/server.crt","wb").write(cert.public_bytes(serialization.Encoding.PEM))' + #13#10 +
    '        open("certs/server.key","wb").write(key.private_bytes(serialization.Encoding.PEM,' + #13#10 +
    '            serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))' + #13#10 +
    '        print("SSL OK (fallback, self-signed)")' + #13#10 +
    '    except Exception as e2:' + #13#10 +
    '        print(f"SSL FAIL: {e2}")' + #13#10 +
    '        sys.exit(1)' + #13#10;

  SaveStringToFile(ScriptPath, Script, False);
  Exec(PythonExe, '"' + ScriptPath + '" "' + AppDir + '"', AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
  DeleteFile(ScriptPath);

  if ResultCode = 0 then
    LogMsg('SSL certificate generated (CA + Server with LAN IPs)')
  else
    LogMsg('WARNING: SSL generation failed (code ' + IntToStr(ResultCode) + ')');
end;

// ═══════════════════════════════════════════════════════
//  主安装流程：分步执行，带进度反馈
// ═══════════════════════════════════════════════════════
procedure RunInstallSteps();
var
  Page: TOutputProgressWizardPage;
  PythonExe, AppDir: String;
  PyInstaller, VcInstaller: String;
  ResultCode: Integer;
  Errors: String;
begin
  AppDir := ExpandConstant('{app}');
  LogFile := AppDir + '\logs\install.log';
  ForceDirectories(AppDir + '\logs');
  ForceDirectories(AppDir + '\ssl');
  Errors := '';

  SaveStringToFile(LogFile,
    '================================================' + #13#10 +
    ' OpenClaw AI v3.2 Installation Log' + #13#10 +
    ' ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0) + #13#10 +
    '================================================' + #13#10, False);

  Page := CreateOutputProgressPage(
    '正在配置运行环境',
    '安装程序正在下载并配置所需组件，请耐心等待...' + #13#10 +
    '（详细日志: ' + AppDir + '\logs\install.log）'
  );
  Page.Show;

  try
    // ── 步骤 1/7：检测/安装 Python ──────────────────
    Page.SetText('检测 Python 运行环境...', '');
    Page.SetProgress(0, 100);
    LogMsg('=== [Step 1/7] Detect Python ===');

    PythonExe := FindPython();

    if PythonExe = '' then
    begin
      Page.SetText(
        '正在下载 Python 3.11（约 25MB）...',
        '从华为云镜像下载，请确保网络畅通');
      LogMsg('Python not found, downloading installer...');

      PyInstaller := ExpandConstant('{tmp}\python-311-setup.exe');

      if not DownloadFile(
        'https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-amd64.exe',
        PyInstaller) then
      begin
        Page.SetText(
          '华为云镜像下载失败，正在尝试官方源...',
          '官方源速度可能较慢，请耐心等待');
        DownloadFile(
          'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe',
          PyInstaller);
      end;

      if FileExists(PyInstaller) then
      begin
        Page.SetText('正在安装 Python 3.11...', '静默安装中，请勿操作');
        Exec(PyInstaller, '/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=0',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        DeleteFile(PyInstaller);
        LogMsg('Python installer exit code: ' + IntToStr(ResultCode));
        PythonExe := FindPython();
      end;

      if PythonExe = '' then
      begin
        LogMsg('FATAL: Python not available after install attempt');
        MsgBox(
          'Python 安装失败！' + #13#10 + #13#10 +
          '请手动安装 Python 3.11 后，运行安装目录下的 install_full.bat 完成安装。' + #13#10 + #13#10 +
          '下载地址: https://www.python.org/downloads/release/python-3119/' + #13#10 +
          '日志文件: ' + LogFile,
          mbError, MB_OK);
        Exit;
      end;
    end;

    LogMsg('Using Python: ' + PythonExe);
    Page.SetProgress(10, 100);

    // ── 步骤 2/7：检测/安装 VC++ ────────────────────
    Page.SetText('检测 Visual C++ 运行库...', '');
    Page.SetProgress(12, 100);
    LogMsg('=== [Step 2/7] Check VC++ Runtime ===');

    if not RegKeyExists(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64') and
       not RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64') then
    begin
      Page.SetText('正在下载 Visual C++ 运行库（5MB）...', '');
      VcInstaller := ExpandConstant('{tmp}\vcredist_x64.exe');

      if DownloadFile('https://aka.ms/vs/17/release/vc_redist.x64.exe', VcInstaller) then
      begin
        Page.SetText('正在安装 Visual C++ 运行库...', '');
        Exec(VcInstaller, '/quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        DeleteFile(VcInstaller);
        LogMsg('VC++ install exit code: ' + IntToStr(ResultCode));
      end else
      begin
        Errors := Errors + '- VC++ 运行库下载失败（PyTorch 可能无法运行）' + #13#10;
        LogMsg('WARNING: VC++ download failed');
      end;
    end else
      LogMsg('VC++ runtime: already installed');

    Page.SetProgress(15, 100);

    // ── 步骤 3/7：配置 pip 镜像 ────────────────────
    Page.SetText('配置 pip 国内加速镜像（阿里云）...', '');
    Page.SetProgress(16, 100);
    LogMsg('=== [Step 3/7] Configure pip mirror ===');

    RunPip(PythonExe, 'config set global.index-url https://mirrors.aliyun.com/pypi/simple/', False);
    RunPip(PythonExe, 'config set global.trusted-host mirrors.aliyun.com', False);
    RunPip(PythonExe, 'install --upgrade pip -q', False);
    LogMsg('pip mirror configured: aliyun');
    Page.SetProgress(20, 100);

    // ── 步骤 4/7：安装核心依赖（最小包） ───────────
    Page.SetText(
      '正在安装核心依赖包（云端模式，约 1-3 分钟）...',
      '已弹出命令行窗口显示下载详情。如果长时间无进度，请检查网络连接。');
    Page.SetProgress(20, 100);
    LogMsg('=== [Step 4/7] Install core dependencies (minimal) ===');

    ResultCode := RunPip(PythonExe,
      'install --no-cache-dir -r "' + AppDir + '\requirements.txt"',
      True);

    if ResultCode <> 0 then
    begin
      Errors := Errors + '- 核心依赖安装异常（错误码 ' + IntToStr(ResultCode) + '）' + #13#10;
      LogMsg('WARNING: Core deps failed: ' + IntToStr(ResultCode));
    end;

    Page.SetProgress(50, 100);

    // ── 步骤 5/7：安装本地 AI 模型（仅完整版） ─────
    if IsComponentSelected('localai') then
    begin
      Page.SetText(
        '正在安装本地 AI 引擎（PyTorch + 语音模型，约 10-15 分钟）...',
        '您选择了完整安装，正在下载本地 GPU 模型。如果下载速度慢，请耐心等待。');
      Page.SetProgress(50, 100);
      LogMsg('=== [Step 5/7] Install local AI (Full mode) ===');

      ResultCode := RunPip(PythonExe,
        'install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu',
        True);

      if ResultCode <> 0 then
      begin
        LogMsg('PyTorch official source failed, trying aliyun mirror...');
        ResultCode := RunPip(PythonExe, 'install --no-cache-dir torch', True);
      end;

      if ResultCode <> 0 then
      begin
        Errors := Errors + '- PyTorch 安装失败（错误码 ' + IntToStr(ResultCode) + '）' + #13#10;
        LogMsg('ERROR: PyTorch install failed');
      end;

      Page.SetProgress(70, 100);

      ResultCode := RunPip(PythonExe,
        'install --no-cache-dir faster-whisper funasr silero-vad torchaudio transformers',
        True);

      if ResultCode <> 0 then
      begin
        Errors := Errors + '- 本地语音模型安装异常（错误码 ' + IntToStr(ResultCode) + '）' + #13#10;
        LogMsg('WARNING: Local STT install failed');
      end;
    end else
    begin
      Page.SetText(
        '跳过本地 AI 模型（最小安装模式，使用云端 API）...',
        '安装 silero-vad 用于语音检测');
      LogMsg('=== [Step 5/7] Minimal mode — skip local AI ===');

      RunPip(PythonExe, 'install silero-vad', True);
    end;

    Page.SetProgress(80, 100);

    // ── 步骤 6/7：安装视觉组件（仅完整版） ─────────
    if IsComponentSelected('vision') then
    begin
      Page.SetText('正在安装视觉控制组件（OCR + 屏幕识别）...', '');
      LogMsg('=== [Step 6/7] Install vision components ===');
      RunPip(PythonExe,
        'install --no-cache-dir rapidocr-onnxruntime mss pyautogui uiautomation',
        True);
    end else
    begin
      LogMsg('=== [Step 6/7] Skip vision (minimal mode) ===');
    end;

    Page.SetProgress(90, 100);

    // ── 步骤 7/7：生成 SSL 证书 ────────────────────
    Page.SetText('正在生成 SSL 证书（HTTPS 必需）...', '');
    Page.SetProgress(92, 100);
    LogMsg('=== [Step 7/7] Generate SSL certificate ===');

    GenerateSSL(PythonExe, AppDir);

    Page.SetProgress(100, 100);

    // ── 安装结果汇总 ────────────────────────────────
    LogMsg('================================================');
    LogMsg('Installation finished: ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0));

    if Errors <> '' then
    begin
      LogMsg('WARNINGS: ' + Errors);
      MsgBox(
        '安装已完成，但以下步骤有异常：' + #13#10 + #13#10 +
        Errors + #13#10 +
        '这些组件可能影响部分功能。您可以：' + #13#10 +
        '  1. 手动运行 install_full.bat 重试' + #13#10 +
        '  2. 查看日志: ' + LogFile + #13#10 +
        '  3. 将日志发送给开发者排查问题',
        mbInformation, MB_OK);
    end else
      LogMsg('All steps completed successfully!');

  finally
    Page.Hide;
  end;
end;

// ─── 欢迎页自定义说明 ─────────────────────────────────
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpWelcome then
  begin
    WizardForm.WelcomeLabel2.Caption :=
      '欢迎安装 OpenClaw AI 语音助手 v3.2！' + #13#10 + #13#10 +
      '主要功能：' + #13#10 +
      '  - 全双工语音对话 + 情感识别' + #13#10 +
      '  - 声音克隆（3 秒音频即可）' + #13#10 +
      '  - AI 桌面控制 + 截图 + 窗口管理' + #13#10 +
      '  - 微信公众号 / Siri / 飞书 / 钉钉 桥接' + #13#10 +
      '  - 会议助手 + 主动智能' + #13#10 + #13#10 +
      '安装模式：' + #13#10 +
      '  [最小安装] 云端模式，约 50MB，3 分钟搞定' + #13#10 +
      '  [完整安装] 含本地模型，约 1.5GB，高配电脑推荐' + #13#10 + #13#10 +
      '下一步选择安装模式，安装过程会弹出命令行窗口。';
  end;
end;

// ─── 磁盘空间检查 ─────────────────────────────────────
function InitializeSetup(): Boolean;
var
  FreeSpaceMB, TotalSpaceMB: Cardinal;
begin
  Result := True;
  if GetSpaceOnDisk(ExpandConstant('{autopf}'), True, FreeSpaceMB, TotalSpaceMB) then
  begin
    if FreeSpaceMB < 2048 then
    begin
      if MsgBox(
        '磁盘可用空间不足 2GB！' + #13#10 +
        'OpenClaw 需要约 1-2GB 空间安装依赖。' + #13#10 + #13#10 +
        '是否仍要继续安装？',
        mbConfirmation, MB_YESNO
      ) = IDNO then
        Result := False;
    end;
  end;
end;

// ─── 创建目录 + 复制 .env + 运行安装步骤 ──────────────
procedure CreateDirs();
begin
  ForceDirectories(ExpandConstant('{app}\data'));
  ForceDirectories(ExpandConstant('{app}\data\voice_clones'));
  ForceDirectories(ExpandConstant('{app}\data\mcp_servers'));
  ForceDirectories(ExpandConstant('{app}\data\meetings'));
  ForceDirectories(ExpandConstant('{app}\data\screenshots'));
  ForceDirectories(ExpandConstant('{app}\models'));
  ForceDirectories(ExpandConstant('{app}\logs'));
  ForceDirectories(ExpandConstant('{app}\ssl'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvFile, TemplateFile: String;
begin
  if CurStep = ssPostInstall then
  begin
    EnvFile := ExpandConstant('{app}\.env');
    TemplateFile := ExpandConstant('{app}\.env.template');
    if not FileExists(EnvFile) and FileExists(TemplateFile) then
      CopyFile(TemplateFile, EnvFile, False);

    RunInstallSteps();
  end;
end;
