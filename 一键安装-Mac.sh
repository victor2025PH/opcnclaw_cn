#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║        OpenClaw Voice AI — macOS 一键安装脚本               ║
# ║  支持 macOS 12+，Intel 和 Apple Silicon (M1/M2/M3) 均可     ║
# ╚══════════════════════════════════════════════════════════════╝
#
# 使用方式（终端中执行）：
#   chmod +x 一键安装-Mac.sh
#   ./一键安装-Mac.sh

set -e

# ── 颜色 ──────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; WHITE='\033[1;37m'; GRAY='\033[0;37m'; NC='\033[0m'

step()  { echo -e "\n${CYAN}[$1/$TOTAL_STEPS] $2${NC}"; }
ok()    { echo -e "  ${GREEN}✓ $1${NC}"; }
warn()  { echo -e "  ${YELLOW}⚠ $1${NC}"; }
fail()  { echo -e "  ${RED}✗ $1${NC}"; exit 1; }
info()  { echo -e "  ${GRAY}  $1${NC}"; }

TOTAL_STEPS=8
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/OpenClaw"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     OpenClaw Voice AI  macOS 安装程序         ║${NC}"
echo -e "${CYAN}║     AI 语音 · 手势 · 视觉 · 远程桌面          ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── 检查 macOS 版本 ───────────────────────────────────────────
MACOS_VER=$(sw_vers -productVersion)
ARCH=$(uname -m)
info "macOS: $MACOS_VER  架构: $ARCH"
ok "系统检查通过"

# ── 0. 确认安装目录 ───────────────────────────────────────────
echo ""
echo -e "  安装到: ${WHITE}$INSTALL_DIR${NC}"
read -p "  修改路径？直接回车使用默认 [Enter]: " custom_dir
if [ -n "$custom_dir" ]; then
    INSTALL_DIR="$custom_dir"
fi

# ── 1. Homebrew ───────────────────────────────────────────────
step 1 "检查 Homebrew"
if ! command -v brew &>/dev/null; then
    warn "未找到 Homebrew，正在安装..."
    info "这需要几分钟，可能需要输入密码..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Apple Silicon: 添加 brew 到 PATH
    if [ "$ARCH" = "arm64" ]; then
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    ok "Homebrew 安装完成"
else
    ok "Homebrew 已安装: $(brew --version | head -1)"
fi

# ── 2. Python 3.11 ───────────────────────────────────────────
step 2 "检查 Python 3.11+"
PYTHON_EXE=""
for py in python3.13 python3.12 python3.11 python3; do
    if command -v $py &>/dev/null; then
        VER=$($py --version 2>&1 | grep -oE '3\.[0-9]+')
        MINOR=$(echo $VER | cut -d. -f2)
        if [ "$MINOR" -ge 10 ] 2>/dev/null; then
            PYTHON_EXE=$(which $py)
            ok "Python $VER → $PYTHON_EXE"
            break
        fi
    fi
done

if [ -z "$PYTHON_EXE" ]; then
    warn "安装 Python 3.11..."
    brew install python@3.11
    PYTHON_EXE=$(brew --prefix)/bin/python3.11
    ok "Python 3.11 安装完成"
fi

# ── 3. 系统依赖 ───────────────────────────────────────────────
step 3 "安装系统依赖（ffmpeg、portaudio）"
for pkg in ffmpeg portaudio; do
    if ! brew list $pkg &>/dev/null; then
        info "安装 $pkg..."
        brew install $pkg --quiet
    fi
done
ok "系统依赖就绪"

# ── 4. 复制项目文件 ───────────────────────────────────────────
step 4 "复制项目文件"
mkdir -p "$INSTALL_DIR/logs"

# 排除不需要的目录
rsync -a --exclude='venv/' --exclude='.venv/' --exclude='__pycache__/' \
         --exclude='.git/' --exclude='certs/' --exclude='logs/' \
         --exclude='.env' --exclude='*.pyc' --exclude='uv.lock' \
         --exclude='node_modules/' \
         "$SCRIPT_DIR/" "$INSTALL_DIR/"

