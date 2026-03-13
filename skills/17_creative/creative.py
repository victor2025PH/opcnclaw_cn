"""创意写作技能（轻量版，供 AI 增强用）"""
import random


BIRTHDAY_TEMPLATES = [
    "愿你的{age}岁，笑声多过烦恼，快乐多过忧愁。生日快乐！🎂",
    "岁月不居，时节如流。愿你此刻所拥有的，都是你喜欢的。生日快乐！",
    "又是一年生日到，送你开心和微笑。愿你每天都有好心情，生日快乐！🎈",
    "生日快乐！愿你今天吃好喝好，未来所有的期待都如约而至。",
    "今天是你的节日，愿所有美好都向你涌来，所有烦恼都离你远去！生日快乐🎂",
    "把最诚挚的祝福送给你，愿你笑口常开，天天开心！生日快乐！",
    "愿岁月温柔以待，愿你所爱皆如愿。生日快乐，永远年轻！🌟",
]

NEWYEAR_TEMPLATES = {
    "正式": [
        "新的一年，愿{recipient}身体健康，万事如意，工作顺利，阖家幸福！新年快乐！",
        "岁末辞旧迎新，祝{recipient}新的一年，诸事顺遂，心想事成！",
        "新春佳节，送上最诚挚的祝愿。愿{recipient}在新的一年里，阖家安康，幸福美满！",
    ],
    "轻松": [
        "新年到啦！🎆 祝{recipient}新的一年赚钱多多，烦恼少少，天天开心！",
        "恭喜发财！愿{recipient}新的一年睡醒就有钱，出门皆是喜，万事顺心！🧧",
        "新年快乐！祝{recipient}这一年：钱途似锦，前途光明，薪情愉快！💰",
    ],
}

MOMENTS_TEMPLATES = {
    "旅游": [
        "世界那么大，我想去看看 🌍",
        "又一次说走就走的旅行，这辈子要把地图走成足迹 ✈️",
        "旅行的意义，不只是去了哪里，而是路上遇见的风景和自己 🗺️",
        "愿你走遍山河，归来仍是少年 🏔️",
    ],
    "美食": [
        "人间烟火气，最抚凡人心 🍜",
        "没有什么事是一顿美食解决不了的，如果有，那就两顿 🍲",
        "干饭人，干饭魂，干饭必须精神抖擞 😋",
        "今天也是被美食治愈的一天 🍱",
    ],
    "自拍": [
        "今天也是美美哒一天 ✨",
        "岁月不饶人，我也不饶岁月 💅",
        "有时候要假装一下精致，不然真的会沉沦 🌸",
        "美貌与才华兼备，这句话说的就是我 😆",
    ],
    "心情": [
        "生活总是在最不经意的时候，给你一个惊喜 🌈",
        "愿你不急不躁，慢慢成为自己想要的样子 🌿",
        "今天也是元气满满的一天！加油 💪",
        "把每一天都过成礼物 🎁",
    ],
    "工作": [
        "又是努力搬砖的一天，生活不易，且行且珍惜 💼",
        "打工人，打工魂，打工都是人上人 😤",
        "工作是为了更好地生活，而不是为了工作而生活 ☕",
    ],
}

CREATIVE_NAMES = {
    "网名": ["星辰逐梦", "风轻云淡", "温柔以待", "浅笑安然", "半缘修道", "云深不知处",
            "青山不老", "向阳而生", "余生皆甜", "烟雨江南", "一念执着", "时光正好"],
    "宝宝": {
        "男": ["浩然", "俊熙", "子墨", "睿博", "鑫宇", "天翊", "明轩", "逸飞"],
        "女": ["雨馨", "静怡", "思涵", "若晴", "梦琪", "欣悦", "嘉怡", "诗涵"],
    },
}


def birthday_blessing(name: str = "", style: str = "温馨", **kwargs) -> dict:
    template = random.choice(BIRTHDAY_TEMPLATES)
    text = template.format(age="新的一岁")
    if name:
        text = f"{name}，" + text
    return {"blessing": text, "style": style, "type": "birthday"}


def newyear_blessing(recipient: str = "朋友", style: str = "正式", **kwargs) -> dict:
    templates = NEWYEAR_TEMPLATES.get(style, NEWYEAR_TEMPLATES["轻松"])
    text = random.choice(templates).format(recipient=recipient)
    return {"blessing": text, "recipient": recipient, "style": style}


def generate_names(purpose: str = "网名", surname: str = "", style: str = "现代", **kwargs) -> dict:
    if "宝宝" in purpose or "小孩" in purpose or "婴儿" in purpose:
        boy_names = [surname + n for n in CREATIVE_NAMES["宝宝"]["男"]]
        girl_names = [surname + n for n in CREATIVE_NAMES["宝宝"]["女"]]
        return {
            "purpose": "宝宝取名",
            "boy_names": random.sample(boy_names, min(5, len(boy_names))),
            "girl_names": random.sample(girl_names, min(5, len(girl_names))),
            "tip": "以上仅供参考，具体还需结合父母姓名五行、生辰八字综合考虑",
        }
    else:
        names = random.sample(CREATIVE_NAMES["网名"], 8)
        return {
            "purpose": purpose,
            "suggestions": names,
            "tip": "以上为随机推荐，你也可以组合自己喜欢的词语",
        }


def moments_copy(scene: str = "旅游", mood: str = "开心", **kwargs) -> dict:
    templates = MOMENTS_TEMPLATES.get(scene, MOMENTS_TEMPLATES["心情"])
    selected = random.sample(templates, min(3, len(templates)))
    return {
        "scene": scene,
        "suggestions": selected,
        "tip": "以上文案可以直接使用，也可以根据实际情况修改",
    }
