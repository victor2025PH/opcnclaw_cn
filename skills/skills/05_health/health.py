"""健康计算技能（Code类型）"""


def calc_bmi(weight: float = 60, height: float = 170, **kwargs) -> dict:
    """BMI 计算"""
    h_m = float(height) / 100
    bmi = float(weight) / (h_m ** 2)

    if bmi < 18.5:
        category = "偏轻"
        advice = "建议适当增加营养摄入，多吃高蛋白食物"
        color = "blue"
    elif bmi < 24:
        category = "正常"
        advice = "体重指数正常，继续保持健康生活方式"
        color = "green"
    elif bmi < 28:
        category = "超重"
        advice = "建议控制饮食热量，增加有氧运动"
        color = "yellow"
    elif bmi < 32:
        category = "肥胖"
        advice = "建议咨询营养师制定减重计划，加强运动"
        color = "orange"
    else:
        category = "重度肥胖"
        advice = "建议就医进行专业干预，优先改善生活方式"
        color = "red"

    # 理想体重范围
    ideal_low = round(18.5 * h_m ** 2, 1)
    ideal_high = round(23.9 * h_m ** 2, 1)

    return {
        "bmi": round(bmi, 1),
        "category": category,
        "advice": advice,
        "weight_kg": weight,
        "height_cm": height,
        "ideal_weight_range": f"{ideal_low}~{ideal_high} kg",
        "summary": (
            f"你的BMI是 {bmi:.1f}，属于【{category}】。"
            f"理想体重范围是 {ideal_low}~{ideal_high} kg。{advice}"
        ),
    }


def water_intake(weight: float = 60, **kwargs) -> dict:
    """每日推荐饮水量"""
    w = float(weight)
    ml = round(w * 35)  # 35ml/kg
    cups = round(ml / 200)  # 200ml/杯

    return {
        "weight_kg": w,
        "daily_water_ml": ml,
        "daily_water_L": round(ml / 1000, 1),
        "cups_200ml": cups,
        "summary": (
            f"体重 {w:.0f} kg，每天建议喝水约 {ml} ml（{cups} 杯 200ml），"
            f"即 {ml/1000:.1f} 升。运动后或天气热时可适当增加。"
        ),
    }


def heart_rate(age: float = 30, **kwargs) -> dict:
    """运动心率区间"""
    a = int(age)
    max_hr = 220 - a

    zones = {
        "热身区（50-60%）": (int(max_hr * 0.5), int(max_hr * 0.6), "适合热身，入门有氧"),
        "燃脂区（60-70%）": (int(max_hr * 0.6), int(max_hr * 0.7), "最佳燃脂，适合减重"),
        "有氧区（70-80%）": (int(max_hr * 0.7), int(max_hr * 0.8), "提升心肺，耐力训练"),
        "无氧区（80-90%）": (int(max_hr * 0.8), int(max_hr * 0.9), "提升速度，高强度训练"),
        "极限区（90%+）":   (int(max_hr * 0.9), max_hr,            "短时冲刺，需运动基础"),
    }

    return {
        "age": a,
        "max_heart_rate": max_hr,
        "zones": {k: {"low": v[0], "high": v[1], "desc": v[2]} for k, v in zones.items()},
        "fat_burn_zone": f"{int(max_hr*0.6)}-{int(max_hr*0.7)} bpm",
        "summary": (
            f"{a}岁的最大心率约 {max_hr} bpm。"
            f"燃脂跑步建议保持 {int(max_hr*0.6)}-{int(max_hr*0.7)} bpm，"
            f"有氧训练 {int(max_hr*0.7)}-{int(max_hr*0.8)} bpm。"
        ),
    }
