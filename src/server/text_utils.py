"""
Text utilities for voice-friendly output.

Cleans AI responses for TTS (removes markdown, URLs, symbols, etc.)
"""

import re


def clean_for_speech(text: str) -> str:
    """清理文本，让 TTS 只朗读有意义的中文/英文内容"""
    if not text:
        return text

    # 1. 移除代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)

    # 2. 移除 TOOL_CALL 块
    text = re.sub(r'\[TOOL_CALL\][\s\S]*?\[/TOOL_CALL\]', '', text, flags=re.IGNORECASE)

    # 3. 移除 URL（各种格式，彻底清除）
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'//\S+', '', text)                   # //duckduckgo.com/...
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r'\S+\.(com|cn|io|org|net|ai|app|html|php|asp)\S*', '', text)
    text = re.sub(r'\S*%[0-9A-Fa-f]{2}\S*', '', text)  # URL编码 %2F %3A 等
    text = re.sub(r'\S+/\S+/\S+', '', text)             # 路径 a/b/c
    text = re.sub(r'[a-zA-Z0-9_\-]{20,}', '', text)     # 长字母数字串（token/hash）

    # 4. 移除 markdown 链接 [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # 5. 移除 JSON/字典内容
    text = re.sub(r'\{[^}]{10,}\}', '', text)
    text = re.sub(r'\[[^\]]{20,}\]', '', text)

    # 6. 移除 markdown 格式符号
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)  # 标题
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **粗体**
    text = re.sub(r'__([^_]+)__', r'\1', text)       # __粗体__
    text = re.sub(r'\*([^*]+)\*', r'\1', text)       # *斜体*
    text = re.sub(r'_([^_]+)_', r'\1', text)         # _斜体_

    # 7. 移除剩余的星号、井号等符号
    text = re.sub(r'[*#_~`|>]', '', text)

    # 7.5 移除函数调用格式 xxx(...) 和 key=value
    text = re.sub(r'\w+\([^)]*\)', '', text)           # function(args)
    text = re.sub(r'\w+=\w+', '', text)                 # key=value
    text = re.sub(r'\w+=["\'][^"\']*["\']', '', text)   # key="value"

    # 8. 移除 emoji（几乎所有）
    text = re.sub(r'[\U0001F300-\U0001F9FF\u2600-\u27BF\u2300-\u23FF]', '', text)

    # 9. 移除列表符号
    text = re.sub(r'^\s*[-•●◆▪]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+[.、）)]\s*', '', text, flags=re.MULTILINE)

    # 10. 移除括号中的英文技术词（保留中文括号内容）
    text = re.sub(r'\([a-zA-Z0-9_\-./: ]{5,}\)', '', text)

    # 11. 清理多余空白
    text = re.sub(r'\n{2,}', '。', text)
    text = re.sub(r'\n', '，', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'[。，]{2,}', '。', text)

    text = text.strip()
    # 移除开头的标点
    text = re.sub(r'^[。，、；：！？,.;:!?\s]+', '', text)

    return text


def estimate_speech_duration(text: str, wpm: int = 150) -> float:
    """Estimate speech duration in seconds."""
    word_count = len(text.split())
    return (word_count / wpm) * 60
