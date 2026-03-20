"""时间日期相关技能"""
import re
from datetime import datetime, timedelta, date


def get_current_time(**kwargs) -> dict:
    now = datetime.now()
    weekdays = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
    lunar = _get_lunar_simple(now.date())
    return {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y年%m月%d日"),
        "time": now.strftime("%H:%M"),
        "weekday": weekdays[now.weekday()],
        "lunar_date": lunar,
        "timestamp": int(now.timestamp()),
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
    }


def countdown_days(event: str = "", **kwargs) -> dict:
    """计算距离目标日期/节日还有多少天"""
    today = date.today()

    FIXED_EVENTS = {
        "春节": _next_spring_festival,
        "元旦": lambda: date(today.year + (1 if today >= date(today.year, 1, 1) else 0), 1, 1),
        "五一": lambda: _next_date(5, 1),
        "劳动节": lambda: _next_date(5, 1),
        "国庆": lambda: _next_date(10, 1),
        "国庆节": lambda: _next_date(10, 1),
        "中秋": _next_mid_autumn,
        "圣诞": lambda: _next_date(12, 25),
        "情人节": lambda: _next_date(2, 14),
        "儿童节": lambda: _next_date(6, 1),
        "教师节": lambda: _next_date(9, 10),
        "高考": lambda: _next_date(6, 7),
        "元宵节": _next_lantern,
    }

    target = None
    event_name = event.strip() or "未指定"

    # 尝试固定节日
    for key, fn in FIXED_EVENTS.items():
        if key in event:
            target = fn()
            event_name = key
            break

    # 尝试解析日期格式
    if target is None:
        m = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', event)
        if m:
            target = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        else:
            m = re.search(r'(\d{1,2})[月](\d{1,2})[日号]', event)
            if m:
                mo, dy = int(m.group(1)), int(m.group(2))
                target = date(today.year, mo, dy)
                if target <= today:
                    target = date(today.year + 1, mo, dy)

    if target is None:
        return {"error": f"无法识别日期或节日：{event}，请说得更具体些"}

    days = (target - today).days
    return {
        "event": event_name,
        "target_date": target.strftime("%Y年%m月%d日"),
        "days_remaining": days,
        "message": f"距离{event_name}还有 {days} 天" if days > 0 else
                   (f"今天就是{event_name}！" if days == 0 else f"{event_name}已过去 {-days} 天"),
    }


def get_lunar(**kwargs) -> dict:
    now = datetime.now()
    lunar = _get_lunar_simple(now.date())
    jieqi = _get_jieqi(now.date())
    return {
        "solar_date": now.strftime("%Y年%m月%d日"),
        "lunar_date": lunar,
        "jieqi": jieqi,
        "message": f"今天是 {now.strftime('%Y年%m月%d日')}，农历{lunar}{'，' + jieqi if jieqi else ''}",
    }


# ── 内部辅助 ──────────────────────────────────────────

def _get_lunar_simple(d: date) -> str:
    """简化版农历（仅供显示，非精确天文计算）"""
    # 使用一个固定参考点做粗略换算
    # 实际项目中应引入 lunarcalendar 库
    try:
        from lunarcalendar import Converter, Solar
        solar = Solar(d.year, d.month, d.day)
        lunar = Converter.Solar2Lunar(solar)
        months = ["正","二","三","四","五","六","七","八","九","十","冬","腊"]
        days = ["初一","初二","初三","初四","初五","初六","初七","初八","初九","初十",
                "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十",
                "廿一","廿二","廿三","廿四","廿五","廿六","廿七","廿八","廿九","三十"]
        prefix = "闰" if lunar.isleap else ""
        return f"{prefix}{months[lunar.month-1]}月{days[lunar.day-1]}"
    except Exception:
        return "（农历需要 lunarcalendar 库）"


def _get_jieqi(d: date) -> str:
    JIEQI_APPROX = {
        (1, 6): "小寒", (1, 20): "大寒",
        (2, 4): "立春", (2, 19): "雨水",
        (3, 6): "惊蛰", (3, 21): "春分",
        (4, 5): "清明", (4, 20): "谷雨",
        (5, 6): "立夏", (5, 21): "小满",
        (6, 6): "芒种", (6, 21): "夏至",
        (7, 7): "小暑", (7, 23): "大暑",
        (8, 7): "立秋", (8, 23): "处暑",
        (9, 8): "白露", (9, 23): "秋分",
        (10, 8): "寒露", (10, 23): "霜降",
        (11, 7): "立冬", (11, 22): "小雪",
        (12, 7): "大雪", (12, 22): "冬至",
    }
    for (m, day_approx), name in JIEQI_APPROX.items():
        if d.month == m and abs(d.day - day_approx) <= 1:
            return name
    return ""


def _next_date(month: int, day: int) -> date:
    today = date.today()
    target = date(today.year, month, day)
    if target <= today:
        target = date(today.year + 1, month, day)
    return target


def _next_spring_festival() -> date:
    today = date.today()
    SPRING_FESTIVALS = {
        2024: date(2024, 2, 10), 2025: date(2025, 1, 29),
        2026: date(2026, 2, 17), 2027: date(2027, 2, 6),
    }
    for year in sorted(SPRING_FESTIVALS):
        d = SPRING_FESTIVALS[year]
        if d > today:
            return d
    return date(today.year + 1, 2, 1)


def _next_mid_autumn() -> date:
    today = date.today()
    MID_AUTUMN = {
        2024: date(2024, 9, 17), 2025: date(2025, 10, 6),
        2026: date(2026, 9, 25), 2027: date(2027, 9, 15),
    }
    for year in sorted(MID_AUTUMN):
        d = MID_AUTUMN[year]
        if d > today:
            return d
    return date(today.year + 1, 9, 15)


def _next_lantern() -> date:
    today = date.today()
    LANTERN = {
        2024: date(2024, 2, 24), 2025: date(2025, 2, 12),
        2026: date(2026, 3, 3), 2027: date(2027, 2, 20),
    }
    for year in sorted(LANTERN):
        d = LANTERN[year]
        if d > today:
            return d
    return date(today.year + 1, 2, 15)
