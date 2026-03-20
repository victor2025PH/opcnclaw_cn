# 十三香小龙虾 v4.0 — 战略开发方案

> **起始版本：** v3.3.0
> **目标版本：** v4.0
> **日期：** 2026-03-17
> **战略定位：** 多模态人机协同桌面控制平台 — 人用身体语言和AI一起控制电脑

---

## 一、战略方向

### 核心判断

1. AI独立操作电脑的成功率只有24%（Gartner 2026数据），纯AI Agent路线走不通
2. "Agent + Human"模式比纯Agent成功率提高48%（AgentBay研究）
3. 中国巨头（阿里/阶跃/MiniMax）全部在做"文本→AI操作"，没人做多模态身体语言控制
4. Cephable靠"表情/手势控制电脑"拿了$940万融资，证明市场存在
5. 手势/语音/眼动可及性技术市场$300亿（2025），2033年达$1000亿

### 不做什么

- 不和巨头正面竞争"AI独立操作电脑"
- 不做专用硬件（眼动追踪设备）
- 不等全部做完才上线

### 双赛道并行

```
赛道A（近期，3个月上线）：无障碍桌面控制工具
  → 核心价值：让任何人都能用身体语言控制电脑
  → 不强依赖AI的OCR/LLM，纯本地实时处理
  → 对标Cephable，但更强（加上AI对话能力）
  → 用户：残障人士、RSI患者、特教、效率极客
  → 收费：$15-30/月 或 企业授权

赛道B（中期，6个月上线）：人AI协同桌面工作台
  → 核心价值：人和AI共驾，成功率比纯AI翻倍
  → 建立在赛道A的多模态输入层之上
  → 对标：无直接竞品（蓝海）
  → 用户：知识工作者、内容创作者
  → 收费：开源免费 + Pro增值
```

---

## 二、当前代码资产盘点

> 详细的代码行号、类名、方法索引见 DEV_ROADMAP.md 第二章

### 已完成的能力

| 能力 | 完成度 | 关键文件 |
|------|--------|---------|
| 手势识别（7种标准手势） | 95% | `src/client/app.html` L5328 |
| 桌面手势控制（光标/点击/拖拽/滑动） | 90% | `src/client/app.html` L5735 |
| 手势连招（5种组合） | 90% | `src/client/app.html` L5367 |
| 捏合空中截图 | 100% | `src/client/app.html` L5445 |
| 手指音量控制 | 100% | `src/client/app.html` L5494 |
| 语音识别+AI对话 | 95% | `src/server/stt.py`, `src/server/backend.py` |
| AI桌面控制（OCR→LLM→执行） | 85% | `src/server/routers/desktop.py` L160 |
| 桌面技能包（微信/截图/窗口管理） | 80% | `src/server/desktop_skills.py` |
| 情感检测→AI语气适应 | 80% | `src/server/emotion.py` L89 |
| MCP工具协议客户端 | 70% | `src/mcp/client.py` L44 |
| 面部表情检测 | **30%** | `src/client/app.html` L6246（仅展示，不触发动作） |
| 眼神追踪 | **0%** | 未实现 |
| 多模态意图融合 | **0%** | 不存在 |
| 人AI协同调度 | **0%** | 不存在 |

### 需要补齐的核心短板

```
赛道A需要：
  [缺] 表情→动作映射（点头确认/摇头取消/皱眉求助...）
  [缺] 粗略眼神追踪（注视方向→关注区域）
  [缺] 自定义映射配置UI（用户绑定手势→任意操作）
  [弱] 无AI依赖的纯本地手势控制模式

赛道B需要：
  [缺] 意图融合引擎（手势+语音+表情→统一意图）
  [缺] 人AI协同调度（区域锁定/冲突避免/进度同步）
  [缺] AI操作回滚系统
  [缺] 后台任务执行器
```

---

## 三、赛道A开发计划 — 无障碍桌面控制工具

### 产品名：十三香 AccessControl（暂定）

### 目标用户画像

| 用户群 | 痛点 | 我们的解法 |
|--------|------|-----------|
| 肢体残障人士 | 无法使用鼠标键盘 | 表情+头部动作+语音控制电脑 |
| RSI/腱鞘炎患者 | 长期打字导致手腕疼痛 | 手势+语音替代键盘鼠标 |
| 特殊教育机构 | 学生无法用传统方式操作 | 简化的手势/表情控制界面 |
| 效率极客 | 想要更快的操作方式 | 手势快捷键+语音命令 |
| 手术室/实验室 | 双手被占用无法碰电脑 | 纯表情+语音控制 |

