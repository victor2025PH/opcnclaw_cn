"""天气技能 — 使用免费 Open-Meteo API（无需 Key）"""
import httpx


WMO_CODES = {
    0: "晴天☀️", 1: "大致晴朗🌤️", 2: "局部多云⛅", 3: "阴天☁️",
    45: "雾🌫️", 48: "冻雾", 51: "轻毛毛雨🌦️", 53: "毛毛雨", 55: "大毛毛雨",
    61: "小雨🌧️", 63: "中雨🌧️", 65: "大雨", 71: "小雪🌨️", 73: "中雪❄️", 75: "大雪",
    80: "小阵雨", 81: "中阵雨🌦️", 82: "强阵雨⛈️",
    95: "雷暴⛈️", 96: "雷暴伴冰雹", 99: "强雷暴⛈️",
}

CITY_COORDS = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
    "成都": (30.5728, 104.0668), "杭州": (30.2741, 120.1551),
    "武汉": (30.5928, 114.3055), "重庆": (29.5630, 106.5516),
    "西安": (34.3416, 108.9398), "南京": (32.0603, 118.7969),
    "天津": (39.3434, 117.3616), "苏州": (31.2990, 120.5853),
    "青岛": (36.0671, 120.3826), "大连": (38.9140, 121.6147),
    "厦门": (24.4798, 118.0894), "宁波": (29.8683, 121.5440),
    "长沙": (28.2278, 112.9388), "郑州": (34.7472, 113.6249),
    "济南": (36.6512, 117.1201), "福州": (26.0745, 119.2965),
    "哈尔滨": (45.8038, 126.5349), "合肥": (31.8206, 117.2272),
    "昆明": (25.0453, 102.7097), "南宁": (22.8170, 108.3665),
    "太原": (37.8706, 112.5489), "南昌": (28.6820, 115.8581),
    "贵阳": (26.6470, 106.6302), "石家庄": (38.0428, 114.5149),
    "三亚": (18.2524, 109.5119), "海口": (20.0458, 110.1993),
}


async def get_weather(city: str = "北京", **kwargs) -> dict:
    """获取城市天气"""
    coords = CITY_COORDS.get(city)
    if not coords:
        # 尝试地理编码
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city, "count": 1, "language": "zh"},
                )
                data = r.json()
                if data.get("results"):
                    loc = data["results"][0]
                    coords = (loc["latitude"], loc["longitude"])
                    city = loc.get("name", city)
        except Exception:
            return {"error": f"无法找到城市 {city}，请检查城市名称"}

    if not coords:
        return {"error": f"不支持的城市: {city}"}

    lat, lon = coords
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": ["temperature_2m", "apparent_temperature",
                                "relative_humidity_2m", "weather_code",
                                "wind_speed_10m", "precipitation"],
                    "daily": ["weather_code", "temperature_2m_max",
                              "temperature_2m_min", "precipitation_sum"],
                    "timezone": "Asia/Shanghai",
                    "forecast_days": 3,
                },
            )
            data = r.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        temp = current.get("temperature_2m", "--")
        feels = current.get("apparent_temperature", "--")
        humidity = current.get("relative_humidity_2m", "--")
        wind = current.get("wind_speed_10m", "--")
        code = current.get("weather_code", 0)
        condition = WMO_CODES.get(code, "未知")

        # 穿衣建议
        if temp <= 5:
            clothes = "❄️ 羽绒服、厚外套"
        elif temp <= 12:
            clothes = "🧥 毛衣、外套"
        elif temp <= 18:
            clothes = "👔 薄外套、长袖"
        elif temp <= 24:
            clothes = "👕 短袖、薄长裤"
        else:
            clothes = "🩴 短袖短裤、防晒"

        umbrella = "☂️ 建议带伞" if current.get("precipitation", 0) > 0.1 or code in [51,53,55,61,63,65,71,73,75,80,81,82,95,96,99] else "☀️ 不需要带伞"

        forecast = []
        if daily.get("time"):
            for i in range(min(3, len(daily["time"]))):
                forecast.append({
                    "date": daily["time"][i],
                    "max": daily["temperature_2m_max"][i],
                    "min": daily["temperature_2m_min"][i],
                    "condition": WMO_CODES.get(daily["weather_code"][i], ""),
                    "rain": daily["precipitation_sum"][i],
                })

        return {
            "city": city,
            "temperature": temp,
            "feels_like": feels,
            "humidity": humidity,
            "wind_speed": wind,
            "condition": condition,
            "clothes_suggestion": clothes,
            "umbrella": umbrella,
            "forecast_3day": forecast,
            "summary": (
                f"{city}现在{condition}，{temp}°C（体感{feels}°C），"
                f"湿度{humidity}%，风速{wind}km/h。{umbrella}。"
                f"穿衣参考：{clothes}"
            ),
        }
    except Exception as e:
        return {"error": f"天气获取失败: {e}，请检查网络"}


async def get_oil_price(province: str = "全国", **kwargs) -> dict:
    """油价查询（内置参考数据，实际项目可对接实时API）"""
    # 2024年参考油价（实际应从 API 获取）
    BASE_PRICES = {
        "92号": 7.35, "95号": 7.80, "98号": 8.72, "0号柴油": 7.31
    }
    return {
        "province": province,
        "prices": BASE_PRICES,
        "update_tip": "以当地加油站实际价格为准",
        "summary": (
            f"参考油价 — 92号: ¥{BASE_PRICES['92号']}/L，"
            f"95号: ¥{BASE_PRICES['95号']}/L，"
            f"98号: ¥{BASE_PRICES['98号']}/L，"
            f"柴油: ¥{BASE_PRICES['0号柴油']}/L"
        ),
    }


# 同名同步别名（供测试）
travel = type('', (), {'get_oil_price': get_oil_price})()
