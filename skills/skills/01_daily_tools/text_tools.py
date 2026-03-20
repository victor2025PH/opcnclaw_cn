"""文本工具技能"""
import re


def num_to_chinese(amount: float = 0, **kwargs) -> dict:
    """数字转人民币大写"""
    try:
        amount = float(amount)
    except Exception:
        return {"error": "无效金额"}

    if amount < 0:
        return {"error": "不支持负数"}
    if amount >= 1e12:
        return {"error": "金额过大（最大支持万亿）"}

    DIGITS = "零壹贰叁肆伍陆柒捌玖"
    UNITS = ["", "拾", "佰", "仟"]
    MAGNITUDES = ["", "万", "亿", "万亿"]

    def _int_to_chinese(n: int) -> str:
        if n == 0:
            return "零"
        result = ""
        groups = []
        while n > 0:
            groups.append(n % 10000)
            n //= 10000

        for idx, group in enumerate(reversed(groups)):
            if group == 0:
                if result and result[-1] != "零":
                    result += "零"
                continue
            group_str = ""
            thousands = group // 1000
            hundreds = (group % 1000) // 100
            tens = (group % 100) // 10
            ones = group % 10

            if thousands:
                group_str += DIGITS[thousands] + "仟"
            if hundreds:
                group_str += DIGITS[hundreds] + "佰"
            elif thousands and (tens or ones):
                group_str += "零"
            if tens:
                group_str += DIGITS[tens] + "拾"
            elif hundreds and ones:
                group_str += "零"
            if ones:
                group_str += DIGITS[ones]
            result += group_str + MAGNITUDES[len(groups) - 1 - idx]

        return result

    int_part = int(amount)
    frac = round(amount - int_part, 2)
    jiao = int(frac * 10)
    fen = int(round(frac * 100) % 10)

    result = _int_to_chinese(int_part) + "元"
    if jiao == 0 and fen == 0:
        result += "整"
    else:
        if int_part > 0 and jiao == 0:
            result += "零"
        if jiao:
            result += DIGITS[jiao] + "角"
        if fen:
            result += DIGITS[fen] + "分"

    return {"amount": amount, "chinese": result, "message": f"人民币大写：{result}"}


def parse_id_card(id_number: str = "", **kwargs) -> dict:
    """解析中国居民身份证号"""
    id_num = re.sub(r'\s+', '', id_number).upper()
    if not re.match(r'^\d{17}[\dX]$', id_num):
        return {"error": "身份证号格式不正确（应为18位数字，最后一位可为X）"}

    # 校验码
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_chars = "10X98765432"
    total = sum(int(id_num[i]) * weights[i] for i in range(17))
    expected = check_chars[total % 11]
    valid = id_num[17] == expected

    # 地区码（部分主要城市）
    area_codes = {
        "11": "北京市", "12": "天津市", "13": "河北省", "14": "山西省",
        "15": "内蒙古自治区", "21": "辽宁省", "22": "吉林省", "23": "黑龙江省",
        "31": "上海市", "32": "江苏省", "33": "浙江省", "34": "安徽省",
        "35": "福建省", "36": "江西省", "37": "山东省", "41": "河南省",
        "42": "湖北省", "43": "湖南省", "44": "广东省", "45": "广西壮族自治区",
        "46": "海南省", "50": "重庆市", "51": "四川省", "52": "贵州省",
        "53": "云南省", "54": "西藏自治区", "61": "陕西省", "62": "甘肃省",
        "63": "青海省", "64": "宁夏回族自治区", "65": "新疆维吾尔自治区",
        "71": "台湾省", "81": "香港特别行政区", "82": "澳门特别行政区",
    }
    area = area_codes.get(id_num[:2], "未知地区")

    birth = f"{id_num[6:10]}年{id_num[10:12]}月{id_num[12:14]}日"
    gender = "男" if int(id_num[16]) % 2 == 1 else "女"

    from datetime import date
    birth_date = date(int(id_num[6:10]), int(id_num[10:12]), int(id_num[12:14]))
    today = date.today()
    age = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )

    return {
        "id_number": id_num,
        "valid": valid,
        "area": area,
        "birthday": birth,
        "gender": gender,
        "age": age,
        "check_digit": id_num[17],
        "expected_check": expected,
        "message": f"归属：{area} | 生日：{birth} | 性别：{gender} | 年龄：{age}岁 | 校验：{'✅有效' if valid else '❌无效'}",
    }


def convert_chars(text: str = "", direction: str = "s2t", **kwargs) -> dict:
    """简繁体转换"""
    try:
        import opencc
        config = "s2t.json" if direction == "s2t" else "t2s.json"
        converter = opencc.OpenCC(config)
        result = converter.convert(text)
        return {
            "input": text[:50] + ("..." if len(text) > 50 else ""),
            "output": result,
            "direction": "简体→繁体" if direction == "s2t" else "繁体→简体",
        }
    except ImportError:
        # 简单映射（不完整，仅演示）
        mapping = {"爱": "愛", "国": "國", "来": "來", "说": "說", "为": "為"}
        result = "".join(mapping.get(c, c) for c in text)
        return {"output": result, "note": "需要安装 opencc-python-reimplemented 获得完整支持"}
    except Exception as e:
        return {"error": str(e)}
