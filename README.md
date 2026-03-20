# 十三香小龙虾 AI

**自托管全双工 AI 语音助手 — 语音交互 / 桌面控制 / 微信自动化 / 人机协作**

![Version](https://img.shields.io/badge/version-4.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Tests](https://img.shields.io/badge/tests-185%20passed-brightgreen.svg)

## 核心功能

| 功能 | 描述 |
|------|------|
| 🎤 **语音交互** | STT/TTS/VAD 全链路，支持唤醒词、连续对话、声音克隆 |
| 🖥️ **桌面控制** | AI 看着屏幕帮你操作电脑（OCR + 鼠标键盘自动化） |
| 💬 **微信 4.x** | 自动回复、朋友圈管理、多会话扫描、AI 智能评论 |
| 🤝 **人机协作** | AI 知道你在做什么，不会打扰你，用户活跃时自动暂停 |
| 🧩 **63+ 技能** | 天气、计算器、翻译、日程、食谱、编程辅助等 |
| 🔌 **MCP 协议** | 标准 MCP Server，Claude Desktop / Cursor 可直接对接 |
| 🌐 **多平台** | Windows 桌面（Tauri 15MB）+ 手机 H5 + 浏览器 |

## 快速开始

### 方式一：安装包（推荐）

下载 `十三香小龙虾-v4.0-Setup.exe` (150MB)，双击安装即可使用。

### 方式二：源码运行

```bash
git clone https://github.com/victor2025PH/opcnclaw_cn.git
cd opcnclaw_cn
pip install -r requirements.txt
python -m src.server.main
```

浏览器打开 `http://localhost:8766/app`

### 方式三：Tauri 桌面客户端

```bash
npm install
npx tauri dev
```

## 技术架构

```
┌─────────────────────────────────────────┐
│  Tauri 桌面壳层 (15MB)                   │
│  ├── WebView → localhost:8766/app       │
│  ├── 系统托盘 + 启动画面                  │
│  └── Python 后端生命周期管理              │
├─────────────────────────────────────────┤
│  FastAPI 后端 (Python)                   │
│  ├── 13+ AI 平台路由 (智谱/OpenAI/...)   │
│  ├── 微信 4.x 自动化引擎                 │
│  ├── 桌面控制 (OCR + PyAutoGUI)          │
│  ├── 人机协作调度 (CoworkBus)            │
│  ├── MCP Server (5 工具)                 │
│  └── 63 个内置技能                       │
├─────────────────────────────────────────┤
│  数据层                                  │
│  ├── SQLite (main.db + wechat.db)       │
│  ├── FTS5 双索引 (unicode61 + jieba)    │
│  └── 自动迁移 + 定期备份                 │
└─────────────────────────────────────────┘
```

## API 文档

启动后访问 `http://localhost:8766/docs` (Swagger UI)

## 微信 4.x 自动化

```
无障碍钩子激活 UI 树 → UIA 读取消息 → AI 生成回复 → UIA 发送
```

- 自动回复私聊和群聊(@me)
- 朋友圈浏览 + AI 分析 + 自动点赞/评论
- 30 天内容日历 + AI 文案生成
- 多会话自动扫描 + 未读消息处理

## MCP Server

Claude Desktop / Cursor 可直接调用：

```json
{
  "mcpServers": {
    "shisanxiang": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/openclaw-voice"
    }
  }
}
```

可用工具：`wechat_send` / `wechat_read` / `wechat_status` / `cowork_status` / `action_journal`

## 安全

- PIN 码保护敏感 API（`.env` 设置 `OPENCLAW_ADMIN_PIN`）
- 写保护中间件（非 LAN 请求拦截）
- 滑动窗口速率限制
- Ed25519 设备认证

## 开发

```bash
# 运行测试
python -m pytest tests/ -q

# 构建安装包
build_installer.bat

# Tauri 构建
npx tauri build
```

## 许可证

MIT License