### A阶段1：表情动作系统（2周）

**目标：** 用面部表情控制电脑，无需双手。

#### A1.1 扩展表情检测（客户端）

**修改文件：** `src/client/app.html` (L6246-6257 附近)

当前只检测4种表情且仅展示。需要扩展为完整的表情→动作系统：

```javascript
// ── 表情动作配置 ──
const EXPRESSION_COMMANDS = {
  // 嘴部
  smile_hold:    { detect: bs => (get(bs,'mouthSmileLeft') + get(bs,'mouthSmileRight'))/2 > 0.5,
                   holdMs: 2000, action: 'confirm', label: '😊 微笑确认' },
  mouth_open:    { detect: bs => get(bs,'jawOpen') > 0.6,
                   holdMs: 800,  action: 'start_voice', label: '🗣️ 张嘴说话' },
  kiss:          { detect: bs => get(bs,'mouthPucker') > 0.6,
                   holdMs: 1500, action: 'screenshot', label: '😘 嘟嘴截图' },
  // 眉毛
  brow_up:       { detect: bs => get(bs,'browInnerUp') > 0.5,
                   holdMs: 1000, action: 'scroll_up', label: '🤨 挑眉上翻' },
  brow_down:     { detect: bs => (get(bs,'browDownLeft') + get(bs,'browDownRight'))/2 > 0.4,
                   holdMs: 1000, action: 'scroll_down', label: '😤 皱眉下翻' },
  // 眼睛
  wink_left:     { detect: bs => get(bs,'eyeBlinkLeft') > 0.6 && get(bs,'eyeBlinkRight') < 0.3,
                   holdMs: 500,  action: 'click', label: '😉 左眨=点击' },
  wink_right:    { detect: bs => get(bs,'eyeBlinkRight') > 0.6 && get(bs,'eyeBlinkLeft') < 0.3,
                   holdMs: 500,  action: 'right_click', label: '😉 右眨=右键' },
  both_blink:    { detect: bs => get(bs,'eyeBlinkLeft') > 0.7 && get(bs,'eyeBlinkRight') > 0.7,
                   holdMs: 1200, action: 'enter', label: '😑 双闭=回车' },
  // 头部（通过noseTip landmark位移检测）
  nod:           { detect: 'landmark_motion', landmark: 1, axis: 'y', threshold: 0.03,
                   pattern: 'down_up', timeMs: 800, action: 'confirm', label: '✅ 点头确认' },
  shake:         { detect: 'landmark_motion', landmark: 1, axis: 'x', threshold: 0.03,
                   pattern: 'left_right', timeMs: 800, action: 'cancel', label: '❌ 摇头取消' },
  tilt_left:     { detect: 'landmark_tilt', landmarks: [234, 454], threshold: 0.05,
                   holdMs: 1000, action: 'undo', label: '↩️ 左歪=撤销' },
  tilt_right:    { detect: 'landmark_tilt', landmarks: [234, 454], threshold: -0.05,
                   holdMs: 1000, action: 'redo', label: '↪️ 右歪=重做' },
};
```

**实现要点：**

1. **Blendshape持续检测框架**：每种表情都有`holdMs`持续时间要求，避免误触发。需要一个类似手势的`expressionHoldState`状态机。

2. **头部动作检测**：通过FaceLandmarker的landmark点帧间位移实现：
   - `landmark 1` (noseTip) 的Y轴变化检测点头
   - `landmark 1` (noseTip) 的X轴变化检测摇头
   - `landmark 234`和`454`（左右耳朵）的Y差值检测歪头
   - 需要维护最近10帧的landmark历史，用位移模式匹配判断动作

3. **防冲突**：表情动作和手势动作使用同一个冷却队列，同时只能触发一个

4. **可配置**：所有阈值和映射关系用户可在设置面板中调整

#### A1.2 表情控制设置面板（客户端）

**修改文件：** `src/client/app.html` 或 `src/client/admin.html`

新增"表情控制"设置页，允许用户：
- 开关每种表情动作
- 调整灵敏度（阈值）
- 调整持续时间（holdMs）
- 自定义表情→动作映射
- 实时预览（显示当前检测到的表情和阈值仪表盘）

