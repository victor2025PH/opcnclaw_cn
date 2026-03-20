"""
Internationalization (i18n) for 十三香小龙虾 settings UI.

Usage:
    from src.gui.i18n import t, set_locale, get_locale

    label.configure(text=t("ai_platform"))  # "AI 平台" or "AI Platform"
"""

from typing import Dict

_current_locale = "zh"

_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # ── 导航标签 ──
    "tab_ai":       {"zh": "🤖  AI 平台",    "en": "🤖  AI Platform"},
    "tab_voice":    {"zh": "🎙️  语音设置",   "en": "🎙️  Voice"},
    "tab_bridge":   {"zh": "💬  平台接入",    "en": "💬  Bridges"},
    "tab_skills":   {"zh": "📦  技能管理",    "en": "📦  Skills"},
    "tab_mcp":      {"zh": "🔌  MCP 市场",   "en": "🔌  MCP Market"},
    "tab_model":    {"zh": "📥  模型管理",   "en": "📥  Models"},
    "tab_system":   {"zh": "⚙️  系统设置",   "en": "⚙️  System"},

    # ── 通用按钮 ──
    "save":         {"zh": "保存设置",      "en": "Save Settings"},
    "cancel":       {"zh": "取消",         "en": "Cancel"},
    "close":        {"zh": "关闭",         "en": "Close"},
    "refresh":      {"zh": "🔄 刷新",      "en": "🔄 Refresh"},
    "test":         {"zh": "测试",         "en": "Test"},
    "install":      {"zh": "安装",         "en": "Install"},
    "uninstall":    {"zh": "卸载",         "en": "Uninstall"},
    "copy":         {"zh": "复制",         "en": "Copy"},
    "export":       {"zh": "导出",         "en": "Export"},
    "import_":      {"zh": "导入",         "en": "Import"},

    # ── 系统页面 ──
    "version_update": {"zh": "版本与更新",    "en": "Version & Updates"},
    "check_update":   {"zh": "🔍  检查更新",  "en": "🔍  Check Updates"},
    "download_update":{"zh": "⬇️  下载更新",  "en": "⬇️  Download Update"},
    "startup_opts":   {"zh": "启动选项",      "en": "Startup Options"},
    "autostart":      {"zh": "开机自启动",    "en": "Launch at startup"},
    "minimize_tray":  {"zh": "启动时最小化到托盘", "en": "Minimize to tray on start"},
    "network_ports":  {"zh": "网络端口",      "en": "Network Ports"},
    "appearance":     {"zh": "外观",         "en": "Appearance"},
    "dark_mode":      {"zh": "深色模式",      "en": "Dark Mode"},
    "light_mode":     {"zh": "浅色模式",      "en": "Light Mode"},
    "skills_pack":    {"zh": "技能包",       "en": "Skill Packs"},
    "hotkeys":        {"zh": "全局快捷键",    "en": "Global Hotkeys"},
    "config_backup":  {"zh": "配置备份",      "en": "Config Backup"},
    "export_config":  {"zh": "📦  导出配置",  "en": "📦  Export Config"},
    "import_config":  {"zh": "📥  导入配置",  "en": "📥  Import Config"},
    "service_mgmt":   {"zh": "服务管理",      "en": "Service Management"},
    "restart_service":{"zh": "🔄  重启服务",  "en": "🔄  Restart Service"},
    "stop_service":   {"zh": "⏹  停止服务",   "en": "⏹  Stop Service"},
    "running_log":    {"zh": "运行日志",      "en": "Runtime Log"},
    "open_log_dir":   {"zh": "📂 打开日志目录", "en": "📂 Open Log Folder"},
    "diagnostics":    {"zh": "诊断信息",      "en": "Diagnostics"},
    "copy_diag":      {"zh": "📋  复制诊断报告", "en": "📋  Copy Report"},
    "export_diag":    {"zh": "📤  导出到文件",    "en": "📤  Export to File"},
    "feedback":       {"zh": "🐛  反馈问题",      "en": "🐛  Report Bug"},

    # ── AI 平台页面 ──
    "ai_provider":    {"zh": "AI 服务商",     "en": "AI Provider"},
    "api_key":        {"zh": "API Key",       "en": "API Key"},
    "model":          {"zh": "模型",          "en": "Model"},
    "test_connection":{"zh": "🔗  测试连接",  "en": "🔗  Test Connection"},

    # ── 语音设置 ──
    "stt_engine":     {"zh": "语音识别引擎",   "en": "STT Engine"},
    "tts_engine":     {"zh": "语音合成引擎",   "en": "TTS Engine"},
    "voice_clone":    {"zh": "声音克隆",       "en": "Voice Clone"},
    "voice_sample":   {"zh": "音频样本",       "en": "Voice Sample"},

    # ── 桥接 ──
    "wechat_mp":      {"zh": "微信公众号",     "en": "WeChat Official"},
    "siri_shortcuts":  {"zh": "Siri Shortcuts", "en": "Siri Shortcuts"},
    "dingtalk":       {"zh": "钉钉机器人",     "en": "DingTalk Bot"},
    "feishu":         {"zh": "飞书机器人",     "en": "Feishu Bot"},
    "wecom":          {"zh": "企业微信",       "en": "WeCom"},

    # ── 模型管理 ──
    "model_mgmt":     {"zh": "模型管理",       "en": "Model Management"},
    "gpu_status":     {"zh": "GPU 状态",       "en": "GPU Status"},
    "disk_space":     {"zh": "磁盘空间",       "en": "Disk Space"},
    "online":         {"zh": "🌐 在线",        "en": "🌐 Online"},
    "offline":        {"zh": "📴 离线",        "en": "📴 Offline"},
    "installed":      {"zh": "已安装",         "en": "Installed"},
    "not_installed":  {"zh": "未安装",         "en": "Not Installed"},

    # ── Toast 消息 ──
    "save_ok":        {"zh": "设置已保存",      "en": "Settings saved"},
    "save_fail":      {"zh": "保存失败",       "en": "Save failed"},
    "test_ok":        {"zh": "连接成功",       "en": "Connection OK"},
    "test_fail":      {"zh": "连接失败",       "en": "Connection failed"},
    "copied":         {"zh": "已复制到剪贴板",  "en": "Copied to clipboard"},

    # ── 语言 ──
    "language":       {"zh": "界面语言",       "en": "UI Language"},
    "lang_zh":        {"zh": "中文",          "en": "Chinese"},
    "lang_en":        {"zh": "English",       "en": "English"},
}


def t(key: str) -> str:
    entry = _TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(_current_locale, entry.get("zh", key))


def set_locale(locale: str):
    global _current_locale
    if locale in ("zh", "en"):
        _current_locale = locale


def get_locale() -> str:
    return _current_locale


def available_locales() -> list:
    return [("zh", "中文"), ("en", "English")]
