# 十三香小龙虾 — 人机协同桌面控制 开发路线图

> **版本：** v3.3.0 → v4.0 目标
> **日期：** 2026-03-17
> **定位：** 多模态人机协同桌面控制平台 — 用最自然的方式（手势、表情、语音、眼神）和AI一起控制电脑

---

## 一、产品定位与行业对标

### 我们是谁

十三香小龙虾是一个**本地部署的多模态AI桌面助手**，用户通过手势、面部表情、语音、触控四种通道同时与AI协作控制电脑桌面。

### 与业界巨头的差异化

| 维度 | Claude Cowork (Anthropic) | OpenAI Operator/CUA | Microsoft Copilot | **十三香小龙虾** |
|------|--------------------------|--------------------|--------------------|----------------|
| 输入方式 | 文本提示 | 文本提示 | 文本/语音 | **手势+表情+语音+触控** |
| 控制模式 | AI独占控制(VM隔离) | AI独占浏览器 | 应用内辅助 | **人AI共享桌面** |
| 人的角色 | 监督者 | 偶尔接管 | 指令发出者 | **全程参与的共驾者** |
| 情感感知 | 无 | 无 | 无 | **语音情感+面部表情** |
| 部署方式 | 云端 | 云端 | 云端 | **本地部署，数据不出电脑** |
| 价格 | API计费 | $200/月 | 企业付费 | **免费/开源** |

### 核心理念

**不是"AI替你操作"，不是"人指挥AI"，而是"人和AI并肩工作"。**

人不需要退出控制权来让AI工作。人的手势、眼神、表情、声音都是实时控制信号，AI感知这些信号并配合行动。

---

## 二、当前代码架构（v3.3.0 现状）

### 2.1 整体数据流

