# -*- coding: utf-8 -*-
"""
综合研判：把技术面/资金面/消息面三维得分加权为综合分，输出
  - 未来 1-3 日走势的概率分布（看涨/震荡/看跌）
  - 明确的交易操作建议与仓位
  - 用 ATR + 支撑压力量化的入场区间、止损、目标价位
所有数值均有量化出处，便于审查复核。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as C
from .utils import clamp, fmt_pct, safe_round


def _volatility(df: pd.DataFrame) -> float:
    """近 20 日年化波动率（%），用于风险分级与仓位调整。"""
    if df is None or len(df) < 6:
        return float("nan")
    r = df["close"].pct_change().tail(20)
    return float(r.std() * math.sqrt(250) * 100)


def _trend_distribution(score: float) -> dict:
    """综合分 -> 看涨/震荡/看跌概率分布。越极端，震荡概率越低。"""
    x = (score - 50) / 50.0                       # -1..1
    up = 0.33 + 0.5 * x
    down = 0.33 - 0.5 * x
    side = 0.34 - 0.2 * abs(x)
    raw = [max(0.02, up), max(0.02, side), max(0.02, down)]
    s = sum(raw)
    up, side, down = (v / s for v in raw)
    return {"up": round(up, 3), "side": round(side, 3), "down": round(down, 3)}


def _price_levels(df: pd.DataFrame, snap: dict, sr: dict) -> dict:
    """量化关键价位：入场区间 / 止损 / 目标1 / 目标2 / 盈亏比。"""
    close = snap.get("close")
    atr = snap.get("ATR") or (close * 0.02 if close else None)
    if not close:
        return {}
    sup = sr.get("nearest_sup")
    res = sr.get("resistance") or []

    entry_low = round((sup * 1.005 if sup else close * 0.97), 2)
    entry_high = round(close * 1.005, 2)
    if entry_low > entry_high:
        entry_low, entry_high = round(close * 0.97, 2), entry_high

    # 止损：支撑下方与 ATR 通道下沿取更靠近价格者，控制单笔风险
    stop_candidates = [close - 1.8 * atr]
    if sup:
        stop_candidates.append(sup * 0.985)
    stop = round(max(stop_candidates), 2)          # 取较高者=更紧的止损
    stop = min(stop, round(close * 0.985, 2))      # 至少留 1.5% 缓冲

    target1 = res[0] if res else round(close + 2 * atr, 2)
    target2 = res[1] if len(res) > 1 else round(close + 3.5 * atr, 2)

    risk = max(close - stop, 1e-6)
    rr = (target1 - close) / risk
    return {
        "entry": [safe_round(entry_low, 2), safe_round(entry_high, 2)], "stop": safe_round(stop, 2),
        "target1": safe_round(target1, 2), "target2": safe_round(target2, 2),
        "risk_reward": safe_round(rr, 2),
        "stop_pct": safe_round((stop / close - 1) * 100, 2),
        "t1_pct": safe_round((target1 / close - 1) * 100, 2),
    }


def synthesize(df, snap, tech: dict, capital: dict, news: dict, is_mock: bool) -> dict:
    """生成综合研判结果。"""
    w = C.DIMENSION_WEIGHTS
    t, c, n = tech["score"], capital["score"], news["score"]
    composite = clamp(t * w["technical"] + c * w["capital"] + n * w["news"])

    dist = _trend_distribution(composite)
    vol = _volatility(df)
    if math.isnan(vol):
        risk_level = "未知"
    elif vol < 25:
        risk_level = "低"
    elif vol < 45:
        risk_level = "中"
    else:
        risk_level = "高"

    # —— 操作建议 ——
    action, action_note = "观望", "数据不足，建议观望"
    for lo, hi, act, note in C.ACTION_BANDS:
        if lo <= composite < hi:
            action, action_note = act, note
            break

    # 仓位：基准 × 风险调整
    pos = C.suggest_position(composite)
    if risk_level == "高":
        pos = int(pos * 0.7)
    divergence = max(t, c, n) - min(t, c, n)
    if divergence > 35:
        action_note += "；三维分歧较大，注意控制仓位"
        pos = int(pos * 0.8)
    if is_mock:
        action = "观望(演示)"
        action_note = "当前为模拟数据，仅演示流程，不构成任何建议"

    levels = _price_levels(df, snap, tech["support_resistance"])

    # —— 走势预测文字（约 200 字）——
    lead = max(dist, key=dist.get)
    lead_txt = {"up": "看涨", "side": "震荡", "down": "看跌"}[lead]
    prediction = (
        f"综合技术、资金、消息三个维度，未来 1-3 个交易日{lead_txt}概率最高。"
        f"概率分布为：看涨 {dist['up']*100:.0f}%、震荡 {dist['side']*100:.0f}%、看跌 {dist['down']*100:.0f}%。"
        f"技术面当前为【{tech['trend']['state']}】（得分 {t}），"
        f"资金面【{'净流入' if (capital.get('today_main') or 0) >= 0 else '净流出'}】（得分 {c}），"
        f"消息面【{news['overall']}】（得分 {n}）。"
        f"主要逻辑：{tech['summary'][:60]}…；"
        f"{('资金面' + capital['summary'][:40]) if capital.get('available') else '资金面数据有限'}。"
        f"年化波动率约 {fmt_pct(vol, with_sign=False)}，风险等级【{risk_level}】，"
        f"操作上{action_note}。"
    )

    return {
        "composite": safe_round(composite, 1),
        "dimension_scores": {"technical": t, "capital": c, "news": n},
        "distribution": dist, "lead": lead_txt,
        "volatility": safe_round(vol, 1), "risk_level": risk_level,
        "action": action, "action_note": action_note, "position": pos,
        "levels": levels, "prediction": prediction,
    }
