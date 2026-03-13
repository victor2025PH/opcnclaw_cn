"""数学计算技能"""
import math
import re


def calc(expression: str = "", **kwargs) -> dict:
    """安全数学表达式计算"""
    expr = expression.strip()
    if not expr:
        return {"error": "请提供计算表达式"}

    # 中文数学词汇转换
    replacements = {
        "加": "+", "减": "-", "乘以": "*", "除以": "/",
        "次方": "**", "的": "**", "平方": "**2",
        "开方": "sqrt", "开根号": "sqrt",
        "π": "pi", "派": "pi", "圆周率": "pi",
        "正弦": "sin", "余弦": "cos", "正切": "tan",
        "绝对值": "abs", "取整": "floor",
        "对数": "log", "自然对数": "log",
        "百分之": "*0.01",
        "万": "*10000", "亿": "*100000000",
    }
    for cn, en in replacements.items():
        expr = expr.replace(cn, en)

    # 移除非安全字符
    expr = re.sub(r'[^\d\s\+\-\*/\(\)\.\^%,a-zA-Z_]', '', expr)
    expr = expr.replace("^", "**")

    safe_names = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
        "tan": math.tan, "asin": math.asin, "acos": math.acos,
        "atan": math.atan, "log": math.log, "log10": math.log10,
        "log2": math.log2, "abs": abs, "round": round,
        "floor": math.floor, "ceil": math.ceil,
        "pi": math.pi, "e": math.e, "pow": pow,
        "max": max, "min": min,
    }
    try:
        result = eval(expr, {"__builtins__": {}}, safe_names)  # noqa: S307
        # 格式化输出
        if isinstance(result, float):
            if result == int(result):
                result_str = str(int(result))
            else:
                result_str = f"{result:.6g}"
        else:
            result_str = str(result)
        return {
            "expression": expression,
            "result": result,
            "result_formatted": result_str,
        }
    except ZeroDivisionError:
        return {"error": "计算错误：除以零"}
    except Exception as e:
        return {"error": f"计算错误：{e}，表达式：{expr}"}
