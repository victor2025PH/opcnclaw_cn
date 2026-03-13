"""
技能执行器 — 执行技能并格式化结果供 AI 使用
"""
import asyncio
from typing import Optional

from loguru import logger

from .matcher import MatchResult, SkillMatcher
from .registry import get_registry


class SkillExecutor:
    """
    技能执行器：协调匹配 → 执行 → 格式化
    
    优化：技能结果注入到 AI 上下文而不是直接返回，
    让 AI 自然语言化结果，体验更好。
    """

    def __init__(self):
        self.registry = get_registry()
        self.matcher = SkillMatcher(self.registry)

    def try_match(self, user_text: str) -> Optional[MatchResult]:
        """尝试匹配技能，返回匹配结果或 None"""
        return self.matcher.match(user_text)

    def is_prompt_skill(self, match: MatchResult) -> bool:
        return match.skill.skill_type == "prompt"

    def execute_sync(self, match: MatchResult) -> dict:
        """同步执行技能，返回原始结果"""
        try:
            result = match.skill.call(**match.params)
            logger.info(f"🧩 技能执行: {match.skill.name_zh} → {str(result)[:80]}")
            return result
        except Exception as e:
            logger.error(f"技能执行失败 {match.skill.id}: {e}")
            return {"error": str(e)}

    async def execute(self, match: MatchResult) -> dict:
        """异步执行技能（支持需要网络的技能）"""
        loop = asyncio.get_event_loop()
        if match.skill.needs_network:
            # 网络型技能直接 await（技能本身是 async）
            try:
                import inspect
                fn = match.skill._fn
                if fn is None:
                    match.skill.load_handler()
                    fn = match.skill._fn
                if fn and inspect.iscoroutinefunction(fn):
                    return await fn(**match.params)
            except Exception as e:
                return {"error": str(e)}
        # CPU 型技能放线程池
        return await loop.run_in_executor(None, self.execute_sync, match)

    def build_skill_context(self, match: MatchResult, result: dict) -> str:
        """
        构建注入 AI 提示词的技能上下文。
        
        AI 拿到这段话后，用自然语言回答用户，
        比直接返回 JSON 体验好 10 倍。
        """
        if "error" in result:
            return (
                f"[技能执行出错]\n"
                f"技能: {match.skill.name_zh}\n"
                f"错误: {result['error']}\n"
                f"请告知用户遇到了问题，并建议他们重试。"
            )

        import json
        result_str = json.dumps(result, ensure_ascii=False, indent=2)

        return (
            f"[技能执行结果]\n"
            f"技能名称: {match.skill.name_zh}\n"
            f"原始数据:\n{result_str}\n\n"
            f"请根据以上数据，用简洁自然的中文语气回答用户，"
            f"不要直接读出 JSON，要像正常对话一样表达。"
        )

    async def process(self, user_text: str) -> Optional[tuple]:
        """
        一步到位：匹配 + 执行 + 构建上下文

        返回 (skill_name, context_prompt) 或 None（无匹配）

        Prompt 技能：直接返回 system_injection，无需执行 Python 代码
        Code 技能：执行 handler 获取数据，注入结构化结果
        """
        match = self.try_match(user_text)
        if not match:
            return None

        # 记录使用统计（异步，不阻塞主流程）
        try:
            from src.server.stats import record_usage
            record_usage(skill_id=match.skill.id, user_input=user_text[:80])
        except Exception:
            pass

        # ── Prompt 技能（纯提示词，无代码）──────────────────────
        if match.skill.skill_type == "prompt":
            context = (
                f"[领域技能激活: {match.skill.name_zh}]\n"
                f"{match.skill.system_injection}\n\n"
                f"用户问题：{user_text}\n"
                f"请以上述专家身份简洁地回答，语气口语化，适合语音播报。"
            )
            logger.info(f"💡 Prompt技能: {match.skill.name_zh}")
            return (match.skill.name_zh, context)

        # ── Code 技能（执行Python代码）──────────────────────────
        result = await self.execute(match)
        context = self.build_skill_context(match, result)
        return (match.skill.name_zh, context)


# 全局实例（在服务器启动时初始化一次）
_executor: Optional[SkillExecutor] = None


def get_executor() -> SkillExecutor:
    global _executor
    if _executor is None:
        _executor = SkillExecutor()
    return _executor