```
┌─────────────────── 客户端 (src/client/app.html) ───────────────────┐
│                                                                     │
│  摄像头 → MediaPipe GestureRecognizer ─┬→ 标准手势命令(7种)         │
│           (GPU加速, 2手, VIDEO模式)    ├→ 桌面手势控制(光标/点击/拖拽)│
│                                        ├→ 手势连招(6种组合)          │
│                                        ├→ 捏合=空中截图              │
│                                        └→ 手指计数=音量控制          │
│                                                                     │
│  摄像头 → MediaPipe FaceLandmarker ────→ 表情标签展示(仅展示)        │
│           (blendshapes输出)             微笑/惊讶/眨眼/说话          │
│                                                                     │
│  麦克风 → WebSocket → 服务端STT ────────→ 语音意图识别               │
│                                         → 情感检测 → AI语气适应      │
│                                                                     │
│  桌面画布 → 触控/鼠标 ─── WebSocket ───→ 直接桌面操作               │
│                                                                     │
├──────────────────── WebSocket/HTTP ─────────────────────────────────┤
│                                                                     │
│                     服务端 (src/server/)                             │
│  desktop.py       → DesktopStreamer: 屏幕捕获+OCR+鼠标键盘控制      │
│  vision_control.py → VisionController: OCR→UI元素→动作执行           │
│  desktop_skills.py → 预定义技能包(打开微信/发消息/截图等)            │
│  routers/desktop.py → AI决策循环: 截图→OCR→LLM规划→执行→验证        │
│  emotion.py       → 情感引擎: 检测→AI适应→TTS语气调整               │
│  mcp/client.py    → MCP协议客户端: 连接外部工具服务器                │
│  skills/_engine/  → 技能注册/发现/执行引擎                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键文件索引

#### 桌面控制核心

| 文件 | 核心类/函数 | 职责 |
|------|-----------|------|
| `src/server/desktop.py` | `DesktopStreamer` (L24) | 屏幕捕获、OCR、鼠标键盘控制、AI动作执行 |
| `src/server/vision_control.py` | `VisionController` (L181) | OCR→UI元素解析→结构化屏幕状态 |
| `src/server/desktop_skills.py` | `SKILL_REGISTRY` | 预定义桌面自动化技能包 |
| `src/server/routers/desktop.py` | `desktop_ai_command` (L160) | AI驱动桌面控制的HTTP端点 |

#### 多模态输入（客户端）

| 功能 | 文件位置 | 关键行号 |
|------|---------|---------|
| 手势命令映射 | `src/client/app.html` | L5328-5359 |
| 手势连招系统 | `src/client/app.html` | L5367-5374 |
| 桌面手势控制(光标/拖拽) | `src/client/app.html` | L5735-5915 |
| 捏合截图 | `src/client/app.html` | L5445 |
| 手指音量控制 | `src/client/app.html` | L5494 |
| 面部表情检测 | `src/client/app.html` | L6246-6257 |
| 情感系统UI | `src/client/app.html` | L8713-8776 |
| 手势保持时间 | `src/client/app.html` | L5519 `GESTURE_HOLD_MS=700` |
| 手势冷却时间 | `src/client/app.html` | L5520 `GESTURE_COOLDOWN_MS=2500` |
| 连招窗口时间 | `src/client/app.html` | L5367 `COMBO_WINDOW_MS=2500` |

#### 情感与AI适应

| 文件 | 核心内容 |
|------|---------|
| `src/server/emotion.py` | `EmotionEngine` (L89): 6种情感(happy/sad/angry/surprised/fearful/neutral) |
| | `_PROMPT_INJECTION` (L48): 每种情感对应的AI提示词注入 |
| | `_TTS_EMOTION_MAP` (L71): 情感→TTS语音风格映射 |
| | `_EVENT_RESPONSES` (L80): 音频事件(笑/哭/咳嗽)→共情回复 |

#### MCP工具协议

| 文件 | 核心内容 |
|------|---------|
| `src/mcp/client.py` | `MCPClient` (L44): 支持stdio/http/sse三种传输 |
| | `call_tool()` (L189): 调用任意MCP服务器上的工具 |
| | `_discover_tools_*()` (L144/161): 自动发现服务器能力 |
| | 配置持久化: `data/mcp_servers/servers.json` |

#### 技能引擎

| 文件 | 核心内容 |
|------|---------|
| `skills/_engine/registry.py` | `SkillRegistry` (L74): 扫描skills/子目录，读取_meta.json注册技能 |
| | `Skill` (L12): 两种类型 — code(Python函数) / prompt(领域专家提示词) |
| | 发现流程: skills/*/\_meta.json → Skill对象 → 按ID和分类索引 |

### 2.3 当前手势控制映射表

#### 标准模式（非桌面控制时）

| 手势 | 图标 | 动作 | 触发方式 |
|------|------|------|---------|
| Thumb_Up | 👍 | AI确认("好的，请继续") | 保持700ms |
| Thumb_Down | 👎 | AI否定("不好，换一个") | 保持700ms |
| Open_Palm | ✋ | 停止播放 | 保持700ms |
| Closed_Fist | ✊ | 打开桌面控制 | 保持700ms |
| Pointing_Up | ☝️ | 开始/停止录音 | 保持700ms |
| Victory | ✌️ | 截图 | 保持700ms |
| ILoveYou | 🤟 | AI打招呼 | 保持700ms |

#### 桌面控制模式

| 输入 | 检测方式 | 桌面动作 |
|------|---------|---------|
| 食指指向 | landmark[8]坐标, EMA平滑α=0.18 | 鼠标光标移动 |
| 握拳(短) | Closed_Fist + 移动<0.04 | 点击 |
| 握拳(长+移动) | Closed_Fist + 移动>0.04 | 拖拽 |
| 快速双拳 | 两次Fist间隔<380ms | 双击 |
| 双指竖起 | 食指+中指竖, 无名指弯 | 滚动 |
| 手掌滑动 | Open_Palm速度>0.22/500ms | 窗口切换(Alt+←/→, Win+↑/D) |
| ✌️ | Victory手势 | 右键菜单 |
| 🤟 | ILoveYou手势 | Ctrl+C 复制 |
| ✋ | Open_Palm手势 | Ctrl+V 粘贴 |
| ☝️ | Pointing_Up手势 | Ctrl+Z 撤销 |
| 👍 | Thumb_Up | 向上滚动 |
| 👎 | Thumb_Down | 向下滚动 |

#### 手势连招

| 连招序列 | 效果 |
|---------|------|
| ✌️ → 👍 | 截图 → AI分析 |
| ✋ → ☝️ | 切换语言 |
| 🤟 → ✊ | 进入桌面代理模式 |
| 👍 → 👍 | 最大音量 |
| 👎 → 👎 | 静音 |

### 2.4 AI桌面控制循环（当前实现）

`POST /api/desktop-cmd` → `desktop_ai_command()` (routers/desktop.py L160)

```
循环（最多5轮）:
  1. DesktopStreamer.capture_screenshot_b64() → 截取当前屏幕
  2. DesktopStreamer.ocr_screen() → OCR识别所有文字及归一化坐标
  3. 构建 DESKTOP_AI_SYSTEM_PROMPT（含OCR结果+技能列表）
  4. 流式调用 LLM（deepseek-chat via gateway）
  5. 解析响应中的 [ACTIONS]...[/ACTIONS] JSON数组
  6. DesktopStreamer.execute_actions(actions) → 执行（上限15步）
  7. 再次截图发给客户端显示
  8. 将执行结果追加到上下文，进入下一轮
