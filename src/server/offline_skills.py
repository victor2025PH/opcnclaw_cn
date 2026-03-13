"""
Offline skills — pure Python implementations that run without network.

These provide instant responses for common queries when:
- Cloud AI is unreachable
- The query is a simple utility (no LLM needed)
- Ultra-low latency is desired
"""

import math
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple


_CALC_PATTERN = re.compile(
    r"^(?:计算|算一下|算|calculate|compute|eval)\s*[：:]?\s*(.+)",
    re.IGNORECASE,
)

_UNIT_CONVERSIONS = {
    ("km", "mi"): 0.621371, ("mi", "km"): 1.60934,
    ("kg", "lb"): 2.20462, ("lb", "kg"): 0.453592,
    ("cm", "in"): 0.393701, ("in", "cm"): 2.54,
    ("m", "ft"): 3.28084, ("ft", "m"): 0.3048,
    ("摄氏", "华氏"): None, ("华氏", "摄氏"): None,
    ("c", "f"): None, ("f", "c"): None,
    ("公里", "英里"): 0.621371, ("英里", "公里"): 1.60934,
    ("公斤", "磅"): 2.20462, ("磅", "公斤"): 0.453592,
    ("厘米", "英寸"): 0.393701, ("英寸", "厘米"): 2.54,
    ("米", "英尺"): 3.28084, ("英尺", "米"): 0.3048,
    ("升", "加仑"): 0.264172, ("加仑", "升"): 3.78541,
    ("l", "gal"): 0.264172, ("gal", "l"): 3.78541,
}

_UNIT_PATTERN = re.compile(
    r"(\d+\.?\d*)\s*(公里|英里|公斤|磅|厘米|英寸|米|英尺|升|加仑|摄氏|华氏|km|mi|kg|lb|cm|in|m|ft|l|gal|c|f)"
    r"\s*(?:转换?为?|换算?成?|等于多少|是多少|to|=)\s*"
    r"(公里|英里|公斤|磅|厘米|英寸|米|英尺|升|加仑|摄氏|华氏|km|mi|kg|lb|cm|in|m|ft|l|gal|c|f)",
    re.IGNORECASE,
)

_TIME_QUERIES = [
    "现在几点", "几点了", "什么时间", "当前时间", "现在时间",
    "今天几号", "今天日期", "今天星期几", "what time", "what day",
    "what date", "current time",
]

_DATE_CALC_PATTERN = re.compile(
    r"(\d+)\s*天(?:后|前|以后|以前)",
    re.IGNORECASE,
)

_TIMER_PATTERN = re.compile(
    r"(?:定时|提醒我?|计时|timer|remind)\s*(\d+)\s*(秒|分钟?|小时?|seconds?|minutes?|hours?)",
    re.IGNORECASE,
)

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def process(text: str) -> Optional[Tuple[str, str]]:
    """
    Try to handle the query with an offline skill.
    Returns (skill_name, result_text) or None.
    """
    text = text.strip()
    if not text:
        return None

    result = _try_time_query(text)
    if result:
        return result

    result = _try_calculator(text)
    if result:
        return result

    result = _try_unit_conversion(text)
    if result:
        return result

    result = _try_date_calc(text)
    if result:
        return result

    result = _try_timer(text)
    if result:
        return result

    return None


def _try_time_query(text: str) -> Optional[Tuple[str, str]]:
    lower = text.lower()
    if any(q in lower for q in _TIME_QUERIES):
        now = datetime.now()
        weekday = _WEEKDAYS[now.weekday()]
        return ("时间查询", f"现在是 {now.strftime('%Y年%m月%d日')} {weekday} {now.strftime('%H:%M:%S')}")
    return None


def _try_calculator(text: str) -> Optional[Tuple[str, str]]:
    m = _CALC_PATTERN.match(text)
    if not m:
        if re.match(r"^[\d\s\+\-\*\/\(\)\.\%\^]+$", text.strip()):
            expr = text.strip()
        else:
            return None
    else:
        expr = m.group(1).strip()

    expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**").replace("，", "")

    safe_chars = set("0123456789+-*/().% ")
    if not all(c in safe_chars or c == '*' for c in expr):
        if "sqrt" in expr or "sin" in expr or "cos" in expr or "log" in expr or "pi" in expr:
            return _try_math_calc(expr)
        return None

    try:
        result = eval(expr, {"__builtins__": {}}, {})
        if isinstance(result, float):
            result = round(result, 10)
            if result == int(result):
                result = int(result)
        return ("计算器", f"{expr} = {result}")
    except Exception:
        return None


def _try_math_calc(expr: str) -> Optional[Tuple[str, str]]:
    safe_names = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
        "tan": math.tan, "log": math.log, "log10": math.log10,
        "pi": math.pi, "e": math.e, "abs": abs, "pow": pow,
        "ceil": math.ceil, "floor": math.floor, "round": round,
    }
    try:
        result = eval(expr, {"__builtins__": {}}, safe_names)
        if isinstance(result, float):
            result = round(result, 10)
        return ("科学计算", f"{expr} = {result}")
    except Exception:
        return None


def _try_unit_conversion(text: str) -> Optional[Tuple[str, str]]:
    m = _UNIT_PATTERN.search(text)
    if not m:
        return None
    value = float(m.group(1))
    from_unit = m.group(2).lower()
    to_unit = m.group(3).lower()

    key = (from_unit, to_unit)
    factor = _UNIT_CONVERSIONS.get(key)

    if factor is None and key in _UNIT_CONVERSIONS:
        if from_unit in ("摄氏", "c"):
            converted = value * 9 / 5 + 32
            return ("单位换算", f"{value}°C = {round(converted, 2)}°F")
        elif from_unit in ("华氏", "f"):
            converted = (value - 32) * 5 / 9
            return ("单位换算", f"{value}°F = {round(converted, 2)}°C")
    elif factor:
        converted = value * factor
        return ("单位换算", f"{value} {m.group(2)} = {round(converted, 4)} {m.group(3)}")

    return None


def _try_date_calc(text: str) -> Optional[Tuple[str, str]]:
    m = _DATE_CALC_PATTERN.search(text)
    if not m:
        return None
    days = int(m.group(1))
    if "前" in text or "以前" in text:
        target = datetime.now() - timedelta(days=days)
        direction = "前"
    else:
        target = datetime.now() + timedelta(days=days)
        direction = "后"
    weekday = _WEEKDAYS[target.weekday()]
    return ("日期计算", f"{days}天{direction}是 {target.strftime('%Y年%m月%d日')} {weekday}")


def _try_timer(text: str) -> Optional[Tuple[str, str]]:
    m = _TIMER_PATTERN.search(text)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()

    if unit in ("秒", "second", "seconds"):
        seconds = amount
        unit_zh = "秒"
    elif unit in ("分", "分钟", "minute", "minutes"):
        seconds = amount * 60
        unit_zh = "分钟"
    elif unit in ("小时", "hour", "hours"):
        seconds = amount * 3600
        unit_zh = "小时"
    else:
        return None

    target = datetime.now() + timedelta(seconds=seconds)
    return ("定时器", f"已设定 {amount}{unit_zh} 定时，到期时间 {target.strftime('%H:%M:%S')}。"
            f"\n[timer:{seconds}]")
