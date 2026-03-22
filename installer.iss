; ╔══════════════════════════════════════════════════════════════╗
; ║   十三香小龙虾 v6.0 — Inno Setup 安装脚本（护城河版）       ║
; ║   最小≈50MB / 无障碍≈60MB / 完整（本地GPU）≈1.5GB          ║
; ╚══════════════════════════════════════════════════════════════╝
;
; 前置步骤（仅首次编译前执行一次）:
;   cd installer && python build_embedded_python.py
;
; 编译安装包前必须先完成 Tauri 构建（否则 ISCC 会报错，避免静默跳过桌面端）:
;   1) 项目根目录: npx tauri build
;      或一键: build_installer.bat（含 tauri build + 复制到 dist + ISCC）
;   2) "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; 生成文件: dist\十三香小龙虾-v5.x.x-Setup.exe（版本见下方 #define AppVersion）

#define AppName       "十三香小龙虾"
#define AppVersion    "6.0.0"
#define AppPublisher  "十三香小龙虾"
#define AppURL        "https://github.com/openclaw/voice"
#define AppExeName    "十三香小龙虾.exe"
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
DefaultDirName={localappdata}\ShisanXiang
DefaultGroupName=十三香小龙虾
AllowNoIcons=yes
LicenseFile=installer\assets\license.txt
; 输出目录和文件名
OutputDir=dist
; 带 BuildID 的文件名，避免被网盘/浏览器同名覆盖、拿错包
OutputBaseFilename=十三香小龙虾-v{#AppVersion}-Setup
; 图标
SetupIconFile=assets\icon.ico
; 压缩（lzma2/ultra 最高压缩率）
Compression=lzma2/ultra64
SolidCompression=yes
CompressionThreads=auto
; 界面风格
WizardStyle=modern
WizardSizePercent=140
WizardImageFile=installer\assets\wizard_image.bmp
WizardSmallImageFile=installer\assets\wizard_small.bmp
; 权限（不要求管理员，避免UAC弹窗）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 版本信息
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=十三香小龙虾 — 全双工 AI 语音助手
VersionInfoProductName={#AppName}
; 关闭运行中的程序
CloseApplications=yes
CloseApplicationsFilter=*OpenClaw*,*shisanxiang*,*launcher*,*十三香小龙虾*
; 安装后重启设置
RestartIfNeededByRun=no
; 最低 Windows 版本：Windows 10
MinVersion=10.0

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english";     MessagesFile: "compiler:Default.isl"

[Types]
Name: "minimal";  Description: "最小安装 — 云端模式，约 50MB，适合日常使用"
Name: "access";   Description: "无障碍控制版 — 含桌面控制，约 80MB，推荐大多数用户"
Name: "full";     Description: "完整安装 — 含本地 GPU 模型，约 1.5GB，可离线使用"
Name: "custom";   Description: "自定义安装 — 手动选择组件"; Flags: iscustom

[Components]
Name: "core";     Description: "核心引擎 — 语音对话 + 情感识别 + 声音克隆（~50MB）";       Types: minimal access full custom; Flags: fixed
Name: "desktop";  Description: "桌面控制 — OCR识别 + 鼠标键盘 + 屏幕捕获（+30MB）";       Types: access full
Name: "localai";  Description: "本地AI引擎 — PyTorch + 语音模型，需GPU（+1.4GB）";         Types: full
Name: "vision";   Description: "高级视觉 — UIAutomation 窗口控制（+10MB）";                Types: full

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式";     GroupDescription: "附加图标:"; Flags: checkedonce
Name: "startmenu";   Description: "创建开始菜单快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce
Name: "autostart";   Description: "开机自动启动";          GroupDescription: "开机行为:"

[Files]
; ── 核心应用文件 ──────────────────────────────────────────────
; Tauri 桌面端：从 Cargo 实际产物安装（包名 shisanxiang）→ 用户可见文件名 十三香小龙虾.exe
; 不再使用 dist\ 下的副本 + skipifsourcedoesntexist，否则未编译 tauri 时会静默不打进 exe。
Source: "src-tauri\target\release\shisanxiang.exe"; DestDir: "{app}"; DestName: "十三香小龙虾.exe"; Flags: ignoreversion skipifsourcedoesntexist
; ── 项目文件 ────────────────────────────────────────────────
Source: "start.bat";             DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "version.txt";           DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt";      DestDir: "{app}"; Flags: ignoreversion
Source: "requirements-full.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.template";         DestDir: "{app}"; DestName: ".env.template"; Flags: ignoreversion
Source: "安装说明.md";            DestDir: "{app}"; Flags: ignoreversion
Source: "OpenClaw使用说明书.md";  DestDir: "{app}"; Flags: ignoreversion
Source: "openclaw_debug.bat";    DestDir: "{app}"; Flags: ignoreversion
Source: "config.ini";            DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

; ── 源代码目录 ────────────────────────────────────────────────
Source: "src\*";               DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "skills\*";            DestDir: "{app}\skills"; Flags: ignoreversion recursesubdirs createallsubdirs
; ── 离线依赖包（pip install 无需联网）──────────────────────
Source: "offline_packages\*";  DestDir: "{app}\offline_packages"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── 图标资源 ──────────────────────────────────────────────────
Source: "assets\icon.ico";      DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\icon.png";      DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\tray_icon.png"; DestDir: "{app}\assets"; Flags: ignoreversion

; ── 安装辅助脚本 ────────────────────────────────────────────
Source: "install_full.bat";    DestDir: "{app}"; Flags: ignoreversion

; ── 内嵌 Python 3.11.9 运行环境（离线可用，排除大型 ML 库）────
Source: "installer\embedded\python\*";  DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "Lib\site-packages\torch\*,Lib\site-packages\torchaudio\*,Lib\site-packages\nvidia\*"

; ── VC++ 运行库（安装后自动删除临时文件）──────────────────
Source: "installer\embedded\vcredist_x64.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall

; ── 创建必要的空目录 ──────────────────────────────────────────
Source: "assets\icon.ico";     DestDir: "{app}\data";   Flags: ignoreversion; AfterInstall: CreateDirs
Source: "assets\icon.ico";     DestDir: "{app}\models"; Flags: ignoreversion; AfterInstall: CreateDirs
Source: "assets\icon.ico";     DestDir: "{app}\logs";   Flags: ignoreversion; AfterInstall: CreateDirs
Source: "assets\icon.ico";     DestDir: "{app}\ssl";    Flags: ignoreversion; AfterInstall: CreateDirs

[Icons]
; 桌面快捷方式（非U盘模式）
; 优先 Tauri exe，不存在则用 start.bat
Name: "{autodesktop}\十三香小龙虾";       Filename: "{app}\start.bat"; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\assets\icon.ico"; IconIndex: 0; \
  Comment: "十三香小龙虾 AI — 52个AI员工一键上岗"; \
  Tasks: desktopicon; Check: IsNotUSBMode

; 开始菜单（非U盘模式）
Name: "{group}\十三香小龙虾";             Filename: "{app}\start.bat"; \
  WorkingDir: "{app}"; \
  IconFilename: "{app}\assets\icon.ico"; IconIndex: 0; \
  Tasks: startmenu; Check: IsNotUSBMode
Name: "{group}\命令行模式（调试）";        Filename: "{app}\openclaw_debug.bat"; \
  WorkingDir: "{app}"; \
  Tasks: startmenu; Check: IsNotUSBMode
Name: "{group}\使用说明";                 Filename: "{app}\OpenClaw使用说明书.md"; \
  Tasks: startmenu; Check: IsNotUSBMode
Name: "{group}\卸载 十三香小龙虾";        Filename: "{uninstallexe}"; \
  Tasks: startmenu; Check: IsNotUSBMode

[Registry]
; 开机自启（非U盘模式）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "十三香小龙虾"; \
  ValueData: """{app}\十三香小龙虾.exe"""; \
  Flags: uninsdeletevalue; Tasks: autostart; Check: IsNotUSBMode

[Run]
; 标准模式完成后弹出"立即启动"（极速/U盘模式在 [Code] 中自动处理）
Filename: "{app}\十三香小龙虾.exe"; \
  Description: "立即启动 十三香小龙虾"; \
  Flags: nowait postinstall skipifsilent; Check: IsStandardMode

[UninstallRun]
; 卸载前终止运行中的程序（Tauri + Python 后端）
Filename: "taskkill"; Parameters: "/F /IM shisanxiang.exe /T"; Flags: runhidden; RunOnceId: "KillTauri"
Filename: "taskkill"; Parameters: "/F /IM 十三香小龙虾.exe /T"; Flags: runhidden; RunOnceId: "KillTauriCN"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\src\__pycache__"
Type: filesandordirs; Name: "{app}\skills\__pycache__"
Type: filesandordirs; Name: "{app}\python\__pycache__"
Type: filesandordirs; Name: "{app}\data\projects"
Type: filesandordirs; Name: "{app}\data\transfers"
Type: filesandordirs; Name: "{app}\certs"
Type: filesandordirs; Name: "{app}\logs"
; 保留核心用户数据
; Type: filesandordirs; Name: "{app}\data"
; Type: filesandordirs; Name: "{app}\.env"

[Code]
var
  LogFile: String;
  QuickMode: Boolean;
  USBMode: Boolean;
  ModePage: TWizardPage;
  USBDrivePage: TInputDirWizardPage;

// ─── Windows API ────────────────────────────────────────
function PostMessage(hWnd: Integer; Msg, wParam, lParam: Integer): Integer;
  external 'PostMessageA@user32.dll stdcall';
function GetDriveTypeW(lpRootPathName: String): UINT;
  external 'GetDriveTypeW@kernel32.dll stdcall';

const
  BM_CLICK = $00F5;
  DRIVE_REMOVABLE = 2;

// ─── Check 函数（供 [Icons]/[Registry]/[Run] 条件判断）──
function IsNotUSBMode(): Boolean;
begin
  Result := not USBMode;
end;

function IsStandardMode(): Boolean;
begin
  Result := (not QuickMode) and (not USBMode);
end;

// ─── 日志 ──────────────────────────────────────────────
procedure LogMsg(Msg: String);
begin
  SaveStringToFile(LogFile,
    '[' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0) + '] ' + Msg + #13#10, True);
end;

// ─── 检测系统已安装的 Python ───────────────────────────
function FindPython(): String;
var
  LocalAppData, PF, PF86, RegPath: String;
  I: Integer;
  Paths: array[0..13] of String;
  ResultCode: Integer;
begin
  Result := '';
  LocalAppData := GetEnv('LOCALAPPDATA');
  PF := ExpandConstant('{commonpf}');
  PF86 := ExpandConstant('{commonpf32}');

  Paths[0]  := LocalAppData + '\Programs\Python\Python313\python.exe';
  Paths[1]  := LocalAppData + '\Programs\Python\Python312\python.exe';
  Paths[2]  := LocalAppData + '\Programs\Python\Python311\python.exe';
  Paths[3]  := LocalAppData + '\Programs\Python\Python310\python.exe';
  Paths[4]  := PF + '\Python313\python.exe';
  Paths[5]  := PF + '\Python312\python.exe';
  Paths[6]  := PF + '\Python311\python.exe';
  Paths[7]  := PF86 + '\Python313\python.exe';
  Paths[8]  := PF86 + '\Python312\python.exe';
  Paths[9]  := PF86 + '\Python311\python.exe';
  Paths[10] := 'C:\Python313\python.exe';
  Paths[11] := 'C:\Python312\python.exe';
  Paths[12] := 'C:\Python311\python.exe';
  Paths[13] := 'C:\Python310\python.exe';

  for I := 0 to 13 do
  begin
    if FileExists(Paths[I]) then
    begin
      Result := Paths[I];
      LogMsg('Found system Python: ' + Result);
      Exit;
    end;
  end;

  if RegQueryStringValue(HKCU, 'SOFTWARE\Python\PythonCore\3.13\InstallPath', '', RegPath) then
    if FileExists(RegPath + 'python.exe') then begin Result := RegPath + 'python.exe'; LogMsg('Found Python via registry: ' + Result); Exit; end;
  if RegQueryStringValue(HKCU, 'SOFTWARE\Python\PythonCore\3.12\InstallPath', '', RegPath) then
    if FileExists(RegPath + 'python.exe') then begin Result := RegPath + 'python.exe'; LogMsg('Found Python via registry: ' + Result); Exit; end;
  if RegQueryStringValue(HKCU, 'SOFTWARE\Python\PythonCore\3.11\InstallPath', '', RegPath) then
    if FileExists(RegPath + 'python.exe') then begin Result := RegPath + 'python.exe'; LogMsg('Found Python via registry: ' + Result); Exit; end;
  if RegQueryStringValue(HKLM, 'SOFTWARE\Python\PythonCore\3.13\InstallPath', '', RegPath) then
    if FileExists(RegPath + 'python.exe') then begin Result := RegPath + 'python.exe'; LogMsg('Found Python via registry: ' + Result); Exit; end;
  if RegQueryStringValue(HKLM, 'SOFTWARE\Python\PythonCore\3.12\InstallPath', '', RegPath) then
    if FileExists(RegPath + 'python.exe') then begin Result := RegPath + 'python.exe'; LogMsg('Found Python via registry: ' + Result); Exit; end;
  if RegQueryStringValue(HKLM, 'SOFTWARE\Python\PythonCore\3.11\InstallPath', '', RegPath) then
    if FileExists(RegPath + 'python.exe') then begin Result := RegPath + 'python.exe'; LogMsg('Found Python via registry: ' + Result); Exit; end;

  if Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
    begin
      Result := 'python';
      LogMsg('Found Python in PATH');
    end;
  end;
end;

// ─── 运行 pip install ─────────────────────────────────
function RunPip(PythonExe, Args: String; Visible: Boolean): Integer;
var
  ShowMode, ResultCode: Integer;
begin
  if Visible then ShowMode := SW_SHOWNORMAL else ShowMode := SW_HIDE;
  LogMsg('pip> ' + PythonExe + ' -m pip ' + Args);
  if Exec(PythonExe, '-m pip ' + Args, ExpandConstant('{app}'), ShowMode, ewWaitUntilTerminated, ResultCode) then
    Result := ResultCode
  else
    Result := -1;
  LogMsg('pip exit code: ' + IntToStr(Result));
end;

// ─── 确保有可用的 Python ──────────────────────────────
function EnsurePython(AppDir: String): String;
begin
  Result := '';
  if FileExists(AppDir + '\python\python.exe') then
  begin
    Result := AppDir + '\python\python.exe';
    LogMsg('Using bundled Python 3.11.9: ' + Result);
    Exit;
  end;
  Result := FindPython();
  if Result <> '' then
  begin
    LogMsg('Using system Python: ' + Result);
    Exit;
  end;
  LogMsg('FATAL: Neither bundled nor system Python found');
end;

// ─── 生成 SSL 证书 ───────────────────────────────────
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
    '        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ShisanXiang Voice Server")])' + #13#10 +
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
    LogMsg('SSL certificate generated')
  else
    LogMsg('WARNING: SSL generation failed (code ' + IntToStr(ResultCode) + ')');
end;

// ─── 检测可移动磁盘（U盘）──────────────────────────────
function DetectFirstUSBDrive(): String;
var
  I: Integer;
  DriveLetter: String;
begin
  Result := '';
  for I := Ord('D') to Ord('Z') do
  begin
    DriveLetter := Chr(I) + ':\';
    if GetDriveTypeW(DriveLetter) = DRIVE_REMOVABLE then
    begin
      Result := DriveLetter;
      Exit;
    end;
  end;
end;

function GetAllUSBDrives(): String;
var
  I: Integer;
  DriveLetter: String;
begin
  Result := '';
  for I := Ord('D') to Ord('Z') do
  begin
    DriveLetter := Chr(I) + ':\';
    if GetDriveTypeW(DriveLetter) = DRIVE_REMOVABLE then
    begin
      if Result = '' then
        Result := DriveLetter
      else
        Result := Result + '  ' + DriveLetter;
    end;
  end;
  if Result = '' then
    Result := '(未检测到U盘)';
end;

// ═══════════════════════════════════════════════════════
//  主安装流程：分步执行，带进度反馈
// ═══════════════════════════════════════════════════════
procedure RunInstallSteps();
var
  Page: TOutputProgressWizardPage;
  PythonExe, AppDir, VcInstaller: String;
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
    ' 十三香小龙虾 v{#AppVersion} Installation Log' + #13#10 +
    ' ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0) + #13#10 +
    ' Mode: ' + #13#10 +
    '================================================' + #13#10, False);

  if QuickMode then LogMsg('Install mode: QUICK')
  else if USBMode then LogMsg('Install mode: USB PORTABLE')
  else LogMsg('Install mode: STANDARD');

  Page := CreateOutputProgressPage(
    '正在配置运行环境',
    '安装程序正在配置所需组件，请耐心等待...' + #13#10 +
    '（详细日志: ' + AppDir + '\logs\install.log）'
  );
  Page.Show;

  try
    // ── 步骤 1: 确保 Python ──
    Page.SetText('正在初始化 Python 运行环境...', '');
    Page.SetProgress(0, 100);
    LogMsg('=== [Step 1] Ensure Python ===');

    PythonExe := EnsurePython(AppDir);
    if PythonExe = '' then
    begin
      LogMsg('FATAL: Python not available');
      if not QuickMode then
        MsgBox(
          'Python 运行环境初始化失败！' + #13#10 + #13#10 +
          '请重新运行安装程序或检查磁盘空间。' + #13#10 +
          '日志: ' + LogFile, mbError, MB_OK);
      Exit;
    end;
    LogMsg('Using Python: ' + PythonExe);
    Page.SetProgress(10, 100);

    // ── 步骤 2: 安装 VC++（U盘模式跳过，已内嵌 DLL）──
    if not USBMode then
    begin
      Page.SetText('正在安装 Visual C++ 运行库...', '');
      Page.SetProgress(12, 100);
      LogMsg('=== [Step 2] Install VC++ Runtime ===');
      VcInstaller := ExpandConstant('{tmp}\vcredist_x64.exe');
      if FileExists(VcInstaller) then
      begin
        Exec(VcInstaller, '/install /quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        LogMsg('VC++ install exit code: ' + IntToStr(ResultCode));
      end else
        LogMsg('WARNING: VC++ installer not found');
    end else
      LogMsg('=== [Step 2] Skip VC++ (USB mode, DLLs bundled) ===');

    Page.SetProgress(15, 100);

    // ── 步骤 3: 配置 pip 镜像 ──
    Page.SetText('配置 pip 国内加速镜像...', '');
    Page.SetProgress(16, 100);
    LogMsg('=== [Step 3] Configure pip mirror ===');
    RunPip(PythonExe, 'config set global.index-url https://mirrors.aliyun.com/pypi/simple/', False);
    RunPip(PythonExe, 'config set global.trusted-host mirrors.aliyun.com', False);
    RunPip(PythonExe, 'install --upgrade pip -q', False);
    Page.SetProgress(20, 100);

    // ── 步骤 4: 安装核心依赖 ──
    Page.SetText('正在安装核心依赖包（约 1-3 分钟）...', '');
    Page.SetProgress(20, 100);
    LogMsg('=== [Step 4] Install core dependencies ===');

    // 优先离线安装（offline_packages 目录已打包在安装包中）
    ResultCode := RunPip(PythonExe,
      'install --no-cache-dir --no-index --find-links="' + AppDir + '\offline_packages" -r "' + AppDir + '\requirements.txt"', True);
    if ResultCode <> 0 then
    begin
      Page.SetText('离线安装未完成，尝试联网安装...', '');
      LogMsg('Offline install failed, trying online...');
      ResultCode := RunPip(PythonExe,
        'install --no-cache-dir --timeout 180 -r "' + AppDir + '\requirements.txt"', True);
    end;
    if ResultCode <> 0 then
    begin
      Errors := Errors + '- 核心依赖安装异常' + #13#10;
      LogMsg('WARNING: Core deps failed: ' + IntToStr(ResultCode));
    end;
    Page.SetProgress(50, 100);

    // ── 步骤 4.5: 桌面控制依赖（极速模式自动包含）──
    if WizardIsComponentSelected('desktop') or QuickMode then
    begin
      Page.SetText('正在安装桌面控制组件...', '');
      LogMsg('=== [Step 4.5] Install desktop control deps ===');
      ResultCode := RunPip(PythonExe,
        'install --no-cache-dir --timeout 120 pyautogui mss rapidocr-onnxruntime pyperclip', True);
      if ResultCode <> 0 then
      begin
        Errors := Errors + '- 桌面控制组件安装异常' + #13#10;
        LogMsg('WARNING: Desktop deps failed');
      end;
    end;

    // ── 步骤 5: 本地 AI（仅完整版，极速/U盘跳过）──
    if WizardIsComponentSelected('localai') and (not QuickMode) and (not USBMode) then
    begin
      Page.SetText('正在安装本地 AI 引擎（约 10-15 分钟）...', '');
      Page.SetProgress(50, 100);
      LogMsg('=== [Step 5] Install local AI ===');
      ResultCode := RunPip(PythonExe,
        'install --no-cache-dir --timeout 300 torch --index-url https://download.pytorch.org/whl/cpu', True);
      if ResultCode <> 0 then
        ResultCode := RunPip(PythonExe, 'install --no-cache-dir --timeout 300 torch', True);
      if ResultCode <> 0 then
        Errors := Errors + '- PyTorch 安装失败' + #13#10;

      Page.SetProgress(70, 100);
      ResultCode := RunPip(PythonExe,
        'install --no-cache-dir --timeout 120 faster-whisper funasr silero-vad torchaudio transformers', True);
      if ResultCode <> 0 then
        Errors := Errors + '- 本地语音模型安装异常' + #13#10;
    end else
    begin
      Page.SetText('安装语音检测组件...', '');
      LogMsg('=== [Step 5] Install silero-vad (minimal) ===');
      RunPip(PythonExe, 'install --timeout 120 silero-vad', True);
    end;
    Page.SetProgress(80, 100);

    // ── 步骤 6: 视觉组件（仅完整版）──
    if WizardIsComponentSelected('vision') and (not QuickMode) and (not USBMode) then
    begin
      Page.SetText('正在安装视觉控制组件...', '');
      LogMsg('=== [Step 6] Install vision components ===');
      ResultCode := RunPip(PythonExe,
        'install --no-cache-dir --timeout 120 rapidocr-onnxruntime mss pyautogui uiautomation', True);
      if ResultCode <> 0 then
        RunPip(PythonExe,
          'install --no-cache-dir --timeout 180 rapidocr-onnxruntime mss pyautogui uiautomation', True);
    end;
    Page.SetProgress(90, 100);

    // ── 步骤 7: SSL 证书 ──
    Page.SetText('正在生成 SSL 证书...', '');
    Page.SetProgress(92, 100);
    LogMsg('=== [Step 7] Generate SSL certificate ===');
    GenerateSSL(PythonExe, AppDir);
    Page.SetProgress(100, 100);

    // ── 安装结果 ──
    LogMsg('Installation finished: ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0));
    if Errors <> '' then
    begin
      LogMsg('WARNINGS: ' + Errors);
      if not QuickMode then
        MsgBox(
          '安装已完成，但以下步骤有异常：' + #13#10 + #13#10 +
          Errors + #13#10 +
          '可重新运行安装程序或手动运行 install_full.bat 重试。' + #13#10 +
          '日志: ' + LogFile, mbInformation, MB_OK);
    end else
      LogMsg('All steps completed successfully!');

  finally
    Page.Hide;
  end;
end;

// ═══════════════════════════════════════════════════════
//  三种安装模式的按钮回调
// ═══════════════════════════════════════════════════════
procedure QuickInstallClick(Sender: TObject);
begin
  QuickMode := True;
  USBMode := False;
  WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\ShisanXiang');
  PostMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0);
end;

procedure StandardInstallClick(Sender: TObject);
begin
  QuickMode := False;
  USBMode := False;
  PostMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0);
end;

procedure USBInstallClick(Sender: TObject);
var
  FirstUSB: String;
begin
  QuickMode := False;
  USBMode := True;
  FirstUSB := DetectFirstUSBDrive();
  if FirstUSB <> '' then
    USBDrivePage.Values[0] := FirstUSB + 'ShisanXiang'
  else
    USBDrivePage.Values[0] := 'D:\ShisanXiang';
  PostMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0);
end;

// ═══════════════════════════════════════════════════════
//  InitializeWizard — 三模式选择页 + U盘驱动器页 + 全局美化
// ═══════════════════════════════════════════════════════
procedure InitializeWizard();
var
  QuickBtn, StdBtn, USBBtn: TNewButton;
  QuickDesc, StdDesc, USBDesc, LicenseNote: TNewStaticText;
  Sep1, Sep2: TBevel;
  BtnLeft, BtnWidth, BtnHeight, Y: Integer;
begin
  QuickMode := False;
  USBMode := False;

  // ── 全局美化 ──
  WizardForm.Color := $00FAFAFA;

  // ── 模式选择页（替代 wpWelcome）──
  ModePage := CreateCustomPage(
    wpWelcome,
    '十三香小龙虾 v{#AppVersion}',
    '全双工语音对话 · AI桌面控制 · 声音克隆 · 会议助手');

  BtnLeft := ScaleX(16);
  BtnWidth := ModePage.SurfaceWidth - ScaleX(32);
  BtnHeight := ScaleY(44);
  Y := ScaleY(12);

  // ─── 极速安装（推荐）───
  QuickBtn := TNewButton.Create(ModePage);
  QuickBtn.Parent := ModePage.Surface;
  QuickBtn.Caption := '  极速安装（推荐）';
  QuickBtn.Left := BtnLeft;
  QuickBtn.Top := Y;
  QuickBtn.Width := BtnWidth;
  QuickBtn.Height := BtnHeight;
  QuickBtn.Font.Size := 11;
  QuickBtn.Font.Style := [fsBold];
  QuickBtn.Cursor := crHand;
  QuickBtn.OnClick := @QuickInstallClick;

  Y := Y + BtnHeight + ScaleY(3);
  QuickDesc := TNewStaticText.Create(ModePage);
  QuickDesc.Parent := ModePage.Surface;
  QuickDesc.Caption := '一键完成 — 安装到默认位置，含桌面控制，自动打开设置页';
  QuickDesc.Left := BtnLeft + ScaleX(4);
  QuickDesc.Top := Y;
  QuickDesc.Font.Color := $00888888;
  QuickDesc.Font.Size := 8;

  // ── 分隔线 ──
  Y := Y + ScaleY(20);
  Sep1 := TBevel.Create(ModePage);
  Sep1.Parent := ModePage.Surface;
  Sep1.Left := BtnLeft;
  Sep1.Top := Y;
  Sep1.Width := BtnWidth;
  Sep1.Height := 1;
  Sep1.Shape := bsTopLine;

  // ─── 自定义安装 ───
  Y := Y + ScaleY(10);
  StdBtn := TNewButton.Create(ModePage);
  StdBtn.Parent := ModePage.Surface;
  StdBtn.Caption := '  自定义安装';
  StdBtn.Left := BtnLeft;
  StdBtn.Top := Y;
  StdBtn.Width := BtnWidth;
  StdBtn.Height := BtnHeight;
  StdBtn.Font.Size := 11;
  StdBtn.Cursor := crHand;
  StdBtn.OnClick := @StandardInstallClick;

  Y := Y + BtnHeight + ScaleY(3);
  StdDesc := TNewStaticText.Create(ModePage);
  StdDesc.Parent := ModePage.Surface;
  StdDesc.Caption := '选择安装目录、组件和高级选项';
  StdDesc.Left := BtnLeft + ScaleX(4);
  StdDesc.Top := Y;
  StdDesc.Font.Color := $00888888;
  StdDesc.Font.Size := 8;

  // ── 分隔线 ──
  Y := Y + ScaleY(20);
  Sep2 := TBevel.Create(ModePage);
  Sep2.Parent := ModePage.Surface;
  Sep2.Left := BtnLeft;
  Sep2.Top := Y;
  Sep2.Width := BtnWidth;
  Sep2.Height := 1;
  Sep2.Shape := bsTopLine;

  // ─── U盘便携安装 ───
  Y := Y + ScaleY(10);
  USBBtn := TNewButton.Create(ModePage);
  USBBtn.Parent := ModePage.Surface;
  USBBtn.Caption := '  安装到U盘（便携版）';
  USBBtn.Left := BtnLeft;
  USBBtn.Top := Y;
  USBBtn.Width := BtnWidth;
  USBBtn.Height := BtnHeight;
  USBBtn.Font.Size := 11;
  USBBtn.Cursor := crHand;
  USBBtn.OnClick := @USBInstallClick;

  Y := Y + BtnHeight + ScaleY(3);
  USBDesc := TNewStaticText.Create(ModePage);
  USBDesc.Parent := ModePage.Surface;
  USBDesc.Caption := '随插随用，不写入电脑 — 插到任何 Windows 10+ 电脑即可使用';
  USBDesc.Left := BtnLeft + ScaleX(4);
  USBDesc.Top := Y;
  USBDesc.Font.Color := $00888888;
  USBDesc.Font.Size := 8;

  // 许可协议小字（紧贴底部）
  LicenseNote := TNewStaticText.Create(ModePage);
  LicenseNote.Parent := ModePage.Surface;
  LicenseNote.Caption := '点击安装即表示您同意《用户许可协议》';
  LicenseNote.Left := BtnLeft;
  LicenseNote.Top := ModePage.SurfaceHeight - ScaleY(14);
  LicenseNote.Font.Color := $00BBBBBB;
  LicenseNote.Font.Size := 7;

  // ── U盘驱动器选择页 ──
  USBDrivePage := CreateInputDirPage(
    wpLicense,
    '选择U盘安装位置',
    '十三香小龙虾将安装到U盘，随插随用',
    '请选择U盘或移动硬盘上的安装目录。' + #13#10 + #13#10 +
    '检测到的可移动磁盘: ' + GetAllUSBDrives() + #13#10 + #13#10 +
    '提示: 最少需要 200MB 可用空间。安装完成后，' + #13#10 +
    'U盘根目录会生成"启动十三香小龙虾.bat"，双击即可运行。',
    False, '');
  USBDrivePage.Add('安装到:');
  USBDrivePage.Values[0] := 'D:\ShisanXiang';
end;

// ─── 页面跳过逻辑 ──────────────────────────────────────
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;

  // 始终跳过默认欢迎页（被我们的 ModePage 替代）
  if PageID = wpWelcome then
  begin
    Result := True;
    Exit;
  end;

  // 模式选择页始终显示
  if PageID = ModePage.ID then
  begin
    Result := False;
    Exit;
  end;

  if QuickMode then
  begin
    // 极速模式：跳过所有剩余页面
    Result := True;
  end
  else if USBMode then
  begin
    // U盘模式：只显示U盘选择页
    if PageID = USBDrivePage.ID then
      Result := False
    else
      Result := True;
  end
  else
  begin
    // 标准模式：跳过U盘选择页，显示其他所有默认页面
    if PageID = USBDrivePage.ID then
      Result := True;
  end;
end;

// ─── 页面切换时设置目录 ────────────────────────────────
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if USBMode and (CurPageID = USBDrivePage.ID) then
  begin
    WizardForm.DirEdit.Text := USBDrivePage.Values[0];
  end;
end;

// ─── 页面变化回调（美化每一步）─────────────────────────
procedure CurPageChanged(CurPageID: Integer);
var
  I: Integer;
begin
  // 极速/U盘模式：到达完成页时自动点击完成
  if (CurPageID = wpFinished) and (QuickMode or USBMode) then
  begin
    PostMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0);
    Exit;
  end;

  // 模式选择页：隐藏 Next 按钮文字（用户通过三个模式按钮选择）
  if CurPageID = ModePage.ID then
    WizardForm.NextButton.Caption := ''
  else
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);

  // ── 各页面美化 ──

  // 许可协议页
  if CurPageID = wpLicense then
  begin
    WizardForm.PageDescriptionLabel.Caption :=
      '请阅读以下许可协议，滚动到底部后点击"我接受"继续。';
  end;

  // 安装目录选择页
  if CurPageID = wpSelectDir then
  begin
    WizardForm.PageNameLabel.Caption := '选择安装位置';
    WizardForm.PageDescriptionLabel.Caption :=
      '十三香小龙虾将安装到以下目录。如果不确定，保持默认即可。';
  end;

  // 组件选择页
  if CurPageID = wpSelectComponents then
  begin
    WizardForm.PageNameLabel.Caption := '选择安装组件';
    WizardForm.PageDescriptionLabel.Caption :=
      '选择要安装的功能模块。括号内为预估占用空间。';
  end;

  // 任务选择页 — 默认勾选所有
  if CurPageID = wpSelectTasks then
  begin
    WizardForm.PageNameLabel.Caption := '附加选项';
    WizardForm.PageDescriptionLabel.Caption :=
      '选择安装后的快捷方式和启动行为。';
    for I := 0 to WizardForm.TasksList.Items.Count - 1 do
      WizardForm.TasksList.Checked[I] := True;
  end;

  // 准备安装页
  if CurPageID = wpReady then
  begin
    WizardForm.PageNameLabel.Caption := '准备安装';
    WizardForm.PageDescriptionLabel.Caption :=
      '确认以下设置无误后，点击"安装"开始。';
  end;

  // 完成页
  if CurPageID = wpFinished then
  begin
    WizardForm.FinishedHeadingLabel.Caption :=
      '安装完成！';
    WizardForm.FinishedLabel.Caption :=
      '十三香小龙虾 v{#AppVersion} 已成功安装到您的电脑。' + #13#10 + #13#10 +
      '勾选下方选项可立即启动程序。首次运行会打开浏览器' + #13#10 +
      '引导您完成 AI 平台配置。' + #13#10 + #13#10 +
      '感谢您选择十三香小龙虾！';
  end;