```

支持的16种动作类型：click, double_click, type, key, hotkey, scroll, wait, find_and_click, find_and_double_click, screenshot, focus_window, minimize_all, close_window, find_and_type

### 2.5 当前面部表情检测

使用 MediaPipe FaceLandmarker 的 blendshapes 输出 (app.html L6246):

| 表情 | Blendshape | 阈值 | 当前用途 |
|------|-----------|------|---------|
| 微笑 | mouthSmileLeft/Right | >0.5 | **仅UI展示** |
| 惊讶 | browInnerUp | >0.5 | **仅UI展示** |
| 眨眼 | eyeBlinkLeft>0.6 + eyeBlinkRight<0.3 | 组合 | **仅UI展示** |
| 说话 | jawOpen | >0.5 | **仅UI展示** |

> **重要：表情目前只展示不触发动作，这是第一阶段要解决的核心问题。**

### 2.6 API端点完整列表

| 路径 | 方法 | 功能 |
|------|------|------|
| `/api/desktop-cmd` | POST | AI驱动桌面控制(多轮) |
| `/api/desktop-skills` | GET | 列出可用技能包 |
| `/api/desktop-skill/{id}` | POST | 执行指定技能 |
| `/api/desktop-skill/send_wechat_message` | POST | 发送微信消息(OCR验证) |
| `/ws/desktop` | WS | 桌面帧流+控制命令 |
| `/api/vision-control/screen` | GET | 结构化UI元素状态 |
| `/api/vision-control/describe` | GET | 屏幕文字描述 |
| `/api/vision-control/execute` | POST | 执行UI动作 |
| `/api/upload` | POST | 上传文件到电脑 |
| `/api/emotion/toggle` | POST | 开关情感检测 |
| `/api/emotion/state` | GET | 查询情感状态 |

---

## 三、开发路线图

### 第一阶段：多模态意图融合引擎（v3.4 → v3.5）

**目标：** 让四个输入通道（手势/表情/语音/触控）不再独立工作，而是协同判断用户意图。

**核心问题：** 当前各通道是互相隔离的。手势有手势的处理，语音有语音的处理。同时出现两个信号时无法智能融合。

#### 任务 1.1：创建意图融合引擎

**新建文件：** `src/server/intent_fusion.py`

```python
"""
多模态意图融合引擎

将手势、表情、语音、触控四个通道的信号在时间窗口内融合，
产出一个统一的高级意图。

设计原则：
  - 安全优先：✋ 停止手势 > 一切其他信号
  - 互补融合：手指位置 + 语音动作 = 精确操作
  - 冲突消解：同时收到两个动作类信号时，优先语音（更明确）
  - 情感加权：表情和语音情感影响AI回复风格，不直接触发操作
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum
import time


class SignalType(Enum):
    GESTURE = "gesture"
    EXPRESSION = "expression"
    VOICE = "voice"
    TOUCH = "touch"
    EMOTION = "emotion"


class IntentPriority(Enum):
    EMERGENCY = 0    # 停止、回滚
    ACTION = 1       # 明确操作指令
    CONTEXT = 2      # 位置/目标上下文
    MOOD = 3         # 情感/态度信号


@dataclass
class Signal:
    """单个通道的原始信号"""
    source: SignalType
    name: str                      # e.g. "Closed_Fist", "smile", "打开微信"
    timestamp: float
    priority: IntentPriority
    data: Dict = field(default_factory=dict)
    # data examples:
    #   gesture: {position: {x, y}, gesture_name: "Pointing_Up"}
    #   expression: {type: "smile", confidence: 0.8}
    #   voice: {text: "打开微信", intent: "open_app", target: "微信"}
    #   touch: {x: 0.5, y: 0.3, action: "click"}
    #   emotion: {emotion: "happy", confidence: 0.9}


@dataclass
class FusedIntent:
    """融合后的统一意图"""
    action: str                    # "click", "open_app", "stop", "scroll", etc.
    target: Optional[str] = None   # 目标（文字/应用名）
    position: Optional[tuple] = None  # (x, y) 归一化坐标
    text: Optional[str] = None     # 要输入的文字
    emotion_context: str = "neutral"  # 情感上下文
    confidence: float = 0.0
    sources: List[SignalType] = field(default_factory=list)  # 哪些通道贡献了这个意图


class IntentFusionEngine:
    """
    多模态意图融合引擎

    使用方式：
      engine = IntentFusionEngine()
      engine.push_signal(gesture_signal)
      engine.push_signal(voice_signal)
      intent = engine.fuse()  # 返回融合后的意图，或None（信号不足）
    """

    FUSION_WINDOW_MS = 500    # 500ms内的信号视为同一意图
    EMERGENCY_GESTURES = {"Open_Palm"}  # 紧急停止手势

    def __init__(self):
        self._buffer: List[Signal] = []
        self._last_fused: float = 0
        self._emotion_state: str = "neutral"

    def push_signal(self, signal: Signal):
        """推入一个通道信号"""
        self._buffer.append(signal)
        # 紧急信号立即处理
        if (signal.priority == IntentPriority.EMERGENCY):
            return self._emergency_fuse(signal)
        return None

    def fuse(self) -> Optional[FusedIntent]:
        """
        融合缓冲区内的信号

        融合规则：
        1. 紧急信号(✋停止) → 立即返回stop意图，清空缓冲区
        2. 语音+手势位置 → 用语音的动作 + 手势的位置
        3. 纯语音 → 直接用语音的意图
        4. 纯手势 → 直接用手势的动作
        5. 表情/情感 → 不产生动作，但附加到意图的emotion_context
        """
        now = time.time()
        window = self.FUSION_WINDOW_MS / 1000
        # 过滤时间窗口内的信号
        recent = [s for s in self._buffer if now - s.timestamp < window]
        self._buffer = recent  # 清理过期信号

        if not recent:
            return None

        # TODO: 实现完整的融合逻辑
        # 参见下方"融合规则矩阵"

    def _emergency_fuse(self, signal: Signal) -> FusedIntent:
        """紧急信号立即处理"""
        self._buffer.clear()
        return FusedIntent(
            action="stop",
            confidence=1.0,
            sources=[signal.source]
        )
```

**融合规则矩阵（需要实现）：**

| 手势 | 语音 | 表情 | 融合结果 |
|------|------|------|---------|
| ☝️指向(x,y) | "打开这个" | - | click(x,y) — 用手指位置+语音动作 |
| ☝️指向(x,y) | "把这个拖到那边" | - | drag — 第一次指向=起点，第二次=终点 |
| ✋停止 | 任何 | 任何 | **立即停止所有AI操作** |
| ✊握拳 | - | - | click(光标位置) — 纯手势 |
| - | "帮我打开微信" | - | open_app("微信") — 纯语音 |
| - | "这个方案不错" | 😊微笑 | AI收到积极反馈 — 情感增强确认 |
| - | "算了不要了" | - | cancel — 语音取消 |
| 👍 | "继续" | - | confirm — 手势+语音双重确认 |
| ✊握拳 | "点这里" | 😲惊讶 | click — 但AI注意到用户惊讶，后续解释操作 |

#### 任务 1.2：表情→动作映射

**修改文件：** `src/client/app.html` (L6246-6257)

当前表情只展示不触发动作。需要增加以下映射：

| 表情 | 触发条件 | 动作 |
|------|---------|------|
| 微笑(持续3秒) | mouthSmile > 0.5 持续3s | AI收到"用户满意"信号 |
| 皱眉(持续2秒) | browDownLeft > 0.4 持续2s | AI收到"用户困惑"信号，主动询问 |
| 连续眨眼(3次/2秒) | 快速眨眼模式检测 | 截图/特殊触发 |
| 张嘴(jawOpen>0.7) | 明显张嘴 | 开始语音录制（嘴巴准备说话） |
| 摇头 | noseTip水平位移检测 | 否定/取消当前AI操作 |
| 点头 | noseTip垂直位移检测 | 确认/同意AI建议 |

**实现要点：**
- 增加 `browDownLeft`, `browDownRight` blendshape 检测（皱眉）
- 增加 `noseTip` landmark (FaceLandmarker landmark 1) 的帧间位移追踪（点头/摇头）
- 所有表情动作都需要"持续时间阈值"，避免误触发
- 表情信号通过WebSocket发送到服务端的IntentFusionEngine

#### 任务 1.3：眼神追踪（注视方向）

**新增检测逻辑位置：** `src/client/app.html` 的 MediaPipe 处理段

MediaPipe FaceLandmarker 可以输出虹膜位置（landmarks 468-477），可用于粗略估计注视方向：

| 检测 | Landmark | 用途 |
|------|----------|------|
| 左眼虹膜中心 | 468 | 与眼眶中心的偏移 → 注视方向 |
| 右眼虹膜中心 | 473 | 同上 |
| 左眼眶中心 | (33+133)/2 | 基准点 |
| 右眼眶中心 | (362+263)/2 | 基准点 |

**实现方案：**
- 计算虹膜在眼眶中的相对位置 → 估算注视方向(左/右/上/下/中)
- 注视屏幕某区域 > 2秒 → 该区域高亮，表示"关注点"
- 结合语音"这个" → AI理解"这个"指的是注视区域的内容

**注意：** 这不是精确的眼动追踪（需要专用硬件），而是基于普通摄像头的粗略方向估计，精度约为屏幕的3x3九宫格区域。

#### 任务 1.4：建立信号总线

**修改文件：** `src/client/app.html`, `src/server/routers/desktop.py`

当前各通道通过不同的WebSocket消息和HTTP请求独立传递信号。需要建立统一的信号总线：

**客户端→服务端 信号协议：**

```json
{
  "type": "signal",
  "source": "gesture|expression|voice|touch|emotion",
  "name": "Pointing_Up",
  "timestamp": 1710000000.123,
  "data": {
    "position": {"x": 0.3, "y": 0.5},
    "confidence": 0.95
  }
}
```

通过现有的 `/ws/desktop` WebSocket 连接传输，在 `handle_command()` (desktop.py L381) 中增加 `type == "signal"` 分支，转发给 IntentFusionEngine。

#### 任务 1.5：打包调整

**修改文件：** `requirements.txt`, `installer.iss`

将桌面控制依赖从"完整版可选"改为"标准版必装"：

```
# requirements.txt 新增（从 requirements-full.txt 移入）
pyautogui>=0.9.54
mss>=9.0.0
rapidocr-onnxruntime>=1.2.0
```

`installer.iss` 中取消 localai/vision 分组，改为：
- **标准版：** 当前最小版 + 桌面控制三件套
- **专业版：** 标准版 + PyTorch + faster-whisper + funasr(情感识别)

---

### 第二阶段：人AI协同工作流引擎（v3.5 → v3.8）

**目标：** 从单步操作协同升级为任务级别协同。人和AI可以同时在不同窗口工作，任务管理器协调两者避免冲突。

#### 任务 2.1：协同工作总线（Collaborative Work Bus）

**新建文件：** `src/server/cowork_bus.py`

```python
"""
协同工作总线