```
设置面板布局：

┌─ 表情控制设置 ──────────────────────────────────┐
│                                                   │
│  [开关] 启用表情控制                               │
│                                                   │
│  预览区: [摄像头画面] + 实时检测到的表情标签         │
│                                                   │
│  嘴部动作                                         │
│  ├─ 😊 微笑确认    [开关] 灵敏度 [━━━●━━] 2.0秒  │
│  ├─ 🗣️ 张嘴说话    [开关] 灵敏度 [━━●━━━] 0.8秒  │
│  └─ 😘 嘟嘴截图    [开关] 灵敏度 [━━━●━━] 1.5秒  │
│                                                   │
│  眉毛动作                                         │
│  ├─ 🤨 挑眉上翻    [开关] 灵敏度 [━━━●━━] 1.0秒  │
│  └─ 😤 皱眉下翻    [开关] 灵敏度 [━━━●━━] 1.0秒  │
│                                                   │
│  眼睛动作                                         │
│  ├─ 😉 左眨=点击   [开关] 灵敏度 [━━━●━━] 0.5秒  │
│  ├─ 😉 右眨=右键   [开关] 灵敏度 [━━━●━━] 0.5秒  │
│  └─ 😑 双闭=回车   [开关] 灵敏度 [━━━●━━] 1.2秒  │
│                                                   │
│  头部动作                                         │
│  ├─ ✅ 点头确认    [开关] 灵敏度 [━━━●━━]         │
│  ├─ ❌ 摇头取消    [开关] 灵敏度 [━━━●━━]         │
│  ├─ ↩️ 左歪=撤销   [开关] 灵敏度 [━━━●━━]         │
│  └─ ↪️ 右歪=重做   [开关] 灵敏度 [━━━●━━]         │
│                                                   │
│  [高级] 自定义映射...                              │
│  [导出配置] [导入配置] [恢复默认]                    │
└───────────────────────────────────────────────────┘
```

#### A1.3 配置持久化（服务端）

**修改文件：** `src/server/main.py`, 新建 `src/server/access_config.py`

```python
# src/server/access_config.py
"""
无障碍控制配置管理

持久化用户的表情/手势/眼神控制映射配置。
存储位置: data/access_config.json
"""

@dataclass
class AccessConfig:
    # 表情控制
    expression_enabled: bool = False
    expression_mappings: Dict[str, ExpressionMapping] = ...
    expression_sensitivity: float = 1.0  # 全局灵敏度系数

    # 手势控制
    gesture_enabled: bool = True
    gesture_mappings: Dict[str, GestureMapping] = ...
    gesture_hold_ms: int = 700

    # 眼神控制（A阶段2实现）
    gaze_enabled: bool = False
    gaze_mappings: Dict[str, GazeMapping] = ...

    # 配置文件路径
    config_path: Path = Path("data/access_config.json")
```

