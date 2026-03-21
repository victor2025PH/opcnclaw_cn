# 十三香小龙虾 — 快速上手指南

## 5 分钟开始使用

### 第 1 步：安装

**方式 A：安装包（推荐）**
```
双击 十三香小龙虾-v4.4-Setup.exe → 下一步 → 完成
```

**方式 B：源码运行**
```bash
git clone https://github.com/victor2025PH/opcnclaw_cn.git
cd opcnclaw_cn
pip install -r requirements.txt
python -m src.server.main
```

### 第 2 步：配置 AI

1. 浏览器打开 `http://localhost:8766/setup`
2. 选择 **智谱 GLM-4-Flash**（永久免费）
3. 去 [智谱 AI](https://open.bigmodel.cn/login) 注册，复制 API Key
4. 粘贴到设置页面 → 保存

### 第 3 步：开始对话

- **电脑浏览器**：打开 `http://localhost:8766/app`
- **手机**：扫描 `http://localhost:8766/qr` 页面的二维码
- 点击麦克风按钮 🎤 或直接打字

---

## 核心功能

### 💬 AI 对话
- 支持文字和语音（点击麦克风或说唤醒词"你好小龙"）
- 支持 13+ AI 平台自动切换（智谱/DeepSeek/百度/OpenAI...）
- 63 个内置技能（天气/计算/翻译/食谱/日程...）

### 📱 微信自动回复
1. 确保微信 4.x 已登录并在前台运行
2. 打开 `http://localhost:8766/app` → 设置 → 微信
3. 开启自动回复 → 添加白名单联系人
4. AI 会自动回复（群聊需要 @你）

### 🖥️ AI 操控电脑
对 AI 说这些话即可：
- "帮我截个图看看屏幕" → 截屏 + OCR
- "点击确认按钮" → 找到按钮并点击
- "打开微信" → 启动微信
- "复制这段文字" → Ctrl+C

### 🏠 智能家居（需要 HomeAssistant）
1. 设置 → 智能家居 → 填入 HomeAssistant URL 和 Token
2. 对 AI 说"关灯"、"开空调"、"调高温度"

### 👤 多用户
1. 点击右上角头像 → 添加新用户
2. 录入 3 句话采集声纹
3. 系统自动识别说话人，切换对应记忆和偏好

### 🔌 MCP Server（给其他 AI 工具用）
在 Claude Desktop 或 Cursor 中配置：
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

---

## API 文档

启动后访问：
- Swagger UI: `http://localhost:8766/docs`
- ReDoc: `http://localhost:8766/redoc`

### 常用 API

| API | 说明 |
|-----|------|
| `POST /api/chat` | AI 对话（SSE 流式） |
| `GET /api/metrics` | 系统指标 |
| `GET /api/users` | 用户列表 |
| `POST /api/intent/signal` | 推送多模态信号 |
| `POST /api/a2a/task` | Agent 间任务委派 |
| `GET /api/iot/devices` | 智能设备列表 |
| `GET /api/system/network-status` | 网络状态 |

---

## 常见问题

**Q: AI 不回复？**
→ 检查 API Key 是否正确：设置 → AI 配置

**Q: 微信自动回复不工作？**
→ 确保微信 4.x 窗口在前台（不能最小化到托盘）

**Q: 手机打不开摄像头？**
→ 需要 HTTPS。访问 `https://你的IP:8765/app`，信任证书后重试

**Q: 内存占用太高？**
→ 关闭不需要的功能（微信监控、OCR 预加载等）

---

## 技术架构

```
FastAPI 后端 (Python)
├── 11 个 API 路由模块
├── 21 个 AI 工具（Function Calling）
├── 4 通道意图融合引擎
├── A2A Agent 间通信协议
├── 微信 4.x 自动化（UIA + OCR）
├── 人机协作调度（CoworkBus）
├── 2 个 SQLite 数据库（FTS5 全文搜索）
└── 8 种语言 TTS 自动切换
```