管理人和AI在同一桌面上的并行操作，核心职责：
1. 屏幕区域锁定：人正在操作的窗口，AI不碰
2. 任务分配：人做前台任务，AI做后台任务
3. 冲突检测：两者要操作同一个目标时的仲裁
4. 进度同步：双方都知道对方做到哪了
5. 安全边界：人可以随时叫停AI（手势✋ → 立即停止）
"""

class WorkZone(Enum):
    HUMAN_ACTIVE = "human_active"    # 人正在操作的区域
    AI_ACTIVE = "ai_active"          # AI正在操作的区域
    SHARED = "shared"                # 共享区域
    IDLE = "idle"                    # 空闲区域


@dataclass
class WorkTask:
    id: str
    description: str
    owner: str                       # "human" | "ai" | "shared"
    status: str                      # "pending" | "active" | "paused" | "done"
    target_window: Optional[str]     # 目标窗口标题
    steps_total: int = 0
    steps_done: int = 0
    can_parallel: bool = True        # 是否允许人同时操作其他任务


class CoworkBus:
    """
    协同工作调度中心

    典型工作流：
    1. 人说"帮我把这10张图片都加水印"
    2. AI创建任务，分解为10个子步骤
    3. AI在后台逐个处理图片（AI_ACTIVE区域）
    4. 人可以同时做其他事情（HUMAN_ACTIVE区域）
    5. AI完成一个就通知人（语音+桌面通知）
    6. 人用👍确认，或✋暂停，或👎让AI重做
    """

    def create_task(self, description: str, owner: str) -> WorkTask:
        """创建新任务"""
        pass

    def claim_window(self, window_title: str, owner: str) -> bool:
        """声明某个窗口的操作权。如果已被另一方占用，返回False"""
        pass

    def release_window(self, window_title: str):
        """释放窗口操作权"""
        pass

    def get_human_zone(self) -> List[str]:
        """获取人当前正在操作的窗口列表（通过前台窗口+最近鼠标活动检测）"""
        pass

    def emergency_stop(self):
        """紧急停止所有AI操作（由✋手势触发）"""
        pass

    def report_progress(self, task_id: str, step: int, message: str):
        """AI汇报进度（通过WebSocket推送到客户端）"""
        pass
```

#### 任务 2.2：人类活动检测器

**新建文件：** `src/server/human_detector.py`

AI需要知道"人正在操作哪个窗口"，以避免冲突：

```python
"""
人类活动检测器