**新增API端点：**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/access/config` | GET | 获取当前无障碍配置 |
| `/api/access/config` | PUT | 更新配置 |
| `/api/access/config/reset` | POST | 恢复默认配置 |
| `/api/access/presets` | GET | 获取预设方案列表 |
| `/api/access/preset/{name}` | POST | 应用预设方案 |

**预设方案（开箱即用）：**

| 预设名 | 适用场景 | 启用的控制方式 |
|--------|---------|--------------|
| `hands_free` | 完全无法使用双手 | 表情全开 + 头部动作 + 语音 |
| `one_hand` | 只能用一只手 | 单手手势 + 语音 + 表情辅助 |
| `voice_only` | 双手被占用 | 纯语音控制 |
| `mouse_assist` | 可以用鼠标但打字困难 | 语音输入 + 表情快捷 |
| `power_user` | 效率极客 | 全部开启，短触发时间 |
| `gentle` | 初次使用/老年人 | 长触发时间，少量映射 |

### A阶段2：眼神追踪（2周）

**目标：** 用眼神方向辅助定位屏幕位置（精度：9宫格级别）。

#### A2.1 虹膜方向检测（客户端）

**修改文件：** `src/client/app.html`

利用 MediaPipe FaceLandmarker 的虹膜 landmarks（468-477）：

```javascript
// ── 眼神方向估计 ──
function estimateGazeDirection(faceLandmarks) {
  // 虹膜中心
  const leftIris  = faceLandmarks[468];  // 左眼虹膜中心
  const rightIris = faceLandmarks[473];  // 右眼虹膜中心

  // 眼眶参考点
  const leftEyeInner  = faceLandmarks[133];
  const leftEyeOuter  = faceLandmarks[33];
  const rightEyeInner = faceLandmarks[362];
  const rightEyeOuter = faceLandmarks[263];

  // 虹膜在眼眶中的相对位置 (0=最左, 0.5=正中, 1=最右)
  const leftRatioX = (leftIris.x - leftEyeOuter.x) /
                     (leftEyeInner.x - leftEyeOuter.x);
  const rightRatioX = (rightIris.x - rightEyeOuter.x) /
                      (rightEyeInner.x - rightEyeOuter.x);

  // 上下方向类似（用上下眼睑landmarks）
  // ... 省略垂直方向计算

  // 双眼平均 → 3x3 九宫格区域
  const avgX = (leftRatioX + rightRatioX) / 2;
  // avgX < 0.35 → 看左, 0.35-0.65 → 看中, > 0.65 → 看右
  // 类似处理垂直方向

  return {
    zone: 'center',  // 九宫格: top-left, top, top-right, left, center, right, bottom-left, bottom, bottom-right
    confidence: 0.8,
    rawX: avgX,
    rawY: avgY,
  };
}
```

**注意事项：**
- 普通摄像头精度有限，只能做到9宫格（3x3）级别的区域定位
- 需要初始校准：让用户看屏幕四个角 + 中心点
- 戴眼镜会影响检测精度，需要在校准时处理
- 这不是精确眼动追踪，定位为"注视区域提示"

#### A2.2 注视光标与视觉反馈

屏幕上显示一个半透明的"注视区域"光晕，跟随眼神移动：

```
┌──────────────────────────────────┐
│              │                   │
│              │                   │
│     ┌──────────────┐             │
│     │  ●  注视区域  │             │ ← 半透明蓝色光晕
│     │    (中央)     │             │    跟随眼神移动
│     └──────────────┘             │
│              │                   │
│              │                   │
└──────────────────────────────────┘
```

**交互模式：**
- 眼睛看向某区域 + 左眨眼 → 在该区域的中心点击
- 眼睛看向某区域 + 语音"点这个" → 精确定位到该区域内的OCR文字
- 眼睛看向某区域 + 手指指向 → 手指提供精确坐标，眼神确认区域

### A阶段3：无AI模式优化（2周）

**目标：** 让手势/表情/眼神控制在没有AI、没有网络的情况下也能完整工作。

#### A3.1 本地模式开关

当前很多功能依赖云端LLM。需要一个纯本地模式：

**修改文件：** `src/server/main.py`, `src/client/app.html`

```
纯本地模式下可用的功能：
  ✅ 手势→光标/点击/拖拽/滚动/快捷键
  ✅ 表情→点击/确认/取消/滚动/回车
  ✅ 眼神→区域定位+眨眼点击
  ✅ 语音→本地命令识别（预定义命令列表，不需要LLM）
  ✅ 桌面快捷键映射
  ✅ 窗口管理（切换/最小化/关闭）
  ❌ AI对话（需要网络）
  ❌ AI桌面控制（需要LLM）
  ❌ 情感检测（需要SenseVoice）
```

#### A3.2 本地语音命令引擎

**新建文件：** `src/server/local_voice_commands.py`

不用LLM，用关键词匹配实现基础语音命令：

```python
"""
本地语音命令引擎（零网络依赖）

使用jieba分词 + 关键词匹配，识别预定义命令。
不需要LLM，延迟<100ms。
"""

