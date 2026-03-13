# OpenClaw 技能开发指南 (Skill SDK)

## 概述

OpenClaw 技能系统允许开发者为 AI 助手扩展新能力。技能以 Python 模块形式存在于 `skills/` 目录下。

## 快速开始

### 1. 创建技能文件

```python
# skills/my_weather/skill.py
"""查询天气的技能"""

SKILL_META = {
    "id": "my_weather",
    "name": "天气查询",
    "description": "查询指定城市的天气",
    "version": "1.0.0",
    "author": "Your Name",
    "triggers": ["天气", "weather", "气温", "下雨"],
    "confidence_threshold": 0.6,
}

async def execute(query: str, context: dict = None) -> str:
    """
    技能入口函数。

    Args:
        query: 用户的原始输入文本
        context: 上下文信息 {"session_id": str, "user_id": str, ...}

    Returns:
        技能执行结果文本
    """
    city = extract_city(query)
    weather = await fetch_weather(city)
    return f"{city}今天{weather['condition']}，温度{weather['temp']}°C"
```

### 2. 技能元数据 (SKILL_META)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | str | 是 | 唯一标识符，建议用 snake_case |
| `name` | str | 是 | 显示名称 |
| `description` | str | 是 | 一句话描述 |
| `version` | str | 是 | 语义化版本号 |
| `author` | str | 否 | 作者名 |
| `triggers` | list[str] | 是 | 触发关键词列表 |
| `confidence_threshold` | float | 否 | 匹配阈值 (0-1, 默认 0.5) |
| `requires` | list[str] | 否 | 依赖的 pip 包 |
| `category` | str | 否 | 分类: "utility", "info", "fun", "productivity" |

### 3. 执行函数签名

```python
async def execute(query: str, context: dict = None) -> str:
```

- `query`: 用户原始文本
- `context`: 可选上下文
  - `session_id`: 当前会话 ID
  - `user_id`: 用户标识
  - `platform`: 来源平台 ("web", "wechat", "siri")
- 返回值: 纯文本字符串

### 4. 触发匹配

技能引擎按以下顺序匹配：
1. 精确关键词命中 (`triggers` 列表)
2. Jieba 分词 + TF-IDF 相似度
3. 置信度超过 `confidence_threshold` 时执行

## 高级功能

### MCP 工具集成

技能可以暴露为 MCP (Model Context Protocol) 工具，供 AI 模型直接调用：

```python
SKILL_META = {
    # ...
    "mcp_tool": {
        "name": "get_weather",
        "description": "Get weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"}
            },
            "required": ["city"]
        }
    }
}
```

### 异步 HTTP 调用

```python
import httpx

async def execute(query: str, context: dict = None) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.example.com/data")
        return resp.json()["result"]
```

### 访问持久化存储

```python
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
```

## API 接口

### 列出所有技能

```
GET /api/skills
```

### 手动调用技能

```
POST /api/skills/{skill_id}/execute
Content-Type: application/json

{"query": "北京天气"}
```

### 安装/卸载技能

```
POST /api/skills/install
{"url": "https://github.com/user/skill-weather.git"}

DELETE /api/skills/{skill_id}
```

## 发布技能

1. 创建 GitHub 仓库，包含 `skill.py` 和可选 `requirements.txt`
2. 在仓库根目录添加 `skill.json` (内容同 SKILL_META)
3. 提交 PR 到 OpenClaw Skills Registry

## 示例技能

参考 `skills/` 目录下的内置技能实现。
