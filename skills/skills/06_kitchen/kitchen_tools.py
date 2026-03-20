"""厨房单位换算（Code技能）"""

KITCHEN_UNITS = {
    "汤匙": {"ml": 15, "g_water": 15},
    "大勺": {"ml": 15, "g_water": 15},
    "tbsp": {"ml": 15, "g_water": 15},
    "tablespoon": {"ml": 15, "g_water": 15},
    "茶匙": {"ml": 5, "g_water": 5},
    "小勺": {"ml": 5, "g_water": 5},
    "tsp": {"ml": 5, "g_water": 5},
    "teaspoon": {"ml": 5, "g_water": 5},
    "杯": {"ml": 240, "g_water": 240},
    "cup": {"ml": 240, "g_water": 240},
}

FOOD_DENSITY = {
    "面粉": 0.55, "白糖": 0.85, "盐": 1.20, "酱油": 1.15,
    "食用油": 0.92, "蜂蜜": 1.42, "牛奶": 1.03, "淀粉": 0.75,
    "可可粉": 0.50, "泡打粉": 0.90,
}


def kitchen_convert(value: float = 1, from_unit: str = "汤匙", ingredient: str = "", **kwargs) -> dict:
    unit_data = KITCHEN_UNITS.get(from_unit.lower(), KITCHEN_UNITS.get("汤匙"))
    ml_total = float(value) * unit_data["ml"]
    g_water = float(value) * unit_data["g_water"]

    results = {"单位": from_unit, "数量": value, "毫升": round(ml_total, 1), "克（水）": round(g_water, 1)}

    # 特定食材密度
    for food, density in FOOD_DENSITY.items():
        if food in ingredient:
            results[f"克（{food}）"] = round(ml_total * density, 1)

    return {
        **results,
        "summary": f"{value} {from_unit} ≈ {ml_total:.0f} ml ≈ {g_water:.0f}g（水）",
    }