VOICE_COMMANDS = {
    # 应用启动
    "打开微信":     {"action": "skill", "skill_id": "open_wechat"},
    "打开浏览器":   {"action": "skill", "skill_id": "open_browser"},
    "打开记事本":   {"action": "skill", "skill_id": "open_notepad"},
    "打开文件管理": {"action": "skill", "skill_id": "open_explorer"},

    # 窗口操作
    "切换窗口":     {"action": "hotkey", "keys": ["alt", "tab"]},
    "关闭窗口":     {"action": "hotkey", "keys": ["alt", "F4"]},
    "最小化":       {"action": "hotkey", "keys": ["win", "d"]},
    "最大化":       {"action": "hotkey", "keys": ["win", "up"]},

    # 编辑操作
    "复制":         {"action": "hotkey", "keys": ["ctrl", "c"]},
    "粘贴":         {"action": "hotkey", "keys": ["ctrl", "v"]},
    "剪切":         {"action": "hotkey", "keys": ["ctrl", "x"]},
    "撤销":         {"action": "hotkey", "keys": ["ctrl", "z"]},
    "重做":         {"action": "hotkey", "keys": ["ctrl", "y"]},
    "全选":         {"action": "hotkey", "keys": ["ctrl", "a"]},
    "保存":         {"action": "hotkey", "keys": ["ctrl", "s"]},
    "查找":         {"action": "hotkey", "keys": ["ctrl", "f"]},

    # 滚动
    "往上翻":       {"action": "scroll", "dy": 5},
    "往下翻":       {"action": "scroll", "dy": -5},
    "翻到顶部":     {"action": "hotkey", "keys": ["ctrl", "home"]},
    "翻到底部":     {"action": "hotkey", "keys": ["ctrl", "end"]},

    # 系统
    "截图":         {"action": "screenshot"},
    "锁屏":         {"action": "skill", "skill_id": "lock_screen"},
    "静音":         {"action": "volume", "level": 0},
    "音量最大":     {"action": "volume", "level": 100},

    # 控制
    "停止":         {"action": "stop_all"},
    "暂停":         {"action": "pause_ai"},
    "继续":         {"action": "resume_ai"},
}
```

#### A3.3 打包为独立产品

**新建文件：** `installer_access.iss` (基于现有installer.iss修改)

独立打包"十三香无障碍控制"版本：
- 安装包更小（不含AI模型相关依赖）
- 标准版依赖 + 桌面控制三件套
- 默认启用表情控制 + 手势控制
- 首次运行引导用户校准（摄像头位置、表情阈值）
- 安装后自动创建"无障碍控制"配置预设

### A阶段4：上线准备（2周）

#### A4.1 首次使用校准向导

**修改文件：** `src/client/setup.html` 或新建 `src/client/calibration.html`

```
校准向导流程（3分钟）：

第1步：摄像头检查
  "请确保你的脸在画面中央，光线充足"
  [摄像头预览] [✓ 检测到人脸]

第2步：表情校准
  "请做以下表情，我来记录你的基准值"
  → 自然表情 (10秒) → 记录中性基准
  → 微笑 (3秒) → 记录微笑阈值
  → 挑眉 (3秒) → 记录挑眉阈值
  → 眨左眼 (3次) → 记录眨眼模式
  → 张嘴 (3秒) → 记录张嘴阈值

第3步：手势校准（如果启用）
  "请做以下手势"
  → 竖起食指 → ✌️ → 握拳 → 张开手掌

第4步：眼神校准（如果启用）
  "请依次看向屏幕的五个点"
  → 左上角 → 右上角 → 中心 → 左下角 → 右下角

第5步：选择预设
  "选择最适合你的控制方案"
  [完全免手] [单手辅助] [语音为主] [全部开启] [自定义]

  "校准完成！随时可以在设置中重新校准。"
```

#### A4.2 无障碍合规

- 确保产品本身可以通过屏幕阅读器操作
- 设置面板支持键盘导航（Tab/Enter）
- 高对比度模式支持
- 支持Windows讲述人和macOS VoiceOver

---

## 四、赛道B开发计划 — 人AI协同工作台

> 建立在赛道A的多模态输入层之上，增加AI协同能力。

### B阶段1：意图融合引擎（3周）

**目标：** 多通道信号智能融合为统一意图。

#### B1.1 融合引擎核心

**新建文件：** `src/server/intent_fusion.py`

> 详细设计见 DEV_ROADMAP.md 任务1.1

**核心融合规则：**

```
优先级：紧急停止 > 明确语音指令 > 手势动作 > 表情情感
互补：手指位置 + 语音"打开这个" = 精确点击
增强：语音"确认" + 点头 = 高置信度确认
冲突：手势点击 + 语音"等一下" = 取消点击（语音优先）
情感：不直接触发操作，但影响AI回复风格
```

#### B1.2 信号总线

**修改文件：** `src/client/app.html`, `src/server/routers/desktop.py`

统一所有通道的信号格式，通过 `/ws/desktop` 传输：

```json
{"type":"signal", "source":"gesture", "name":"Pointing_Up", "ts":1710000000,
 "data":{"position":{"x":0.3,"y":0.5}, "confidence":0.95}}

{"type":"signal", "source":"expression", "name":"nod", "ts":1710000000,
 "data":{"pattern":"down_up", "confidence":0.8}}

