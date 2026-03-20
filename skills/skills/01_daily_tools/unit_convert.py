"""单位换算技能"""

LENGTH_TO_METER = {
    "m": 1, "meter": 1, "meters": 1, "米": 1,
    "cm": 0.01, "centimeter": 0.01, "厘米": 0.01,
    "mm": 0.001, "millimeter": 0.001, "毫米": 0.001,
    "km": 1000, "kilometer": 1000, "公里": 1000, "千米": 1000,
    "inch": 0.0254, "in": 0.0254, "英寸": 0.0254,
    "foot": 0.3048, "ft": 0.3048, "英尺": 0.3048,
    "yard": 0.9144, "yd": 0.9144, "码": 0.9144,
    "mile": 1609.344, "mi": 1609.344, "英里": 1609.344,
    "nautical_mile": 1852, "海里": 1852, "节": 1852,
    "光年": 9.461e15,
}
LENGTH_UNITS_ZH = {
    "m": "米", "cm": "厘米", "mm": "毫米", "km": "公里",
    "inch": "英寸", "foot": "英尺", "mile": "英里", "nautical_mile": "海里",
}

WEIGHT_TO_GRAM = {
    "g": 1, "gram": 1, "克": 1,
    "kg": 1000, "kilogram": 1000, "千克": 1000, "公斤": 1000,
    "mg": 0.001, "milligram": 0.001, "毫克": 0.001,
    "t": 1000000, "ton": 1000000, "吨": 1000000,
    "lb": 453.592, "pound": 453.592, "磅": 453.592,
    "oz": 28.3495, "ounce": 28.3495, "盎司": 28.3495,
    "斤": 500, "jin": 500,
    "两": 50, "liang": 50,
    "钱": 5, "qian": 5,
    "担": 50000,
    "grain": 0.0648,
}


def convert_length(value: float = 1, from_unit: str = "inch", to_unit: str = "cm", **kwargs) -> dict:
    """长度单位换算"""
    from_key = _normalize_unit(from_unit, LENGTH_TO_METER)
    to_key = _normalize_unit(to_unit, LENGTH_TO_METER)

    if from_key is None:
        return {"error": f"不认识单位: {from_unit}"}
    if to_key is None:
        return {"error": f"不认识单位: {to_unit}"}

    in_meters = value * LENGTH_TO_METER[from_key]
    result = in_meters / LENGTH_TO_METER[to_key]

    return {
        "from": f"{value} {from_unit}",
        "to": f"{result:.6g} {to_unit}",
        "value": value,
        "result": result,
        "from_unit": from_unit,
        "to_unit": to_unit,
    }


def convert_weight(value: float = 1, from_unit: str = "lb", to_unit: str = "kg", **kwargs) -> dict:
    """重量单位换算"""
    from_key = _normalize_unit(from_unit, WEIGHT_TO_GRAM)
    to_key = _normalize_unit(to_unit, WEIGHT_TO_GRAM)

    if from_key is None:
        # 默认换算到常用单位
        results = {}
        for unit, factor in [("kg", 1000), ("斤", 500), ("g", 1), ("lb", 453.592)]:
            from_k = _normalize_unit(from_unit, WEIGHT_TO_GRAM)
            if from_k:
                in_grams = value * WEIGHT_TO_GRAM[from_k]
                results[unit] = in_grams / factor
        return {"error": f"不认识单位: {from_unit}"}

    in_grams = value * WEIGHT_TO_GRAM[from_key]

    # 如果没指定目标，转换到常用几个
    if to_unit in ("", "常用", "all"):
        return {
            "from": f"{value} {from_unit}",
            "kg": round(in_grams / 1000, 4),
            "斤": round(in_grams / 500, 4),
            "g": round(in_grams, 4),
            "磅": round(in_grams / 453.592, 4),
            "盎司": round(in_grams / 28.3495, 4),
        }

    result = in_grams / WEIGHT_TO_GRAM.get(to_key or to_unit, 1)
    return {
        "from": f"{value} {from_unit}",
        "to": f"{result:.6g} {to_unit}",
        "value": value,
        "result": result,
    }


def convert_temp(value: float = 0, from_unit: str = "°C", to_unit: str = "", **kwargs) -> dict:
    """温度换算"""
    fu = from_unit.upper().replace("度", "").replace("摄氏", "C").replace("华氏", "F").replace("开尔文", "K")
    if "C" in fu:
        celsius = value
    elif "F" in fu:
        celsius = (value - 32) * 5 / 9
    elif "K" in fu:
        celsius = value - 273.15
    else:
        return {"error": f"不认识温度单位: {from_unit}"}

    return {
        "input": f"{value} {from_unit}",
        "celsius": round(celsius, 2),
        "fahrenheit": round(celsius * 9 / 5 + 32, 2),
        "kelvin": round(celsius + 273.15, 2),
        "摄氏度": round(celsius, 2),
        "华氏度": round(celsius * 9 / 5 + 32, 2),
        "开尔文": round(celsius + 273.15, 2),
    }


def _normalize_unit(unit: str, table: dict) -> str:
    u = unit.lower().strip()
    if u in table:
        return u
    # 模糊匹配
    for key in table:
        if u in key or key in u:
            return key
    return None
