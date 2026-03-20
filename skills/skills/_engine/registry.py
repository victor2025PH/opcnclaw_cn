"""
技能注册表 — 扫描所有 skills/ 子目录，加载 _meta.json，建立索引
"""
import importlib
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

SKILLS_ROOT = Path(__file__).parent.parent


class Skill:
    """
    单个技能描述符

    技能分两种类型：
    - type="code"   → handler 字段指向 Python 函数，提供精确数据
    - type="prompt" → system_injection 字段，注入专业系统提示词，让 AI 表现得像领域专家
                      无需任何 Python 代码，可以用极低成本创造大量专业技能
    """

    def __init__(self, data: dict, category_dir: Path):
        self.id: str = data["id"]
        self.name_zh: str = data.get("name_zh", self.id)
        self.name_en: str = data.get("name_en", self.id)
        self.category: str = data.get("category", "")
        self.subcategory: str = data.get("subcategory", "")
        self.description: str = data.get("description", "")
        self.trigger_words: List[str] = data.get("trigger_words", [])
        self.examples: List[str] = data.get("examples", [])
        self.skill_type: str = data.get("type", "code")        # "code" or "prompt"
        self.handler_path: str = data.get("handler", "")       # only for type="code"
        self.system_injection: str = data.get("system_injection", "")  # only for type="prompt"
        self.params: List[dict] = data.get("params", [])
        self.preinstalled: bool = data.get("preinstalled", False)
        self.safe: bool = data.get("safe", True)
        self.needs_network: bool = data.get("needs_network", False)
        self.category_dir: Path = category_dir
        self._fn: Optional[Callable] = None

    def load_handler(self) -> bool:
        """动态加载处理函数"""
        if self._fn:
            return True
        if not self.handler_path:
            return False
        try:
            parts = self.handler_path.split(".")
            module_name = ".".join(parts[:-1])
            func_name = parts[-1]
            # 构建 skills.category.module 形式的导入路径
            cat_name = self.category_dir.name
            full_module = f"skills.{cat_name}.{module_name}"
            mod = importlib.import_module(full_module)
            self._fn = getattr(mod, func_name)
            return True
        except Exception as e:
            from loguru import logger
            logger.debug(f"Skill handler load failed {self.id}: {e}")
            return False

    def call(self, **kwargs):
        if not self._fn and not self.load_handler():
            return {"error": f"技能 {self.id} 无法加载"}
        try:
            return self._fn(**kwargs)
        except Exception as e:
            return {"error": str(e)}

    def __repr__(self):
        return f"<Skill {self.id}: {self.name_zh}>"


class SkillRegistry:
    """所有技能的注册表，懒加载"""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._categories: Dict[str, List[Skill]] = {}
        self._loaded = False

    def load_all(self):
        """扫描所有 _meta.json 文件，注册技能"""
        if self._loaded:
            return
        count = 0
        for cat_dir in sorted(SKILLS_ROOT.iterdir()):
            if cat_dir.is_dir() and not cat_dir.name.startswith("_"):
                meta_file = cat_dir / "_meta.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, encoding="utf-8") as f:
                            meta = json.load(f)
                        for skill_data in meta.get("skills", []):
                            skill = Skill(skill_data, cat_dir)
                            self._skills[skill.id] = skill
                            self._categories.setdefault(cat_dir.name, []).append(skill)
                            count += 1
                    except Exception as e:
                        from loguru import logger
                        logger.warning(f"Failed to load skills from {meta_file}: {e}")
        self._loaded = True
        from loguru import logger
        logger.info(f"✅ 技能引擎就绪: {count} 个技能，{len(self._categories)} 个分类")

    def get(self, skill_id: str) -> Optional[Skill]:
        if not self._loaded:
            self.load_all()
        return self._skills.get(skill_id)

    def all_skills(self) -> List[Skill]:
        if not self._loaded:
            self.load_all()
        return list(self._skills.values())

    def skills_in_category(self, category: str) -> List[Skill]:
        if not self._loaded:
            self.load_all()
        return self._categories.get(category, [])

    def categories(self) -> List[str]:
        if not self._loaded:
            self.load_all()
        return list(self._categories.keys())

    def search(self, query: str) -> List[Skill]:
        """简单文本搜索（名称/描述）"""
        if not self._loaded:
            self.load_all()
        q = query.lower()
        results = []
        for skill in self._skills.values():
            if (q in skill.name_zh.lower() or
                q in skill.description.lower() or
                any(q in tw for tw in skill.trigger_words)):
                results.append(skill)
        return results


# 全局单例
_registry = SkillRegistry()


def get_registry() -> SkillRegistry:
    return _registry