{"type":"signal", "source":"voice", "name":"command", "ts":1710000000,
 "data":{"text":"打开这个", "intent":"click_target"}}

{"type":"signal", "source":"gaze", "name":"zone", "ts":1710000000,
 "data":{"zone":"center-right", "duration_ms":2500}}
```

### B阶段2：协同调度系统（3周）

#### B2.1 协同工作总线

**新建文件：** `src/server/cowork_bus.py`

> 详细设计见 DEV_ROADMAP.md 任务2.1

核心能力：
- 检测人正在操作的窗口（通过前台窗口+鼠标活动+手势方向）
- AI不碰人正在操作的区域
- 人✋停止 → AI立即停止所有操作
- 任务进度通过WebSocket实时推送

#### B2.2 AI后台任务

**修改文件：** `src/server/routers/desktop.py`

新增后台任务模式。AI可以：
- 在最小化的窗口中操作
- 操作完成后语音通知
- 人可以切过去查看，AI自动暂停让出

**新增API：**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/cowork/task` | POST | 创建后台任务 |
| `/api/cowork/tasks` | GET | 任务列表 |
| `/api/cowork/task/{id}/stop` | POST | 停止任务 |
| `/ws/cowork` | WS | 进度推送 |

#### B2.3 操作回滚

**新建文件：** `src/server/action_journal.py`

> 详细设计见 DEV_ROADMAP.md 任务2.4

AI每步操作都记录前后截图，人用☝️(Ctrl+Z)或语音"撤销"可回退。

### B阶段3：MCP生态（4周）

#### B3.1 桌面控制MCP Server

**新建文件：** `src/mcp/desktop_server.py`

将DesktopStreamer包装为标准MCP Server：

```
暴露的MCP工具：
  desktop.screenshot    → 截图
  desktop.ocr           → OCR识别
  desktop.click         → 点击
  desktop.type          → 输入
  desktop.find_click    → OCR+点击
  desktop.windows       → 窗口列表
  desktop.focus         → 聚焦窗口
  desktop.hotkey        → 快捷键
```

这让其他AI客户端（Claude Desktop、Cursor）也能通过MCP调用十三香的桌面控制。

#### B3.2 手势→MCP工具绑定

允许用户把手势绑定到任意MCP工具：

```json
{
  "gesture_mcp_bindings": {
    "Victory": {"server": "desktop", "tool": "screenshot"},
    "combo:Victory+Thumb_Up": {"server": "image-tool", "tool": "enhance"}
  }
}
```

---

## 五、时间线总览

```
2026年3月                      6月                      9月
   │                           │                        │
   ▼                           ▼                        ▼

   ══ 赛道A：无障碍桌面控制 ═══════════════════════
   │                                               │
   ├─ A1 表情动作系统 (2周) ───┐                    │
   ├─ A2 眼神追踪 (2周) ──────┤                    │
   ├─ A3 无AI模式优化 (2周) ──┤                    │
   ├─ A4 上线准备 (2周) ──────┘                    │
   │            ▲                                   │
   │         v3.5.0                                 │
   │      首个无障碍版本发布                          │
   │                                               │
   ══ 赛道B：人AI协同工作台 ═══════════════════════
   │                                               │
   │         ├─ B1 意图融合 (3周) ───┐              │
   │         ├─ B2 协同调度 (3周) ──┤              │
   │         ├─ B3 MCP生态 (4周) ──┘              │
   │                        ▲                      │
   │                     v4.0.0                     │
   │                  协同工作台发布                   │
   │                                               │
   ═══════════════════════════════════════════════
```

### 里程碑

| 版本 | 时间 | 交付物 |
|------|------|--------|
| v3.4.0 | 第2周末 | 表情动作系统完成，可用表情控制电脑 |
| v3.5.0 | 第8周末 | **赛道A上线：完整无障碍桌面控制产品** |
| v3.6.0 | 第11周末 | 意图融合引擎完成 |
| v3.8.0 | 第14周末 | 协同调度系统完成 |
| v4.0.0 | 第18周末 | **赛道B上线：完整人AI协同工作台** |

---

## 六、打包策略

### 两个安装包

| 安装包 | 文件名 | 目标用户 | 大小 |
|--------|--------|---------|------|
| 无障碍版 | `十三香-无障碍控制-v3.5-Setup.exe` | 残障/辅助/效率 | ~60MB |
| 完整版 | `十三香-协同工作台-v4.0-Setup.exe` | 知识工作者 | ~100MB |