end;

// ─── 磁盘空间检查 ──────────────────────────────────────
function InitializeSetup(): Boolean;
var
  FreeSpaceMB, TotalSpaceMB: Cardinal;
begin
  Result := True;
  if GetSpaceOnDisk(ExpandConstant('{localappdata}'), True, FreeSpaceMB, TotalSpaceMB) then
  begin
    if FreeSpaceMB < 500 then
    begin
      if MsgBox(
        '磁盘可用空间不足 500MB！' + #13#10 +
        '十三香小龙虾需要约 300MB 基础空间。' + #13#10 + #13#10 +
        '是否仍要继续安装？',
        mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

// ─── 创建目录 ──────────────────────────────────────────
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

// ─── U盘启动器生成 ────────────────────────────────────
procedure CreateUSBLauncher(AppDir: String);
var
  DrivePath, FolderName, BatPath, BatContent: String;
begin
  DrivePath := ExtractFileDrive(AppDir);
  FolderName := ExtractFileName(AppDir);
  BatPath := DrivePath + '\启动十三香小龙虾.bat';
  BatContent :=
    '@echo off' + #13#10 +
    'chcp 65001 >nul' + #13#10 +
    'title 十三香小龙虾 — 便携版' + #13#10 +
    'echo.' + #13#10 +
    'echo  正在从U盘启动十三香小龙虾，请稍候...' + #13#10 +
    'echo.' + #13#10 +
    'cd /d "%~dp0' + FolderName + '"' + #13#10 +
    'if not exist "python\python.exe" (' + #13#10 +
    '    echo  [错误] 找不到内嵌 Python，请重新安装便携版。' + #13#10 +
    '    pause' + #13#10 +
    '    exit /b 1' + #13#10 +
    ')' + #13#10 +
    'start "" "十三香小龙虾.exe"' + #13#10 +
    'echo  十三香小龙虾已启动！可以关闭此窗口。' + #13#10 +
    'timeout /t 3 /nobreak >nul' + #13#10;

  SaveStringToFile(BatPath, BatContent, False);
  LogMsg('USB launcher created: ' + BatPath);

  // 写入 portable 标记
  SaveStringToFile(AppDir + '\portable.flag', 'portable=true' + #13#10, False);
  LogMsg('Portable flag created');
end;

// ─── 安装后处理 ────────────────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvFile, TemplateFile, AppDir: String;
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir := ExpandConstant('{app}');
    EnvFile := AppDir + '\.env';
    TemplateFile := AppDir + '\.env.template';
    if not FileExists(EnvFile) and FileExists(TemplateFile) then
      FileCopy(TemplateFile, EnvFile, False);

    RunInstallSteps();

    // U盘模式：生成便携启动器
    if USBMode then
      CreateUSBLauncher(AppDir);

    // 极速/U盘模式：安装后自动启动
    if QuickMode or USBMode then
    begin
      Exec(AppDir + '\十三香小龙虾.exe', '', AppDir,
        SW_SHOWNORMAL, ewNoWait, ResultCode);
      LogMsg('Auto-launched Tauri application');
    end;
  end;
end;
