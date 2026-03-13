"""出行相关技能"""

async def get_oil_price(province: str = "全国", **kwargs) -> dict:
    BASE_PRICES = {"92号": 7.35, "95号": 7.80, "98号": 8.72, "0号柴油": 7.31}
    return {
        "province": province, "prices": BASE_PRICES,
        "summary": f"参考油价 — 92号¥{BASE_PRICES['92号']}/L，95号¥{BASE_PRICES['95号']}/L，柴油¥{BASE_PRICES['0号柴油']}/L（以当地实际为准）",
    }