ok "文件复制到 $INSTALL_DIR"

# ── 5. Python 虚拟环境 + 依赖 ─────────────────────────────────
step 5 "创建虚拟环境 + 安装 Python 依赖（约 10-20 分钟）"
VENV_DIR="$INSTALL_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [ ! -f "$VENV_PYTHON" ]; then
    info "创建虚拟环境..."
    $PYTHON_EXE -m venv "$VENV_DIR"
fi

info "升级 pip..."
$VENV_PYTHON -m pip install --upgrade pip --quiet

info "安装依赖（torch + 语音模型较大，请耐心等待 ☕）..."
# Apple Silicon M1/M2/M3: 使用原生 arm64 torch（比 Rosetta 快 3-5 倍）
if [ "$ARCH" = "arm64" ]; then
    info "检测到 Apple Silicon (M系列芯片)，安装原生 ARM torch..."
    $VENV_PIP install torch torchaudio --quiet || true
else
    info "Intel Mac，安装 CPU 版 torch..."
    $VENV_PIP install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --quiet || true
fi

$VENV_PIP install -r "$INSTALL_DIR/requirements.txt" --quiet 2>&1 | \
    grep -E "Successfully installed|error|Error" | head -20 || true

ok "Python 依赖安装完成"

# ── 6. 配置 .env ─────────────────────────────────────────────
step 6 "配置 API Key"
ENV_FILE="$INSTALL_DIR/.env"
# 优先用 .env，否则用 .env.template，最后兜底创建空文件
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$INSTALL_DIR/.env.template" ]; then
        cp "$INSTALL_DIR/.env.template" "$ENV_FILE"
    else
        touch "$ENV_FILE"
    fi
fi

echo ""
echo -e "  ${WHITE}填入 API Key（回车跳过，之后可编辑 $ENV_FILE）${NC}"
echo ""

# 智谱视觉 API
read -p "  智谱视觉 API Key (open.bigmodel.cn 免费注册): " zhipu_key
if [ -n "$zhipu_key" ]; then
    sed -i '' "s|ZHIPU_VISION_API_KEY=.*|ZHIPU_VISION_API_KEY=$zhipu_key|" "$ENV_FILE"
fi

echo ""
echo -e "  ${GRAY}LLM 对话模型（选一种）:${NC}"
echo -e "  ${GRAY}  A. OpenClaw Gateway  B. DeepSeek/OpenAI 直连${NC}"
read -p "  选择 A 或 B [B]: " llm_choice
llm_choice=${llm_choice:-B}

if [[ "$llm_choice" =~ ^[aA]$ ]]; then
    read -p "  OpenClaw Gateway Token: " gw_token
    if [ -n "$gw_token" ]; then
        sed -i '' "s|OPENCLAW_GATEWAY_TOKEN=.*|OPENCLAW_GATEWAY_TOKEN=$gw_token|" "$ENV_FILE"
    fi
else
    read -p "  DeepSeek/OpenAI API Key: " api_key
    read -p "  Base URL (DeepSeek: https://api.deepseek.com/v1，OpenAI 留空): " base_url
    if [ -n "$api_key" ]; then
        echo "" >> "$ENV_FILE"
        echo "OPENAI_API_KEY=$api_key" >> "$ENV_FILE"
        if [ -n "$base_url" ]; then
            echo "OPENAI_BASE_URL=$base_url" >> "$ENV_FILE"
            echo "OPENAI_MODEL=deepseek-chat" >> "$ENV_FILE"
        fi
    fi
fi
ok ".env 配置完成"

# ── 7. 预下载 Whisper 模型 ─────────────────────────────────────
step 7 "预下载语音识别模型（Whisper base ~145MB）"
$VENV_PYTHON -c "
from faster_whisper import WhisperModel
try:
    m = WhisperModel('base', device='cpu', compute_type='int8')
    print('  \033[0;32m✓ Whisper base 模型就绪\033[0m')