通过以下信号判断人当前的操作焦点：
1. 鼠标位置和移动速度（活跃区域）
2. 键盘输入（有输入的窗口 = 人在操作）
3. 前台窗口切换（人切到哪个窗口，那个就是人的）
4. 手势指向方向（指向哪里就是关注哪里）
5. 眼神注视方向（看哪个窗口就是关注哪个）

输出：
  - human_focus_window: 人当前关注的窗口
  - human_active_zone: 人正在操作的屏幕区域
  - human_idle: bool - 人是否处于空闲状态（超过30秒无操作）
"""
```

#### 任务 2.3：AI后台任务执行器

**修改文件：** `src/server/routers/desktop.py`

当前 `desktop_ai_command` 是前台操作（AI占用屏幕）。需要增加后台模式：

- AI可以将窗口最小化到后台操作
- 操作完成后通知人（语音 + 桌面通知）
- 人可以随时切到AI工作的窗口查看进度

**新增API端点：**

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/cowork/task` | POST | 创建协同任务 |
| `/api/cowork/tasks` | GET | 列出所有任务及状态 |
| `/api/cowork/task/{id}/pause` | POST | 暂停AI任务 |
| `/api/cowork/task/{id}/resume` | POST | 恢复AI任务 |
| `/api/cowork/task/{id}/cancel` | POST | 取消AI任务 |
| `/api/cowork/zones` | GET | 查看当前区域分配 |
| `/ws/cowork` | WS | 实时进度推送 |

#### 任务 2.4：AI操作回滚系统

AI执行的每个操作都可以被人撤销：

**新建文件：** `src/server/action_journal.py`

```python
"""
操作日志与回滚系统

