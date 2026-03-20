"""理财金融技能"""
import math


def calc_mortgage(amount: float = 100, rate: float = 3.5, years: int = 30, **kwargs) -> dict:
    """等额本息房贷计算"""
    principal = float(amount) * 10000  # 万转元
    annual_rate = float(rate) / 100
    months = int(years) * 12
    monthly_rate = annual_rate / 12

    if monthly_rate == 0:
        monthly_payment = principal / months
    else:
        monthly_payment = principal * monthly_rate * (1 + monthly_rate) ** months / \
                          ((1 + monthly_rate) ** months - 1)

    total_payment = monthly_payment * months
    total_interest = total_payment - principal

    return {
        "贷款金额_万": amount,
        "年利率": f"{rate}%",
        "贷款年限": years,
        "月供": round(monthly_payment, 2),
        "月供_formatted": f"¥{monthly_payment:,.2f}",
        "还款总额": round(total_payment, 2),
        "还款总额_formatted": f"¥{total_payment:,.2f}",
        "支付利息": round(total_interest, 2),
        "支付利息_formatted": f"¥{total_interest:,.2f}",
        "利息占比": f"{total_interest/principal*100:.1f}%",
        "summary": (
            f"贷款{amount}万，年利率{rate}%，{years}年还清。"
            f"每月还款 ¥{monthly_payment:,.0f}，"
            f"总利息约 ¥{total_interest:,.0f}（{total_interest/principal*100:.0f}%）"
        ),
    }


def calc_tax(salary: float = 10000, city_level: str = "一线", **kwargs) -> dict:
    """个人所得税计算（2024版税率表）"""
    salary = float(salary)

    # 五险一金比例（个人部分，按一线城市估算）
    rates = {
        "一线": {"pension": 0.08, "medical": 0.02, "unemployment": 0.005, "housing": 0.07},
        "二线": {"pension": 0.08, "medical": 0.02, "unemployment": 0.005, "housing": 0.05},
        "其他": {"pension": 0.08, "medical": 0.02, "unemployment": 0.005, "housing": 0.05},
    }
    r = rates.get(city_level, rates["二线"])
    insurance = salary * (r["pension"] + r["medical"] + r["unemployment"] + r["housing"])
    housing_fund = salary * r["housing"]

    # 应纳税所得额（扣除5000起征点 + 三险一金）
    deduction = 5000
    taxable = max(0, salary - insurance - deduction)

    # 2024年个税税率表（月应纳税所得额）
    brackets = [
        (36000/12, 0.03, 0),
        (144000/12, 0.10, 2520/12),
        (300000/12, 0.20, 16920/12),
        (420000/12, 0.25, 31920/12),
        (660000/12, 0.30, 52920/12),
        (960000/12, 0.35, 85920/12),
        (float('inf'), 0.45, 181920/12),
    ]
    tax = 0
    rate_used = 0
    for upper, rate, quick_deduct in brackets:
        if taxable <= upper:
            tax = taxable * rate - quick_deduct
            rate_used = rate
            break

    take_home = salary - insurance - max(0, tax)

    return {
        "税前月薪": f"¥{salary:,.0f}",
        "五险一金": f"¥{insurance:,.0f}",
        "应纳税所得额": f"¥{taxable:,.0f}",
        "个人所得税": f"¥{max(0, tax):,.0f}",
        "适用税率": f"{rate_used*100:.0f}%",
        "实际到手": f"¥{take_home:,.0f}",
        "到手_number": round(take_home, 2),
        "summary": (
            f"税前月薪 ¥{salary:,.0f}，扣五险一金 ¥{insurance:,.0f}，"
            f"个税 ¥{max(0,tax):,.0f}，实际到手 ¥{take_home:,.0f}"
        ),
    }