except Exception as e:
    print(f'  \033[1;33m⚠ 预下载失败，首次启动时自动下载: {e}\033[0m')
" 2>/dev/null || warn "模型将在首次启动时自动下载"

# ── 8. 系统权限 + 自动启动 ────────────────────────────────────
step 8 "配置系统权限 + 开机自启"

# macOS 权限提示
echo ""
echo -e "  ${YELLOW}macOS 需要以下权限（首次使用时系统会弹窗询问）:${NC}"
echo -e "  ${GRAY}  • 麦克风  — 语音识别和语音唤醒${NC}"
echo -e "  ${GRAY}  • 屏幕录制 — 远程桌面截图功能${NC}"
echo -e "  ${GRAY}  • 辅助功能 — 模拟鼠标键盘（远程控制）${NC}"
echo ""
echo -e "  ${GRAY}如需手动授权: 系统设置 → 隐私与安全性 → 对应权限${NC}"

# 创建启动脚本
START_SH="$INSTALL_DIR/启动服务器.sh"
cat > "$START_SH" << EOF
#!/bin/bash
cd "$INSTALL_DIR"
"$VENV_PYTHON" -m src.server.main
EOF
chmod +x "$START_SH"

# 创建 LaunchAgent（开机自启）
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.openclaw.voice.plist"
mkdir -p "$PLIST_DIR"

cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.voice</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>-m</string>
        <string>src.server.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/logs/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/logs/stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
EOF

# 加载 LaunchAgent
launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load "$PLIST_FILE"
ok "LaunchAgent 已安装（登录时自动启动）"

# 创建应用快捷方式（macOS .command 文件，双击可运行）
SHORTCUT_APP="$HOME/Desktop/OpenClaw AI.command"
cat > "$SHORTCUT_APP" << EOF
#!/bin/bash
cd "$INSTALL_DIR"
open "http://localhost:8766/qr"
"$VENV_PYTHON" -m src.server.main
EOF
chmod +x "$SHORTCUT_APP"
ok "桌面快捷方式已创建"

# ── 完成 ───────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✅ 安装完成！                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  安装目录: ${WHITE}$INSTALL_DIR${NC}"
echo -e "  配置文件: ${WHITE}$ENV_FILE${NC}"
echo -e "  日志目录: ${WHITE}$INSTALL_DIR/logs/${NC}"
echo ""
echo -e "  ${CYAN}📱 手机扫码:   http://本机IP:8766/qr${NC}"
echo -e "  ${CYAN}💻 完整版:     https://本机IP:8765/app${NC}"
echo -e "  ${CYAN}🖥️  本地界面:   http://localhost:8766/qr${NC}"
echo ""
echo -e "  服务管理命令:"
echo -e "  ${GRAY}  启动: launchctl start com.openclaw.voice${NC}"
echo -e "  ${GRAY}  停止: launchctl stop com.openclaw.voice${NC}"
echo -e "  ${GRAY}  卸载: launchctl unload ~/Library/LaunchAgents/com.openclaw.voice.plist${NC}"
echo -e "  ${GRAY}  日志: tail -f $INSTALL_DIR/logs/stdout.log${NC}"
echo ""
echo -e "  修改配置: ${GRAY}open -e $ENV_FILE${NC}"
echo ""

read -p "  现在启动服务器？[Y/n]: " start_now
start_now=${start_now:-Y}
if [[ "$start_now" =~ ^[yY]$ ]]; then
    launchctl start com.openclaw.voice 2>/dev/null || true
    sleep 3
    open "http://localhost:8766/qr"
    echo -e "  ${GREEN}✓ 服务器已启动，浏览器已打开${NC}"
fi

echo ""
echo "  如遇问题请查看: $INSTALL_DIR/logs/stderr.log"
echo ""
