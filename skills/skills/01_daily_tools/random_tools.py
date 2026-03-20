"""随机工具技能"""
import random
import string


FOOD_OPTIONS = [
    "火锅🍲","麻辣烫🌶️","烤鸭🦆","炸鸡🍗","披萨🍕","寿司🍱","拉面🍜","汉堡🍔",
    "饺子🥟","炒饭🍳","红烧肉🥩","糖醋排骨","烤串🥓","螺蛳粉","豆浆油条",
    "热干面","担担面","小笼包","煲仔饭","酸辣土豆丝","番茄炒蛋",
    "麻婆豆腐","宫保鸡丁","鱼香肉丝","红烧鱼","清蒸虾",
]


def random_choice(options: str = "", **kwargs) -> dict:
    """随机选择或抛硬币/掷骰子"""
    # 解析用户提供的选项
    items = []
    if options:
        for sep in ["还是", "或者", "or", "/", "、", "，", ","]:
            if sep in options:
                items = [x.strip() for x in options.split(sep) if x.strip()]
                break

    if not items:
        # 默认：今天吃什么
        chosen = random.choice(FOOD_OPTIONS)
        return {
            "type": "food",
            "result": chosen,
            "message": f"今天就吃 {chosen} 吧！",
        }

    if len(items) == 1 and items[0] in ("硬币", "coin"):
        result = random.choice(["正面 👍", "反面 👎"])
        return {"type": "coin", "result": result, "message": f"抛硬币结果：{result}"}

    if len(items) == 1 and "骰子" in items[0]:
        result = random.randint(1, 6)
        return {"type": "dice", "result": result, "message": f"🎲 掷出了 {result} 点"}

    chosen = random.choice(items)
    return {
        "type": "choice",
        "options": items,
        "result": chosen,
        "message": f"随机选择：{chosen}",
    }


def gen_password(length: int = 16, special: bool = True, **kwargs) -> dict:
    """生成随机强密码"""
    length = max(8, min(64, int(length)))
    chars = string.ascii_letters + string.digits
    if special:
        chars += "!@#$%^&*()-_=+"
    pwd = ''.join(random.choices(chars, k=length))
    # 确保包含大小写和数字
    pwd = list(pwd)
    pwd[0] = random.choice(string.ascii_uppercase)
    pwd[1] = random.choice(string.ascii_lowercase)
    pwd[2] = random.choice(string.digits)
    if special:
        pwd[3] = random.choice("!@#$%^&*")
    random.shuffle(pwd)
    return {
        "password": "".join(pwd),
        "length": length,
        "strength": "强" if length >= 12 and special else "中",
        "tip": "请保存好这个密码，它不会再次显示",
    }