def calc_compound(principal: float = 100000, rate: float = 5, years: int = 10, **kwargs) -> dict:
    """复利计算"""
    p = float(principal)
    r = float(rate) / 100
    y = int(years)

    final = p * (1 + r) ** y
    profit = final - p

    # 72法则：翻倍所需年数
    double_years = 72 / (rate if rate > 0 else 1)

    return {
        "本金": f"¥{p:,.0f}",
        "年化收益率": f"{rate}%",
        "投资年限": y,
        "最终金额": f"¥{final:,.0f}",
        "总收益": f"¥{profit:,.0f}",
        "收益率": f"{(profit/p*100):.1f}%",
        "翻倍需要": f"约{double_years:.0f}年（72法则）",
        "summary": (
            f"本金{p/10000:.0f}万，年化{rate}%，{y}年后变为{final/10000:.1f}万，"
            f"赚了{profit/10000:.1f}万（{profit/p*100:.0f}%）。"
            f"按此利率{double_years:.0f}年翻倍。"
        ),
    }


async def exchange(amount: float = 100, from_currency: str = "USD", to_currency: str = "CNY", **kwargs) -> dict:
    """汇率换算（优先实时，降级到内置参考汇率）"""
    # 内置参考汇率（人民币基准，定期更新）
    REFERENCE_RATES = {
        "CNY": 1.0,
        "USD": 7.25, "EUR": 7.85, "GBP": 9.15, "JPY": 0.047,
        "HKD": 0.93, "KRW": 0.0053, "SGD": 5.38, "AUD": 4.68,
        "CAD": 5.28, "CHF": 8.12, "THB": 0.21, "MYR": 1.65,
        "TWD": 0.23, "MOP": 0.90,
    }
    CURRENCY_NAMES = {
        "USD": "美元", "EUR": "欧元", "GBP": "英镑", "JPY": "日元",
        "HKD": "港币", "KRW": "韩元", "CNY": "人民币", "SGD": "新加坡元",
        "AUD": "澳大利亚元", "CAD": "加拿大元", "CHF": "瑞士法郎",
        "THB": "泰铢", "MYR": "马来西亚林吉特", "TWD": "台币", "MOP": "澳门元",
    }

    fc = from_currency.upper()
    tc = to_currency.upper()

    # 识别中文货币名
    cn_map = {v: k for k, v in CURRENCY_NAMES.items()}
    if fc in cn_map:
        fc = cn_map[fc]
    if tc in cn_map:
        tc = cn_map[tc]

    # 尝试实时汇率
    realtime = False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"https://open.er-api.com/v6/latest/{fc}",
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("result") == "success":
                    rates = data["rates"]
                    rate = rates.get(tc, 0)
                    if rate:
                        result_amount = amount * rate
                        realtime = True
                        return {
                            "from": f"{amount} {fc}",
                            "to": f"{result_amount:.4f} {tc}",
                            "rate": rate,
                            "from_name": CURRENCY_NAMES.get(fc, fc),
                            "to_name": CURRENCY_NAMES.get(tc, tc),
                            "realtime": True,
                            "summary": f"{amount} {CURRENCY_NAMES.get(fc, fc)} ≈ {result_amount:.2f} {CURRENCY_NAMES.get(tc, tc)}（实时汇率）",
                        }
    except Exception:
        pass

    # 降级到内置参考汇率
    if fc not in REFERENCE_RATES or tc not in REFERENCE_RATES:
        return {"error": f"不支持的货币: {fc} 或 {tc}"}

    cny_amount = amount * REFERENCE_RATES[fc]
    result_amount = cny_amount / REFERENCE_RATES[tc]

    return {
        "from": f"{amount} {fc}",
        "to": f"{result_amount:.4f} {tc}",
        "rate": REFERENCE_RATES[fc] / REFERENCE_RATES[tc],
        "from_name": CURRENCY_NAMES.get(fc, fc),
        "to_name": CURRENCY_NAMES.get(tc, tc),
        "realtime": False,
        "note": "参考汇率，非实时",
        "summary": f"{amount} {CURRENCY_NAMES.get(fc, fc)} ≈ {result_amount:.2f} {CURRENCY_NAMES.get(tc, tc)}（参考汇率）",
    }