AI执行的每个桌面操作都记录在日志中：
- 操作前截图（用于对比）
- 操作类型和参数
- 操作后截图（用于验证）
- 可回滚标记

人用 ☝️(Ctrl+Z) 手势可以撤销最近的AI操作。
复杂回滚（如删除了文件）通过截图对比提醒人确认。
"""

@dataclass
class ActionRecord:
    timestamp: float
    action_type: str
    params: dict
    screenshot_before: str    # base64
    screenshot_after: str     # base64
    reversible: bool          # 是否可自动回滚
    reverse_actions: List[dict]  # 回滚动作序列
```

#### 任务 2.5：协同场景实现

实现以下核心协同场景：

**场景A：人AI同时编辑文档**
```
人在Word第1页编辑 → AI同时在第5页排版
人切到第5页查看 → AI自动暂停，让出控制权
人👍确认 → AI继续处理第6页
```

**场景B：AI后台批量处理**
```
人说"帮我把这个文件夹里的图片都压缩一下"
→ AI在后台打开每张图片处理
→ 人继续浏览网页
→ AI完成一个就语音通知"第3张处理完了"
→ 人👍确认继续
```

**场景C：手势+语音精确指令**
```
人指向屏幕某处(☝️) + 说"把这个移到那边"
→ 第一个位置 = 手指指向
→ 人指向另一个位置 + 说"这里"
→ AI执行拖拽
```

---

### 第三阶段：MCP生态化 — 工具市场（v3.8 → v4.0）

**目标：** 让十三香小龙虾成为一个多模态MCP客户端平台，任何MCP Server都可以被手势/语音调用。

#### 任务 3.1：MCP工具发现与手势绑定

**修改文件：** `src/mcp/client.py`, `src/client/app.html`

允许用户将MCP工具绑定到手势：

```json
// 用户自定义手势→MCP工具绑定配置
{
  "gesture_bindings": {
    "Victory": {
      "mcp_server": "screenshot-tool",
      "tool": "capture_and_annotate",
      "params": {"format": "png"}
    },
    "combo:Victory+Thumb_Up": {
      "mcp_server": "image-editor",
      "tool": "enhance_screenshot",
      "params": {}
    }
  }
}
```

#### 任务 3.2：内置MCP Server — 桌面控制

**新建文件：** `src/mcp/desktop_server.py`

将现有的 DesktopStreamer 能力包装为标准MCP Server，让其他AI Agent也能调用：

```python
"""
MCP Server: 桌面控制

