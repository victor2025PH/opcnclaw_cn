# 🦞 十三香小龙虾 AI 工作队

**说一句话，52 个 AI 帮你干活 — 写方案 / 操控电脑 / 微信自动化 / 语音交互**

**开箱即用，无需注册任何 AI 平台。**

![Version](https://img.shields.io/badge/version-6.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Agents](https://img.shields.io/badge/AI_Agents-52人-orange.svg)
![Skills](https://img.shields.io/badge/技能-126个-green.svg)

<p align="center">
  <a href="https://github.com/victor2025PH/opcnclaw_cn/releases/latest"><strong>📥 下载安装包</strong></a> ·
  <a href="https://13x.lol"><strong>🌐 官网</strong></a> ·
  <a href="https://github.com/victor2025PH/opcnclaw_cn/issues"><strong>🐛 反馈</strong></a>
</p>

---

## 它能做什么？

### 👥 52 人 AI 团队 — 一句话，团队帮你干活

说 **"帮我写一个营销方案"**，CEO 自动拆解任务 → 10 个 AI 并行工作 → 3 分钟产出完整报告 + 可下载的项目文件。

- 📣 营销方案（10人营销战队）
- 💻 技术方案（10人研发团队）
- 🛍️ 电商运营（15人电商团队）
- 📝 内容创作（8人内容工厂）
- 💼 商业计划（7人咨询团队）
- 🏢 全员出动（52人全部参与）

### 🖥️ AI 操控电脑 — 不只是聊天，真的干活

说 **"帮我打开 Excel"**，AI 截屏看桌面 → 找到目标 → 自动点击打开。

- 截屏识别 + 鼠标键盘操控
- 打开软件、切换窗口、输入文字
- OCR 屏幕内容理解

### 💬 微信 ClawBot — 微信里直接用 AI

通过腾讯官方 iLink 协议接入微信，在微信聊天中直接对话 AI 团队。

- 官方协议，稳定可靠
- 微信中发 "帮我写方案" → 52 人团队执行 → 结果推送回微信
- 支持桌面自动化双通道

### 🧠 AI 越用越懂你 — 7 层数据积累

| 层级 | 功能 |
|------|------|
| 用户画像 | AI 自动学习你的公司、产品、行业、写作风格 |
| Agent 记忆 | 每个 AI 记住做过什么、收到什么反馈 |
| 项目知识库 | 新任务自动引用历史项目经验 |
| Agent 进化 | 越用越专业（星级系统 + 行业专家化）|
| 反馈学习 | 你说 "太长了"，下次自动精简 |
| 质量守卫 | 检测空洞回复，自动补救 |
| 智能路由 | 不同任务自动选最优 AI 模型 |

### 🤖 智能 AI 调配 — 13+ 平台自动切换

| 任务 | 自动选择 |
|------|----------|
| ⚡ 执行操作 / 推理 / 代码 | DeepSeek R1（最强推理）|
| 💬 日常对话 | 智谱 GLM-4-Flash（免费）|
| 👁️ 图片理解 | 智谱 GLM-4V（视觉专属）|
| ✍️ 文案创作 | DeepSeek V3 / 通义千问 |

支持：智谱 · DeepSeek · 通义千问 · 百度文心 · Kimi · OpenAI · Gemini · Groq · Ollama 等 13+ 平台。

---

## 快速开始

### 方式一：安装包（推荐，开箱即用）

1. 下载 [十三香小龙虾-v6.0.0-Setup.exe](https://github.com/victor2025PH/opcnclaw_cn/releases/latest) (348MB)
2. 双击安装
3. 桌面快捷方式启动 → **直接能用**（预置智谱 + DeepSeek Key）

### 方式二：源码运行

```bash
git clone https://github.com/victor2025PH/opcnclaw_cn.git
cd opcnclaw_cn
pip install -r requirements.txt
python -m src.server.main
```

浏览器打开 `http://localhost:8766/app`

---

## 技术架构

```
┌──────────────────────────────────────────────────┐
│  前端 (app.html)                                  │
│  ├── 聊天界面 + DAG 团队可视化                      │
│  ├── 护城河仪表盘 + 成就系统                        │
│  ├── Agent 面板（进化星级 + 项目时间线）             │
│  └── 设置（AI 配置 + 角色商店 + 微信 Bot）          │
├──────────────────────────────────────────────────┤
│  52 Agent 团队引擎 (agent_team.py)                │
│  ├── CEO 拆解 → DAG 分层并行执行                    │
│  ├── 共享成果板 + CEO 中间审核                      │
│  ├── 项目工作空间（文件输出 + ZIP 下载）             │
│  └── Agent 进化 + 反馈学习                         │
├──────────────────────────────────────────────────┤
│  护城河系统                                        │
│  ├── 用户画像 (user_profile_ai.py)                │
│  ├── 智能路由 (smart_router.py) — 按任务选模型      │
│  ├── 质量守卫 (quality_guard.py)                   │
│  ├── 记忆压缩 (memory_compressor.py)              │
│  └── 护城河分数 (moat_score.py)                    │
├──────────────────────────────────────────────────┤
│  FastAPI 后端                                      │
│  ├── 13+ AI 平台路由器（智能切换 + 容错）            │
│  ├── 27 个工具（团队/桌面/微信/基础）                │
│  ├── 微信双通道（iLink 官方 + UIAutomation）        │
│  ├── 126 个内置技能 + 角色商店（13 角色）           │
│  └── 定时任务（每日早报 + 自动备份）                 │
├──────────────────────────────────────────────────┤
│  数据层                                            │
│  ├── SQLite (main.db + wechat.db)                 │
│  ├── Agent 记忆 + 用户偏好                         │
│  ├── 项目文件 (data/projects/)                     │
│  └── 数据导出/导入（JSON + ZIP）                    │
└──────────────────────────────────────────────────┘
```

## 更多功能

| 功能 | 描述 |
|------|------|
| 🎤 **语音交互** | STT/TTS/VAD 全链路，唤醒词、连续对话、声音克隆 |
| 🛒 **角色商店** | 13 个社区角色（直播主播/小红书写手/广告优化师...）一键安装 |
| 📊 **AI 学习进度** | 0-100 分量化数据积累，5 级成就系统 |
| 💾 **数据备份** | 一键导出/导入 AI 学习数据（JSON + ZIP） |
| 🔗 **分享报告** | 团队完成后生成 HTML 报告，一键分享链接 |
| ⏰ **定时任务** | 每日早报 + 每周分析 + 自动保存 |
| 🔌 **MCP 协议** | Claude Desktop / Cursor 可直接对接 |

## 安全

- PIN 码保护敏感 API
- 写保护中间件（非 LAN 请求拦截）
- 滑动窗口速率限制
- Ed25519 设备认证

## 开发

```bash
# 运行测试
python -m pytest tests/ -q

# 构建安装包
build_installer.bat
```

## 许可证

MIT License

---

<p align="center">
  <strong>🦞 十三香小龙虾 AI 工作队 — 越用越懂你</strong><br>
  <a href="https://13x.lol">官网</a> ·
  <a href="https://github.com/victor2025PH/opcnclaw_cn/releases/latest">下载</a>
</p>
