# -*- coding: utf-8 -*-
"""
20 个内置工作流场景

每个场景是一个 Workflow 模板，首次启动时自动写入数据库（category='builtin'）。
用户可以启用/禁用/编辑参数，但 ID 固定。
"""

from .models import NodeDef, Trigger, TriggerType, Workflow
from . import store

BUILTIN_SCENARIOS = [
    # ① 晨间例行
    Workflow(
        id="builtin_morning",
        name="晨间例行",
        description="每天早上播报天气、新闻和激励语",
        category="builtin",
        icon="🌅",
        tags=["日常", "早晨"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="07:30",
                        days=["mon", "tue", "wed", "thu", "fri"]),
        nodes=[
            NodeDef(id="time", type="system_info",
                    label="获取日期", params={"type": "all"}),
            NodeDef(id="weather", type="llm_generate",
                    label="天气播报",
                    params={"prompt": "今天是{{time.date}} {{time.weekday}}，请简短播报今天的天气情况和穿衣建议（2-3句话）。"}),
            NodeDef(id="news", type="llm_generate",
                    label="新闻简报",
                    params={"prompt": "请简述今天3条最重要的科技/AI新闻，每条一句话。"}),
            NodeDef(id="motivate", type="llm_generate",
                    label="激励语",
                    params={"prompt": "给一句简短有力的早安激励语。"}),
            NodeDef(id="combine", type="template",
                    label="合并播报",
                    params={"template": "早上好！今天是{{time.weekday}}。\n\n🌤 {{weather.output}}\n\n📰 新闻：\n{{news.output}}\n\n💪 {{motivate.output}}"}),
            NodeDef(id="speak", type="tts_speak",
                    label="语音播报", params={"text": "{{combine.output}}"}),
        ],
    ),

    # ② 专注模式
    Workflow(
        id="builtin_focus",
        name="专注模式",
        description="开启专注：微信自动回复「忙碌中」，定时提醒休息",
        category="builtin",
        icon="🎯",
        tags=["效率", "专注"],
        trigger=Trigger(type=TriggerType.MANUAL),
        variables={"focus_minutes": "25"},
        nodes=[
            NodeDef(id="calc_secs", type="python_eval",
                    label="分钟→秒", params={"expression": "int({{focus_minutes}}) * 60"}),
            NodeDef(id="start_reply", type="wechat_autoreply",
                    label="开启自动回复", params={"action": "start"}),
            NodeDef(id="notify_start", type="notify",
                    label="通知开始", params={"message": "🎯 专注模式已开启，时长 {{focus_minutes}} 分钟", "channel": "log"}),
            NodeDef(id="speak_start", type="tts_speak",
                    label="语音提示", params={"text": "专注模式已开启，{{focus_minutes}}分钟后提醒你休息。"}),
            NodeDef(id="wait", type="delay",
                    label="等待专注结束",
                    params={"seconds": "{{calc_secs.value}}"},
                    timeout=7200),
            NodeDef(id="speak_end", type="tts_speak",
                    label="结束提醒", params={"text": "专注时间到了，休息一下吧！站起来活动活动。"}),
            NodeDef(id="stop_reply", type="wechat_autoreply",
                    label="关闭自动回复", params={"action": "stop"}),
        ],
    ),

    # ③ 日报生成
    Workflow(
        id="builtin_daily_report",
        name="日报生成",
        description="下班前自动汇总今日工作内容生成日报",
        category="builtin",
        icon="📋",
        tags=["效率", "报告"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="17:30",
                        days=["mon", "tue", "wed", "thu", "fri"]),
        nodes=[
            NodeDef(id="time", type="system_info", label="日期", params={"type": "all"}),
            NodeDef(id="wx_msgs", type="wechat_read",
                    label="读取微信消息", params={}),
            NodeDef(id="report", type="llm_generate",
                    label="生成日报",
                    params={
                        "prompt": "今天是{{time.date}} {{time.weekday}}。\n\n微信消息摘要：{{wx_msgs.output}}\n\n请根据以上信息，生成一份简洁的工作日报，包含：1.今日完成事项 2.待跟进事项 3.明日计划。格式简洁。",
                        "system": "你是一个专业的日报撰写助手。"
                    }),
            NodeDef(id="save", type="file_write",
                    label="保存日报",
                    params={"path": "data/reports/daily_{{time.date}}.md", "content": "# 日报 {{time.date}}\n\n{{report.output}}"}),
            NodeDef(id="speak", type="tts_speak",
                    label="播报", params={"text": "日报已生成并保存。"}),
        ],
    ),

    # ④ 番茄工作法
    Workflow(
        id="builtin_pomodoro",
        name="番茄工作法",
        description="25分钟专注 + 5分钟休息循环",
        category="builtin",
        icon="🍅",
        tags=["效率", "番茄钟"],
        trigger=Trigger(type=TriggerType.MANUAL),
        nodes=[
            NodeDef(id="start", type="tts_speak",
                    label="开始", params={"text": "番茄钟开始，专注25分钟。"}),
            NodeDef(id="work", type="delay",
                    label="工作25分钟", params={"seconds": "1500"}, timeout=1800),
            NodeDef(id="break_notify", type="tts_speak",
                    label="休息提醒", params={"text": "辛苦了，休息5分钟吧！站起来活动一下。"}),
            NodeDef(id="rest", type="delay",
                    label="休息5分钟", params={"seconds": "300"}, timeout=600),
            NodeDef(id="done", type="tts_speak",
                    label="完成", params={"text": "休息结束，准备开始下一轮番茄钟。"}),
        ],
    ),

    # ⑤ 天气播报
    Workflow(
        id="builtin_weather",
        name="天气播报",
        description="语音播报当前天气和未来天气趋势",
        category="builtin",
        icon="🌤",
        tags=["日常", "天气"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="08:00"),
        nodes=[
            NodeDef(id="weather", type="llm_generate",
                    label="天气预报",
                    params={"prompt": "请简短播报今天和明天的天气预报，包含温度、天气状况和穿衣建议。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="朗读", params={"text": "{{weather.output}}"}),
        ],
    ),

    # ⑥ 新闻早报
    Workflow(
        id="builtin_news",
        name="新闻早报",
        description="每日AI/科技新闻简报",
        category="builtin",
        icon="📰",
        tags=["日常", "新闻"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="08:30"),
        nodes=[
            NodeDef(id="news", type="llm_generate",
                    label="新闻",
                    params={"prompt": "请用简洁的语言播报今天5条最重要的科技和AI新闻，每条1-2句话。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="朗读", params={"text": "早安，今日科技新闻简报：\n{{news.output}}"}),
        ],
    ),

    # ⑦ 健康提醒
    Workflow(
        id="builtin_health",
        name="健康提醒",
        description="每小时提醒喝水、活动、护眼",
        category="builtin",
        icon="💚",
        tags=["健康", "提醒"],
        trigger=Trigger(type=TriggerType.INTERVAL, seconds=3600),
        nodes=[
            NodeDef(id="time", type="system_info", label="时间", params={"type": "time"}),
            NodeDef(id="tip", type="llm_generate",
                    label="健康贴士",
                    params={"prompt": "现在是{{time.output}}，给一句简短的健康提醒（喝水/站起来活动/看看远处让眼睛休息，随机选一个），不超过15个字。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="提醒", params={"text": "{{tip.output}}"}),
        ],
    ),

    # ⑧ 下班例行
    Workflow(
        id="builtin_evening",
        name="下班例行",
        description="下班时总结今日并规划明天",
        category="builtin",
        icon="🌙",
        tags=["日常", "晚间"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="18:00",
                        days=["mon", "tue", "wed", "thu", "fri"]),
        nodes=[
            NodeDef(id="summary", type="llm_generate",
                    label="总结",
                    params={"prompt": "作为工作助手，请生成一段简短的下班语音：1.鼓励今天的工作 2.提醒明天重要事项 3.祝晚间愉快。控制在50字内。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="播报", params={"text": "{{summary.output}}"}),
        ],
    ),

    # ⑨ 周报生成
    Workflow(
        id="builtin_weekly_report",
        name="周报生成",
        description="每周五自动汇总生成周报",
        category="builtin",
        icon="📊",
        tags=["效率", "报告"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="16:00", days=["fri"]),
        nodes=[
            NodeDef(id="time", type="system_info", label="日期", params={"type": "date"}),
            NodeDef(id="report", type="llm_generate",
                    label="周报",
                    params={
                        "prompt": "今天是{{time.output}}（周五），请生成本周工作周报模板，包含：\n1. 本周重点工作\n2. 完成情况\n3. 遇到的问题\n4. 下周计划\n\n请用简洁的 Markdown 格式。",
                        "system": "你是一个周报撰写助手。"
                    }),
            NodeDef(id="save", type="file_write",
                    label="保存",
                    params={"path": "data/reports/weekly_{{time.output}}.md", "content": "{{report.output}}"}),
            NodeDef(id="notify", type="tts_speak",
                    label="提醒", params={"text": "周报模板已生成，请检查并补充细节。"}),
        ],
    ),

    # ⑩ 微信日报
    Workflow(
        id="builtin_wechat_digest",
        name="微信消息日报",
        description="汇总今日微信未读消息并生成摘要",
        category="builtin",
        icon="💬",
        tags=["微信", "摘要"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="20:00"),
        nodes=[
            NodeDef(id="msgs", type="wechat_read", label="读取消息", params={}),
            NodeDef(id="digest", type="llm_generate",
                    label="摘要",
                    params={"prompt": "以下是今天的微信消息记录：\n{{msgs.output}}\n\n请生成一份消息摘要，列出重要对话和待回复事项。"}),
            NodeDef(id="save", type="file_write",
                    label="保存",
                    params={"path": "data/reports/wechat_digest.md", "content": "{{digest.output}}", "mode": "a"}),
            NodeDef(id="speak", type="tts_speak",
                    label="播报", params={"text": "微信消息日报已整理完毕。{{digest.output}}"}),
        ],
    ),

    # ⑪ 微信定时消息
    Workflow(
        id="builtin_wechat_scheduled",
        name="微信定时消息",
        description="在指定时间给指定联系人发送消息",
        category="builtin",
        icon="⏰",
        tags=["微信", "定时"],
        trigger=Trigger(type=TriggerType.MANUAL),
        variables={"contact": "文件传输助手", "message": "这是一条定时消息"},
        nodes=[
            NodeDef(id="send", type="wechat_send",
                    label="发送", params={"contact": "{{contact}}", "message": "{{message}}"}),
            NodeDef(id="log", type="notify",
                    label="记录", params={"message": "已向 {{contact}} 发送定时消息", "channel": "log"}),
        ],
    ),

    # ⑫ 学习复习
    Workflow(
        id="builtin_study_review",
        name="学习复习提醒",
        description="定时提醒复习知识点",
        category="builtin",
        icon="📚",
        tags=["学习", "提醒"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="21:00"),
        nodes=[
            NodeDef(id="quiz", type="llm_generate",
                    label="生成问题",
                    params={"prompt": "请生成3个关于编程或AI的思考题，帮助复习。每题一行，简短有趣。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="朗读", params={"text": "复习时间到了！今天的思考题：\n{{quiz.output}}"}),
        ],
    ),

    # ⑬ 社交提醒
    Workflow(
        id="builtin_social",
        name="社交关怀提醒",
        description="提醒联系重要的人",
        category="builtin",
        icon="👋",
        tags=["社交", "提醒"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="10:00", days=["sat"]),
        nodes=[
            NodeDef(id="remind", type="llm_generate",
                    label="生成提醒",
                    params={"prompt": "今天是周末，请生成一条温馨的社交提醒，建议联系一下家人或朋友，简短温暖。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="朗读", params={"text": "{{remind.output}}"}),
        ],
    ),

    # ⑭ 系统巡检
    Workflow(
        id="builtin_system_check",
        name="系统巡检",
        description="检查系统状态并报告异常",
        category="builtin",
        icon="🖥️",
        tags=["系统", "监控"],
        trigger=Trigger(type=TriggerType.INTERVAL, seconds=7200),
        nodes=[
            NodeDef(id="info", type="python_eval",
                    label="系统信息",
                    params={"expression": "str({'cpu': '检查中', 'memory': '检查中', 'disk': '检查中'})"}),
            NodeDef(id="check", type="llm_generate",
                    label="分析",
                    params={"prompt": "系统信息: {{info.output}}\n\n请简短报告系统状态是否正常。如有异常请标注。"}),
            NodeDef(id="log", type="notify",
                    label="记录", params={"message": "系统巡检: {{check.output}}", "channel": "log"}),
        ],
    ),

    # ⑮ 语音日记
    Workflow(
        id="builtin_voice_diary",
        name="语音日记",
        description="睡前记录今天的感想并存档",
        category="builtin",
        icon="📓",
        tags=["日常", "日记"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="22:00"),
        nodes=[
            NodeDef(id="time", type="system_info", label="日期", params={"type": "all"}),
            NodeDef(id="prompt_speak", type="tts_speak",
                    label="引导", params={"text": "晚上好，来记录今天的想法吧。今天过得怎么样？"}),
            NodeDef(id="diary", type="llm_generate",
                    label="日记模板",
                    params={"prompt": "今天是{{time.date}} {{time.weekday}}，请生成一段简短的日记引导，帮助用户回忆今天做了什么、有什么感受、明天的期待。用温暖的语气，不超过100字。"}),
            NodeDef(id="save", type="file_write",
                    label="保存",
                    params={"path": "data/diary/{{time.date}}.md", "content": "# {{time.date}} 日记\n\n{{diary.output}}\n\n---\n*（待补充个人记录）*\n"}),
        ],
    ),

    # ⑯ 待办回顾
    Workflow(
        id="builtin_todo_review",
        name="待办回顾",
        description="每天中午回顾和整理待办事项",
        category="builtin",
        icon="✅",
        tags=["效率", "待办"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="12:00"),
        nodes=[
            NodeDef(id="review", type="llm_generate",
                    label="回顾",
                    params={"prompt": "作为效率助手，请给出一段简短的午间待办回顾提醒，鼓励用户检查上午完成情况并调整下午计划。不超过50字。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="朗读", params={"text": "{{review.output}}"}),
        ],
    ),

    # ⑰ 阅读摘要
    Workflow(
        id="builtin_reading",
        name="阅读摘要",
        description="对指定文本生成阅读摘要",
        category="builtin",
        icon="📖",
        tags=["学习", "摘要"],
        trigger=Trigger(type=TriggerType.MANUAL),
        variables={"file_path": "data/reading/input.txt"},
        nodes=[
            NodeDef(id="read", type="file_read",
                    label="读取文件", params={"path": "{{file_path}}", "max_chars": "8000"}),
            NodeDef(id="summary", type="llm_generate",
                    label="生成摘要",
                    params={"prompt": "请为以下文本生成一份结构化的阅读摘要，包含：核心观点、关键细节、个人启发。\n\n{{read.output}}"}),
            NodeDef(id="save", type="file_write",
                    label="保存", params={"path": "data/reading/summary.md", "content": "{{summary.output}}", "mode": "a"}),
            NodeDef(id="speak", type="tts_speak",
                    label="朗读摘要", params={"text": "摘要已生成。{{summary.output}}"}),
        ],
    ),

    # ⑱ 自定义通知流水线
    Workflow(
        id="builtin_custom_notify",
        name="自定义通知",
        description="定时发送自定义通知到微信/语音/日志",
        category="builtin",
        icon="🔔",
        tags=["通知", "自定义"],
        trigger=Trigger(type=TriggerType.MANUAL),
        variables={"notify_message": "这是一条自定义通知", "notify_channel": "log"},
        nodes=[
            NodeDef(id="send", type="notify",
                    label="发送通知",
                    params={"message": "{{notify_message}}", "channel": "{{notify_channel}}"}),
        ],
    ),

    # ⑲ 睡前例行
    Workflow(
        id="builtin_bedtime",
        name="睡前例行",
        description="睡前准备：明日提醒 + 放松引导",
        category="builtin",
        icon="🌜",
        tags=["日常", "睡前"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="23:00"),
        nodes=[
            NodeDef(id="prep", type="llm_generate",
                    label="睡前引导",
                    params={"prompt": "现在是深夜，请生成一段简短的睡前引导：1.提醒早点休息 2.明天是新的一天 3.一句放松的话。不超过50字，语气温柔。"}),
            NodeDef(id="speak", type="tts_speak",
                    label="朗读", params={"text": "{{prep.output}}"}),
            NodeDef(id="autoreply_on", type="wechat_autoreply",
                    label="开启免打扰", params={"action": "start"}),
        ],
    ),

    # ⑳ 会议准备
    Workflow(
        id="builtin_meeting_prep",
        name="会议准备",
        description="会议前自动准备议程和要点",
        category="builtin",
        icon="📅",
        tags=["效率", "会议"],
        trigger=Trigger(type=TriggerType.MANUAL),
        variables={"meeting_topic": "项目进度同步", "participants": "团队成员"},
        nodes=[
            NodeDef(id="agenda", type="llm_generate",
                    label="生成议程",
                    params={
                        "prompt": "会议主题：{{meeting_topic}}\n参与者：{{participants}}\n\n请生成一份简洁的会议议程，包含3-5个讨论要点和预估时间。",
                        "system": "你是一个专业的会议助手。"
                    }),
            NodeDef(id="save", type="file_write",
                    label="保存议程",
                    params={"path": "data/meetings/agenda.md", "content": "# {{meeting_topic}}\n\n{{agenda.output}}"}),
            NodeDef(id="speak", type="tts_speak",
                    label="播报", params={"text": "会议议程已准备好。{{agenda.output}}"}),
        ],
    ),

    # ── 朋友圈场景 ────────────────────────────────────────────────────────────────

    # ㉑ 朋友圈智能互动
    Workflow(
        id="builtin_moments_interact",
        name="朋友圈智能互动",
        description="浏览朋友圈，AI 分析每条动态并自动点赞/评论",
        category="builtin",
        icon="👀",
        tags=["朋友圈", "社交"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="12:30"),
        nodes=[
            NodeDef(id="browse", type="wechat_browse_moments",
                    label="浏览并互动",
                    params={"max_posts": "8", "auto_interact": True},
                    timeout=300),
            NodeDef(id="report", type="template",
                    label="汇总",
                    params={"template": "朋友圈互动完成：{{browse.output}}"}),
            NodeDef(id="log", type="notify",
                    label="记录", params={"message": "{{report.output}}", "channel": "log"}),
        ],
    ),

    # ㉒ 朋友圈情报日报
    Workflow(
        id="builtin_moments_digest",
        name="朋友圈情报日报",
        description="浏览朋友圈并生成今日互动摘要报告",
        category="builtin",
        icon="📊",
        tags=["朋友圈", "情报"],
        trigger=Trigger(type=TriggerType.SCHEDULE, time="21:00"),
        nodes=[
            NodeDef(id="browse", type="wechat_browse_moments",
                    label="浏览朋友圈",
                    params={"max_posts": "15", "auto_interact": False},
                    timeout=300),
            NodeDef(id="digest", type="llm_generate",
                    label="生成摘要",
                    params={
                        "prompt": "以下是今天浏览的朋友圈动态：\n\n{{browse.output}}\n\n请生成一份简洁的朋友圈日报，包括：\n1. 重要动态摘要\n2. 需要关注的联系人\n3. 建议互动的内容\n\n用简洁的中文。",
                        "system": "你是一个社交情报分析助手。"
                    }),
            NodeDef(id="save", type="file_write",
                    label="保存日报",
                    params={"path": "data/reports/moments_digest.md", "content": "# 朋友圈日报\n\n{{digest.output}}", "mode": "a"}),
            NodeDef(id="speak", type="tts_speak",
                    label="播报", params={"text": "朋友圈日报已生成。{{digest.output}}"}),
        ],
    ),

    # ㉓ AI 定时发圈
    Workflow(
        id="builtin_moments_publish",
        name="AI 定时发圈",
        description="AI 根据主题自动生成文案并发布朋友圈",
        category="builtin",
        icon="📢",
        tags=["朋友圈", "发布"],
        trigger=Trigger(type=TriggerType.MANUAL),
        variables={"topic": "分享一个有趣的想法", "mood": "轻松"},
        nodes=[
            NodeDef(id="publish", type="wechat_publish_moment",
                    label="AI生成并发布",
                    params={
                        "generate": True,
                        "topic": "{{topic}}",
                        "mood": "{{mood}}",
                        "style": "日常",
                    },
                    timeout=120),
            NodeDef(id="log", type="notify",
                    label="记录",
                    params={"message": "朋友圈已发布: {{publish.text}}", "channel": "log"}),
        ],
    ),
]


def ensure_builtins():
    """确保所有内置场景已写入数据库（不覆盖用户修改）"""
    existing = {w.id for w in store.list_workflows(category="builtin")}
    count = 0
    for wf in BUILTIN_SCENARIOS:
        if wf.id not in existing:
            store.save_workflow(wf)
            count += 1
    if count:
        from loguru import logger
        logger.info(f"已注册 {count} 个内置工作流场景")