### 无障碍版 依赖（不需要PyTorch）

```
# Web框架
fastapi, uvicorn, websockets, pydantic, pydantic-settings, python-multipart

# 桌面控制（核心）
pyautogui, mss, rapidocr-onnxruntime, pyperclip

# 语音（轻量）
edge-tts, silero-vad, numpy, soundfile

# AI后端（可选，有网时使用）
openai, httpx

# 工具
pyyaml, python-dotenv, loguru, cryptography,
pillow, jieba, qrcode[pil], pystray, customtkinter
```

### 完整版 额外依赖

```
# 本地语音识别
torch, torchaudio, faster-whisper, funasr, transformers

# 高级桌面控制
uiautomation

# 高级TTS
elevenlabs
```

---

## 七、开发优先级排序

| 优先级 | 任务ID | 任务 | 预计工时 | 依赖 |
|--------|--------|------|---------|------|
| **P0** | A1.1 | 扩展表情检测（blendshape+头部动作） | 20h | 无 |
| **P0** | A1.2 | 表情控制设置面板 | 12h | A1.1 |
| **P0** | A1.3 | 配置持久化+预设方案 | 8h | A1.2 |
| **P1** | A2.1 | 虹膜方向检测 | 16h | 无 |
| **P1** | A2.2 | 注视光标与视觉反馈 | 8h | A2.1 |
| **P1** | A3.1 | 本地模式开关 | 4h | 无 |
| **P1** | A3.2 | 本地语音命令引擎 | 8h | 无 |
| **P1** | A3.3 | 独立安装包 | 4h | A1-A3 |
| **P2** | A4.1 | 首次使用校准向导 | 16h | A1-A3 |
| **P2** | A4.2 | 无障碍合规 | 8h | A4.1 |
| **P3** | B1.1 | 意图融合引擎核心 | 24h | A1-A2 |
| **P3** | B1.2 | 信号总线 | 8h | B1.1 |
| **P3** | B2.1 | 协同工作总线 | 20h | B1 |
| **P3** | B2.2 | AI后台任务 | 16h | B2.1 |
| **P3** | B2.3 | 操作回滚 | 12h | B2.1 |
| **P4** | B3.1 | 桌面控制MCP Server | 12h | 无 |
| **P4** | B3.2 | 手势→MCP工具绑定 | 8h | B3.1 |

**总工时估计：** ~224小时（约28个工作日）

---

## 八、成功指标

### 赛道A — 无障碍版（v3.5.0）

| 指标 | 目标值 |
|------|--------|
| 表情识别准确率 | >90%（校准后） |
| 表情误触发率 | <5%（持续时间阈值过滤后） |
| 头部动作（点头/摇头）准确率 | >85% |
| 纯表情模式下完成基础任务（打开应用/点击/滚动/输入） | 可行 |
| 眼神区域定位准确率（9宫格） | >70% |
| 无网络模式下所有控制功能可用 | 是 |
| 安装到可用时间 | <5分钟 |
| 校准向导时间 | <3分钟 |

### 赛道B — 协同工作台（v4.0.0）

| 指标 | 目标值 |
|------|--------|
| 多模态融合后意图识别准确率 | >80% |
| 人AI协同完成任务成功率 | >60%（对比纯AI的24%） |
| AI操作不干扰人正在操作的窗口 | 100% |
| 紧急停止响应时间（✋手势→AI停止） | <500ms |
| AI后台任务完成通知延迟 | <2秒 |

---

## 九、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 普通摄像头眼神追踪精度不够 | 高 | 中 | 降级为9宫格而非精确定位，配合语音/手指精确补充 |
| 表情误触发影响体验 | 中 | 高 | 持续时间阈值 + 校准 + 用户可关闭单项 |
| 巨头做出类似产品 | 中 | 高 | 速度优先，先占无障碍市场；开源建立社区壁垒 |
| AI Agent成功率短期不会提升 | 高 | 低 | 赛道A不依赖AI，赛道B用人来补AI不足 |
| 用户不习惯表情/手势操作 | 中 | 中 | 校准向导 + 渐进式引导 + 预设方案 |

---

> **本文档是最终开发方案。新Agent请从P0任务（A1.1表情动作系统）开始执行。**
> **技术细节参考 DEV_ROADMAP.md。**
