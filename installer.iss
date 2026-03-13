; ╔══════════════════════════════════════════════════════════════╗
; ║   OpenClaw AI 语音助手 v2.0 — Inno Setup 安装脚本           ║
; ║   直接打包源代码，安装时在线下载Python依赖                    ║
; ╚══════════════════════════════════════════════════════════════╝
;
; 编译命令（CMD）:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; 生成文件: dist\installer\OpenClaw-v2.0-Setup.exe

#define AppName       "OpenClaw AI 语音助手"
#define AppVersion    "2.0.0"
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
OutputBaseFilename=OpenClaw-v2.0-Setup
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

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式";     GroupDescription: "附加图标:"; Flags: checkedonce
Name: "startmenu";   Description: "创建开始菜单快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce
Name: "autostart";   Description: "开机自动启动";          GroupDescription: "开机行为:"

[Files]
; ── 核心应用文件 ──────────────────────────────────────────────
Source: "launcher.py";           DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt";      DestDir: "{app}"; Flags: ignoreversion
Source: ".env.template";         DestDir: "{app}"; DestName: ".env.template"; Flags: ignoreversion
Source: "安装说明.md";            DestDir: "{app}"; Flags: ignoreversion
Source: "start.bat";             DestDir: "{app}"; Flags: ignoreversion
Source: "OpenClaw.vbs";          DestDir: "{app}"; Flags: ignoreversion
Source: "openclaw_debug.bat";    DestDir: "{app}"; Flags: ignoreversion
Source: "_create_launcher.vbs";  DestDir: "{app}"; Flags: ignoreversion

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
Name: "{group}\使用说明";                 Filename: "{app}\安装说明.md"; \
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
; Step 1: 安装 Python 依赖（检测Python/VC++/pip配置/依赖安装/SSL证书）
Filename: "{cmd}"; \
  Parameters: "/C ""{app}\install_full.bat"""; \
  WorkingDir: "{app}"; \
  StatusMsg: "正在安装 Python 依赖（约5-20分钟，请耐心等待）…"; \
  Flags: runhidden waituntilterminated

; Step 2: 安装完成后弹出"立即启动"选项
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
  InstallPage: TOutputProgressWizardPage;

// 自定义欢迎页说明
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpWelcome then
  begin
    WizardForm.WelcomeLabel2.Caption :=
      '欢迎安装 OpenClaw AI 语音助手 v2.0！' + #13#10 + #13#10 +
      '✨ 主要功能：' + #13#10 +
      '  🎙️ 全双工语音对话（边说边听）' + #13#10 +
      '  🤖 支持 13 个 AI 平台自动轮换' + #13#10 +
      '  🧩 63 个实用技能（天气/菜谱/财务等）' + #13#10 +
      '  📱 手机扫码使用，支持添加到主屏幕' + #13#10 +
      '  🎛️ 系统托盘管理，开机自启' + #13#10 + #13#10 +
      '📦 安装内容：' + #13#10 +
      '  • 应用源代码（约 5MB）' + #13#10 +
      '  • 自动检测/安装 Python 3.11' + #13#10 +
      '  • 自动安装所有依赖（约 500MB-1GB）' + #13#10 + #13#10 +
      '⏱️ 首次安装约需 15-30 分钟（含依赖下载）';
  end;
end;

// 检查磁盘空间（GetSpaceOnDisk: path, usemb, freespace, totalspace）
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

// 安装后创建必要的空目录
procedure CreateDirs();
begin
  ForceDirectories(ExpandConstant('{app}\data'));
  ForceDirectories(ExpandConstant('{app}\models'));
  ForceDirectories(ExpandConstant('{app}\logs'));
  ForceDirectories(ExpandConstant('{app}\ssl'));
end;

// 安装前创建 .env 文件（从模板）
procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvFile, TemplateFile: String;
begin
  if CurStep = ssPostInstall then
  begin
    EnvFile := ExpandConstant('{app}\.env');
    TemplateFile := ExpandConstant('{app}\.env.template');
    if not FileExists(EnvFile) and FileExists(TemplateFile) then
      FileCopy(TemplateFile, EnvFile, False);
  end;
end;
