"""文本处理块。

依赖资源文件：data/stopwords.txt（停用词表，通过 inputs.stopwords_text 传入）

入口函数：
  run              — 分词统计（高频词 TopN）
  extract_keywords — 基于 TF 提取关键词
  sentiment_mock   — 规则情感分析（正面/负面/中性）
"""

from __future__ import annotations

import re
from collections import Counter

# 内置停用词（可通过 inputs.stopwords_text 或 inputs.extra_stopwords 追加）
_BUILTIN_STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "对", "为", "有", "也", "都", "被", "把",
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这", "那", "一", "个",
    "就", "还", "而", "但", "所以", "因为", "如果", "可以", "非常", "很",
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "and", "or", "but", "with",
    "this", "that", "it", "i", "you", "he", "she", "we", "they",
}

# 情感词典（简化规则版）
_POSITIVE_WORDS = {
    "好", "优秀", "满意", "完美", "推荐", "喜欢", "棒", "赞", "不错", "优质",
    "出色", "高效", "快速", "便利", "实用", "超值", "惊喜", "专业", "贴心",
    "good", "great", "excellent", "amazing", "perfect", "love", "nice",
    "awesome", "fantastic", "wonderful", "helpful", "fast", "reliable",
}
_NEGATIVE_WORDS = {
    "差", "坏", "失望", "退款", "糟糕", "劣质", "不好", "垃圾", "骗", "慢",
    "贵", "难用", "崩溃", "卡顿", "延迟", "投诉", "问题", "故障", "破损", "假货",
    "bad", "poor", "terrible", "awful", "hate", "disappointed", "slow",
    "broken", "useless", "waste", "scam", "defective", "crash", "bug",
}

# 内置示例文本（inputs 未提供 text 时使用）
_SAMPLE_TEXT = """
产品质量非常好，物流也很快速，客服态度很专业，整体体验非常满意，强烈推荐给大家。
包装很精美，产品做工出色，使用起来很便利，性价比超值，值得购买。
这款产品功能实用，操作界面简洁高效，响应速度快，是一款很不错的产品。
数据分析平台性能优秀，支持多种数据格式，可视化效果很棒，团队协作非常方便。
""".strip()


def _parse_stopwords(inputs: dict) -> set[str]:
    """合并内置停用词 + 资源文件停用词 + inputs 追加停用词。"""
    extra: set[str] = set(inputs.get("extra_stopwords") or [])
    stopwords_text: str = inputs.get("stopwords_text") or ""
    from_file = {w.strip() for w in stopwords_text.splitlines() if w.strip()}
    return _BUILTIN_STOPWORDS | from_file | extra


def _tokenize(text: str) -> list[str]:
    """按非字母/汉字边界切分，保留长度 >= 1 的词元。"""
    tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text)
    return [t.lower() for t in tokens]


def _get_text(inputs: dict) -> str:
    return str(inputs.get("text") or inputs.get("content") or _SAMPLE_TEXT)


def run(inputs: dict) -> dict:
    """分词并统计高频词 Top-N。

    inputs:
      text (str, 可选): 待处理文本；不填则使用内置示例文本
      top_n (int, 可选): 返回前 N 个高频词，默认 20
      min_len (int, 可选): 词最短长度过滤，默认 2
      extra_stopwords (list, 可选): 追加停用词
      stopwords_text (str, 可选): 停用词文件内容（来自 data/stopwords.txt 资源）

    returns:
      word_count (dict): {词: 频次}（前 top_n 个）
      total_words (int): 分词总数（含停用词）
      unique_words (int): 去重有效词数
      top_n (int): 返回词数
    """
    text = _get_text(inputs)
    top_n: int = int(inputs.get("top_n", 20))
    min_len: int = int(inputs.get("min_len", 2))
    stopwords = _parse_stopwords(inputs)

    tokens = _tokenize(text)
    filtered = [w for w in tokens if w not in stopwords and len(w) >= min_len]
    counter = Counter(filtered)

    return {
        "word_count": dict(counter.most_common(top_n)),
        "total_words": len(tokens),
        "unique_words": len(set(filtered)),
        "top_n": top_n,
    }


def extract_keywords(inputs: dict) -> dict:
    """基于词频（TF）提取关键词列表。

    inputs:
      text (str, 可选): 待分析文本
      top_n (int, 可选): 提取关键词数，默认 10
      min_freq (int, 可选): 最低出现频次，默认 1
      min_len (int, 可选): 词最短长度，默认 2
      stopwords_text (str, 可选): 停用词文件内容

    returns:
      keywords (list): [{"word", "freq", "tf_score"}]
      analyzed_words (int): 有效词总数
      text_length (int): 文本字符数
    """
    text = _get_text(inputs)
    top_n: int = int(inputs.get("top_n", 10))
    min_freq: int = int(inputs.get("min_freq", 1))
    min_len: int = int(inputs.get("min_len", 2))
    stopwords = _parse_stopwords(inputs)

    tokens = _tokenize(text)
    filtered = [w for w in tokens if w not in stopwords and len(w) >= min_len]

    if not filtered:
        return {"keywords": [], "analyzed_words": 0, "text_length": len(text)}

    total = len(filtered)
    counter = Counter(filtered)
    keywords = [
        {
            "word": word,
            "freq": freq,
            "tf_score": round(freq / total, 6),
        }
        for word, freq in counter.most_common(top_n)
        if freq >= min_freq
    ]

    return {
        "keywords": keywords,
        "analyzed_words": total,
        "text_length": len(text),
    }


def sentiment_mock(inputs: dict) -> dict:
    """基于关键词匹配的规则情感分析（Mock 版，无需外部模型）。

    inputs:
      text (str, 可选): 待分析文本
      custom_positive (list, 可选): 追加正面词
      custom_negative (list, 可选): 追加负面词
      threshold (float, 可选): 正/负情感判定阈值，默认 0.2

    returns:
      sentiment (str): positive | negative | neutral
      score (float): 情感得分 -1.0 ~ 1.0（正值偏正面）
      positive_hits (list): 命中的正面词（去重）
      negative_hits (list): 命中的负面词（去重）
      pos_count (int): 正面词命中次数
      neg_count (int): 负面词命中次数
      analyzed_chars (int): 文本字符数
    """
    text = _get_text(inputs)
    custom_pos: set[str] = set(inputs.get("custom_positive") or [])
    custom_neg: set[str] = set(inputs.get("custom_negative") or [])
    threshold: float = float(inputs.get("threshold", 0.2))

    positive_dict = _POSITIVE_WORDS | custom_pos
    negative_dict = _NEGATIVE_WORDS | custom_neg

    tokens = _tokenize(text)
    pos_hits = [w for w in tokens if w in positive_dict]
    neg_hits = [w for w in tokens if w in negative_dict]

    pos_count = len(pos_hits)
    neg_count = len(neg_hits)
    total = pos_count + neg_count

    if total == 0:
        score = 0.0
        sentiment = "neutral"
    else:
        score = round((pos_count - neg_count) / total, 4)
        if score > threshold:
            sentiment = "positive"
        elif score < -threshold:
            sentiment = "negative"
        else:
            sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "score": score,
        "positive_hits": list(set(pos_hits)),
        "negative_hits": list(set(neg_hits)),
        "pos_count": pos_count,
        "neg_count": neg_count,
        "analyzed_chars": len(text),
    }
