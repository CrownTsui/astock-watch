# -*- coding: utf-8 -*-
"""
消息面分析 + 情感打分。

情感引擎：自建金融情感词库（config.py），对每条标题+摘要做极性打分 [-1,1]，
支持程度副词放大与否定词翻转。比通用 SnowNLP 更贴合 A 股语境；若环境已装
SnowNLP，则与词库分加权融合，进一步平滑。
"""
from __future__ import annotations

from . import config as C
from .utils import clamp, safe_round

try:
    from snownlp import SnowNLP
    _HAS_SNOWNLP = True
except Exception:
    _HAS_SNOWNLP = False


def _lexicon_score(text: str) -> float:
    """基于金融词库的极性分 [-1,1]。命中词取平均极性，叠加程度/否定修饰。"""
    if not text:
        return 0.0
    total, hits = 0.0, 0
    for word_set, polarity in ((C.POSITIVE_WORDS, 1.0), (C.NEGATIVE_WORDS, -1.0)):
        for w in word_set:
            idx = text.find(w)
            if idx < 0:
                continue
            window = text[max(0, idx - 3):idx]        # 词前 3 字窗口
            factor = 1.0
            for deg, mult in C.DEGREE_WORDS.items():
                if deg in window:
                    factor *= mult
            if any(neg in window for neg in C.NEGATION_WORDS):
                factor *= -1.0                          # 否定翻转
            total += polarity * factor
            hits += 1
    if hits == 0:
        return 0.0
    return clamp(total / hits, -1.0, 1.0)


def score_text(text: str) -> float:
    """单条文本情感分 [-1,1]，词库为主，SnowNLP（若有）为辅。"""
    lex = _lexicon_score(text)
    if _HAS_SNOWNLP and text:
        try:
            snow = (SnowNLP(text).sentiments - 0.5) * 2     # [0,1] -> [-1,1]
            # 词库命中时以词库为主(0.7)，否则更依赖 SnowNLP
            return clamp(0.7 * lex + 0.3 * snow) if lex != 0 else clamp(0.4 * snow)
        except Exception:
            return lex
    return lex


def _label(score: float) -> tuple:
    if score >= C.SENTIMENT_POS_TH:
        return "正面", "pos"
    if score <= C.SENTIMENT_NEG_TH:
        return "负面", "neg"
    return "中性", "neutral"


def analyze(news_list: list) -> dict:
    """对新闻/公告列表逐条打分并汇总。"""
    if not news_list:
        return {
            "available": False, "score": 50.0, "items": [],
            "pos": 0, "neg": 0, "neutral": 0, "overall": "中性",
            "top": [], "summary": "近期未获取到相关新闻或公告，消息面以中性计入。",
        }

    items = []
    for n in news_list:
        text = f"{n.get('title','')} {n.get('summary','')}"
        sc = score_text(text)
        label, tone = _label(sc)
        items.append({**n, "sentiment": label, "tone": tone, "senti_score": safe_round(sc, 3)})

    pos = sum(1 for i in items if i["tone"] == "pos")
    neg = sum(1 for i in items if i["tone"] == "neg")
    neu = len(items) - pos - neg
    avg = sum(i["senti_score"] for i in items) / len(items)

    # 整体情绪分映射到 0-100
    score = clamp(50 + avg * 50)
    if score >= 58:
        overall = "偏多"
    elif score <= 42:
        overall = "偏空"
    else:
        overall = "中性"

    # 关键资讯：按情感绝对值 + 公告优先排序，取 top3
    ranked = sorted(items, key=lambda x: (x["kind"] == "notice", abs(x["senti_score"])),
                    reverse=True)
    top = ranked[:3]

    summary = (f"近期共采集 {len(items)} 条资讯，正面 {pos} / 中性 {neu} / 负面 {neg}，"
               f"综合情绪分 {safe_round(score,1)}，消息面整体【{overall}】。")

    return {
        "available": True, "score": safe_round(score, 1), "items": items,
        "pos": pos, "neg": neg, "neutral": neu, "overall": overall,
        "top": top, "summary": summary,
    }
