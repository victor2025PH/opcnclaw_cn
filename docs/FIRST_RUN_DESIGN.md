# 首次使用体验重构方案

---

## 一、问题分析

### 当前的灾难流程
```
安装 → 打开 → 看到聊天界面 → 点"写营销方案"
→ "所有AI平台暂时不可用" → 用户懵了 → 卸载
```

### 用户不知道的事
1. 需要配置 AI 的 API Key
2. 去哪里获取 API Key
3. 哪个平台免费
4. 电脑版和手机版有什么区别

---

## 二、正确的首次使用流程

```
安装 → 打开 → 检测是否配置了 AI

没配置 →
┌──────────────────────────────────────┐
│  🦞 欢迎！还差一步就能使用           │
│                                      │
│  十三香需要连接 AI 引擎才能工作      │
│  推荐使用 智谱 GLM-4（永久免费）     │
│                                      │
│  ┌──────────────────────────────┐    │
│  │ 📋 3 步配置（1 分钟）        │    │
│  │                              │    │
│  │ ① 点击打开智谱注册页 →       │    │
│  │ ② 创建 API Key 并复制        │    │
│  │ ③ 粘贴到下方输入框           │    │
│  │                              │    │
│  │ [API Key: _______________]   │    │
│  │                              │    │
│  │ [✅ 验证并开始使用]           │    │
│  └──────────────────────────────┘    │
│                                      │
│  💡 智谱 GLM-4-Flash 完全免费        │
│     无限次数，永久有效               │
│                                      │
│  [跳过（功能受限）]                   │
└──────────────────────────────────────┘

已配置 → 正常进入聊天界面
```

---

## 三、设备识别 + 差异化体验

### 识别逻辑

```python
# 后端识别
def detect_client(request):
    ua = request.headers.get("user-agent", "")

    # 设备类型
    is_mobile = any(k in ua.lower() for k in ["mobile", "android", "iphone", "ipad"])
    is_tauri = "tauri" in ua.lower() or request.headers.get("tauri-custom")
    is_desktop_browser = not is_mobile and not is_tauri

    # 连接方式
    is_local = request.client.host in ("127.0.0.1", "::1", "localhost")
    is_lan = request.client.host.startswith(("192.168.", "10.", "172."))

    return {
        "device": "mobile" if is_mobile else "desktop",
        "client": "tauri" if is_tauri else "browser",
        "network": "local" if is_local else ("lan" if is_lan else "remote"),
    }
```

### 不同设备的差异化

| 功能 | 电脑 Tauri | 电脑浏览器 | 手机浏览器 |
|------|-----------|-----------|-----------|
| 桌宠 | 独立置顶窗口 | 页内浮动 | 隐藏 |
| 远程桌面 | 不需要 | 不需要 | 显示入口 |
| 文件上传 | 拖拽到桌宠 | 拖拽到聊天区 | 点击按钮选择 |
| 语音输入 | 直接可用 | 需要 HTTPS | 需要 HTTPS |
| 键盘快捷键 | 全部可用 | 部分可用 | 不适用 |
| 摄像头 | 直接可用 | 需要 HTTPS | 需要 HTTPS |
| 底部工具栏 | 完整显示 | 完整显示 | 精简（3个） |

---

## 四、AI 未配置时的智能引导

### 每个入口都要检查

```
用户点任何需要 AI 的按钮（写方案/竞品/聊天...）
  → 前端先检查 AI 状态
  → 未配置 → 弹出配置引导（不是报错）
  → 已配置 → 正常执行
```

### 配置引导的 3 种触发方式

1. **首次打开**：自动检测，未配置则全屏引导
2. **点击功能按钮**：弹出小提示"需要先配置AI"
3. **设置页面**：完整的多平台配置表单

---

## 五、实现要点

### 后端
```
GET /api/ai/status → {configured: true/false, platform: "zhipu", model: "glm-4-flash"}
POST /api/ai/quick-setup → {api_key: "xxx"} → 自动配置智谱
GET /api/client/info → {device, client, network}
```

### 前端
```
app.html 加载时：
  1. fetch /api/ai/status
  2. if (!configured) → 显示配置引导
  3. if (configured) → 显示正常界面

每个需要 AI 的按钮：
  onclick → checkAI() → 未配置则弹引导
```

---

*核心原则：用户不应该看到"平台不可用"——要么引导配置，要么降级提示。*