暴露以下工具：
  - desktop.screenshot → 截取屏幕
  - desktop.ocr → OCR识别屏幕文字
  - desktop.click → 点击
  - desktop.type → 输入文字
  - desktop.find_and_click → OCR定位+点击
  - desktop.get_windows → 列出窗口
  - desktop.focus_window → 聚焦窗口

传输方式：stdio 或 http (端口8767)
"""
```

这样做的好处：
- Claude Desktop 可以通过MCP调用十三香小龙虾的桌面控制
- 其他MCP客户端（Cursor、VS Code）可以使用桌面控制功能
- 形成生态：十三香小龙虾既是MCP Client也是MCP Server

#### 任务 3.3：应用专属MCP Server

为常用应用创建专属的MCP Server，比纯OCR更可靠：

| MCP Server | 工具 | 实现方式 |
|-----------|------|---------|
| `mcp-wechat` | 发消息/读消息/管理联系人 | 现有WeChat Skills包装 |
| `mcp-browser` | 打开URL/搜索/填表单 | Playwright/Selenium |
| `mcp-files` | 文件搜索/复制/移动/压缩 | Python os/shutil |
| `mcp-system` | 系统设置/网络/蓝牙/音量 | 平台原生API |

#### 任务 3.4：技能市场UI

**修改文件：** `src/client/admin.html` 或新建页面

在管理后台增加"技能市场"页面：
- 浏览社区MCP Server（从registry获取列表）
- 一键安装MCP Server
- 配置手势绑定
- 查看使用统计

#### 任务 3.5：A2A（Agent-to-Agent）协议支持

**新建文件：** `src/server/a2a.py`

MCP是"Agent↔Tool"的协议，A2A是"Agent↔Agent"的协议。支持A2A后，十三香小龙虾可以和其他AI Agent协作：

```
场景：十三香小龙虾 + 代码Agent协作
  人说"帮我改一下这个bug"
  → 十三香小龙虾(桌面Agent)截图IDE界面，识别错误信息
  → 通过A2A协议发送给代码Agent
  → 代码Agent返回修复方案
  → 十三香小龙虾在IDE中执行修改
  → 人用👍确认或👎拒绝
```

---

## 四、技术依赖与打包

### 标准版（v4.0）必装依赖

```
# Web框架
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
websockets>=12.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-multipart>=0.0.6

# AI后端
openai>=1.6.0
httpx>=0.26.0

# 语音
edge-tts>=6.1.0
silero-vad>=4.0.0
numpy>=1.26.0
soundfile>=0.12.1

# 桌面控制（核心功能，必装）
pyautogui>=0.9.54
mss>=9.0.0
rapidocr-onnxruntime>=1.2.0
pyperclip>=1.8.0

# 工具
pyyaml>=6.0.1
python-dotenv>=1.0.0
loguru>=0.7.2
cryptography>=42.0.0
pillow>=10.0.0
jieba>=0.42.1
qrcode[pil]>=7.4.2

# GUI
pystray>=0.19.5
customtkinter>=5.2.0
```

### 专业版额外依赖

```
# 本地语音识别
torch>=2.1.0
torchaudio>=2.1.0
faster-whisper>=1.0.0
funasr>=1.0.0           # SenseVoice情感识别
transformers>=4.36.0

# 高级音频处理
librosa>=0.10.1
webrtcvad>=2.0.10

# 高级TTS
elevenlabs>=1.0.0

# Windows自动化增强
uiautomation>=2.0.18
```

### 客户端依赖（CDN加载，无需安装）

```
@mediapipe/tasks-vision  — GestureRecognizer + FaceLandmarker
```

---

## 五、开发优先级排序

| 优先级 | 任务 | 预计工时 | 依赖 |
|--------|------|---------|------|
| P0 | 1.5 打包调整（桌面控制移入标准版） | 2h | 无 |
| P0 | 1.2 表情→动作映射（点头/摇头/皱眉） | 8h | 无 |
| P1 | 1.1 意图融合引擎（基础框架） | 16h | 无 |
| P1 | 1.4 信号总线（统一WebSocket协议） | 8h | 1.1 |
| P1 | 1.3 眼神追踪（虹膜位置→注视方向） | 12h | 无 |
| P2 | 2.1 协同工作总线 | 16h | 1.1, 1.4 |
| P2 | 2.2 人类活动检测器 | 8h | 无 |
| P2 | 2.4 AI操作回滚系统 | 12h | 无 |
| P2 | 2.3 AI后台任务执行器 | 16h | 2.1, 2.2 |
| P2 | 2.5 协同场景实现 | 24h | 2.1-2.4 |
| P3 | 3.2 桌面控制MCP Server | 12h | 无 |
| P3 | 3.1 MCP工具手势绑定 | 8h | 3.2 |
| P3 | 3.3 应用专属MCP Server | 24h | 3.2 |
| P3 | 3.4 技能市场UI | 16h | 3.1-3.3 |
| P3 | 3.5 A2A协议支持 | 16h | 3.2 |

---

## 六、最终愿景

**十三香小龙虾 v4.0 = 每个人的AI协同工作台**

```
人坐在电脑前
  → 摄像头看到人的手势、表情、眼神
  → 麦克风听到人的声音和情感
  → AI理解人的多模态意图
  → AI和人同时操作桌面，互不干扰
  → 人随时可以用手势接管或停止AI
  → 通过MCP连接无限工具生态
  → 数据全在本地，隐私安全
  → 免费，开源

不需要打字。不需要写提示词。不需要学习新技能。
对着电脑做出手势、说出想法，AI就在旁边一起干活。
```

---

> **本文档供新Agent参考，包含所有必要的代码位置、架构信息和开发任务。**
> **请从优先级P0的任务开始，逐步推进到P3。**
