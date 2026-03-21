# 桌宠机器人重构方案 — 从 EVE 机器人提取设计

> 基于 D:\web3-migration\aizkw20251219\components\AISprite.tsx 分析

---

## 一、EVE 机器人特性分析

### 已有能力（需要移植的）

| 特性 | EVE 实现 | 十三香移植方案 |
|------|---------|-------------|
| **自由飞行** | framer-motion spring 物理 | CSS transform + requestAnimationFrame |
| **跟随点击飞行** | 点击位置→计算偏移→弹簧动画飞过去 | mousedown 记录目标 → 缓动动画移动 |
| **滚动物理** | 页面滚动→机器人上浮/下坠 | 监听 wheel 事件 → 位移变化 |
| **碰撞检测** | querySelectorAll data-robot-avoid | 边界检测 + 窗口边缘回弹 |
| **7 种表情** | 眼睛 scaleY/borderRadius 变化 | SVG 眼睛形状切换 |
| **8 种行为** | flying/falling/idle/wave/dance/scan/news/spin | CSS animation class 切换 |
| **手臂动画** | 不同模式不同手臂角度 | SVG transform rotate |
| **颜色循环** | setInterval 切换眼睛颜色 | CSS animation hue-rotate |
| **悬停反馈** | whileHover scale(1.1) | CSS :hover transform |
| **全息投影** | 头顶弹出信息面板 | 已有（桌宠输入面板） |
| **拖拽** | 无（固定右下角） | **需要新增** |

### 不需要的（React 专属）

- framer-motion 库依赖
- useSpring/useVelocity（用 JS 手动计算）
- AnimatePresence（用 CSS transition）

---

## 二、纯 HTML/CSS/JS 实现方案

### 核心：桌宠作为自由移动的浮动窗口

```
Tauri 模式：桌宠是独立透明窗口（decorations:false, transparent:true）
  → 窗口本身就可以拖动（data-tauri-drag-region）
  → 不需要边框

浏览器模式：桌宠是 position:fixed 的 div
  → mousedown+mousemove 实现拖拽
  → 桌面上自由移动
```

### 机器人 SVG 设计（替换小龙虾）

```
EVE 风格机器人：
  ┌──────┐
  │ ◉  ◉ │  ← 数字眼（发光扫描线）
  │  ▬   │  ← 嘴巴（LED 点阵）
  └──┬───┘  ← 头部（圆角矩形，白色渐变）
     │      ← 颈部（发光连接线）
  ┌──┴───┐
  │      │  ← 身体（白色胶囊形）
  │  ⚡  │  ← 胸口能量核心（发光）
  └──────┘
 /        \  ← 手臂（可挥手/跳舞/飞行）
```

### 行为模式

```
idle_base:  轻微上下浮动（2.5s 周期）+ 随机眨眼
idle_wave:  鼠标悬停时挥手 + 开心表情
idle_dance: 跳动 + 手臂交替摆动
idle_scan:  眼睛扫描动画 + 身体微转
idle_news:  头顶弹出信息面板
flying:     向点击位置飞行 + 身体倾斜
falling:    受惊表情 + 手臂上举
```

### 交互方式

```
1. 拖拽移动：按住身体任意位置拖动
2. 点击飞行：点击桌面空白处 → 机器人飞过去
3. 悬停互动：鼠标悬停 → 挥手+开心
4. 双击对话：弹出输入面板
5. 右键菜单：快速任务/设置/退出
6. 窗口碰撞：靠近窗口边缘 → 回弹
7. 空闲行为：6秒随机一个动作（跳舞/扫描/新闻/旋转）
```

---

## 三、每个 Agent 独立对话栏

### 设计

```
团队执行时，聊天区右侧弹出 Agent 面板：

┌──────────────────────────────────┬──────────────┐
│  主聊天区                        │  Agent 面板   │
│                                  │              │
│  AI: 团队已就位...               │  📡 CMO       │
│                                  │  ✅ 策略完成   │
│                                  │  [查看] [对话] │
│                                  │              │
│                                  │  ✍️ 文案       │
│                                  │  🔄 写作中...  │
│                                  │  [查看] [对话] │
│                                  │              │
│                                  │  🎨 设计       │
│                                  │  ⏳ 等待中     │
│                                  │  [对话]       │
│                                  │              │
│  [输入框...]                     │  共 10 人     │
└──────────────────────────────────┴──────────────┘

点击 [对话] → 打开与该 Agent 的独立会话窗口
```

### API 需求

```
POST /api/agents/team/{team_id}/agent/{agent_id}/chat
请求: {"message": "标题改一下"}
响应: {"reply": "好的老板，修改版..."}
```

---

## 四、实施步骤

| 步骤 | 任务 | 工期 |
|------|------|------|
| 1 | EVE 机器人 SVG（纯 CSS） | 2小时 |
| 2 | 自由拖拽 + 飞行物理 | 2小时 |
| 3 | 7 种表情 + 8 种行为 | 1小时 |
| 4 | Agent 独立对话 API | 1小时 |
| 5 | Agent 面板 UI | 2小时 |
| 6 | 去边框（白色框去除） | 30分钟 |

---

*总工期：1 天。从小龙虾换成 EVE 机器人，加入飞行物理和 Agent 独立对话。*
