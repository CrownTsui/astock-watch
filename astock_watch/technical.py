# -*- coding: utf-8 -*-
"""
技术面分析：趋势研判、支撑/压力、指标信号、形态识别，并给出 0-100 技术面得分。

所有结论均由量化规则推导（均线排列、ADX、金叉死叉、背离、量价等），
每条信号都带有可解释的依据描述，避免主观臆断。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from scipy.signal import argrelextrema
    _HAS_SCIPY = True
except Exception:
    _HAS_SCIPY = False

from . import config as C
from .utils import clamp, safe_round


# ----------------------------- 趋势 -----------------------------

def _trend(df: pd.DataFrame, snap: dict) -> dict:
    """多头/空头/震荡，依据均线排列 + ADX + MA20 斜率。"""
    ma5, ma10, ma20, ma60 = snap.get("MA5"), snap.get("MA10"), snap.get("MA20"), snap.get("MA60")
    close = snap.get("close")
    adx = snap.get("ADX") or 0
    pdi, mdi = snap.get("PDI") or 0, snap.get("MDI") or 0

    # MA20 斜率（近5日）
    slope = np.nan
    if "MA20" in df and len(df) > 6:
        recent = df["MA20"].iloc[-6:].values
        if recent[0] and not np.isnan(recent[0]):
            slope = (recent[-1] - recent[0]) / abs(recent[0]) * 100

    bull = all(x is not None for x in [ma5, ma10, ma20]) and ma5 > ma10 > ma20
    bear = all(x is not None for x in [ma5, ma10, ma20]) and ma5 < ma10 < ma20

    if bull and (close or 0) >= (ma20 or 0):
        state, score = "多头", 78
    elif bear and (close or 0) <= (ma20 or 0):
        state, score = "空头", 25
    else:
        state, score = "震荡", 50

    # ADX 强化：趋势明确时放大得分偏离
    strong = adx >= C.ADX_TREND
    if strong and state == "多头" and pdi > mdi:
        score = min(90, score + 10)
    elif strong and state == "空头" and mdi > pdi:
        score = max(12, score - 10)

    desc = (f"均线呈{'多头排列' if bull else '空头排列' if bear else '交错纠缠'}，"
            f"ADX={safe_round(adx,1)}（{'趋势明确' if strong else '趋势偏弱/震荡'}），"
            f"+DI{'>' if pdi > mdi else '<'}-DI，MA20 斜率{safe_round(slope,2)}%。")
    return {"state": state, "score": clamp(score), "adx": safe_round(adx, 1),
            "slope": safe_round(slope, 2), "desc": desc}


# ----------------------------- 支撑/压力 -----------------------------

def _round_levels(price: float) -> list:
    """整数心理关口（按价格量级取档）。"""
    if price >= 100:
        step = 10
    elif price >= 30:
        step = 5
    elif price >= 10:
        step = 1
    else:
        step = 0.5
    base = round(price / step) * step
    return [round(base + k * step, 2) for k in (-2, -1, 0, 1, 2)]


def _support_resistance(df: pd.DataFrame, snap: dict) -> dict:
    """综合局部极值、布林轨、MA60、整数关口给出支撑/压力。"""
    cur = snap.get("close")
    win = df.tail(C.SR_LOOKBACK)
    levels = set()

    # 局部高低点
    if _HAS_SCIPY and len(win) > 10:
        highs = win["high"].values
        lows = win["low"].values
        for i in argrelextrema(highs, np.greater, order=5)[0]:
            levels.add(round(float(highs[i]), 2))
        for i in argrelextrema(lows, np.less, order=5)[0]:
            levels.add(round(float(lows[i]), 2))
    else:
        levels.add(round(float(win["high"].max()), 2))
        levels.add(round(float(win["low"].min()), 2))

    # 布林上下轨、MA60、整数关口
    for k in ["BOLL_UP", "BOLL_LOW", "MA60", "MA20"]:
        v = snap.get(k)
        if v and not np.isnan(v):
            levels.add(round(float(v), 2))
    levels.update(_round_levels(cur))

    res = sorted(l for l in levels if l > cur * 1.002)
    sup = sorted((l for l in levels if l < cur * 0.998), reverse=True)
    return {
        "current": safe_round(cur, 2),
        "resistance": [safe_round(x, 2) for x in res[:3]],
        "support": [safe_round(x, 2) for x in sup[:3]],
        "nearest_res": safe_round(res[0], 2) if res else None,
        "nearest_sup": safe_round(sup[0], 2) if sup else None,
    }


# ----------------------------- 指标信号 -----------------------------

def _macd_divergence(df: pd.DataFrame) -> str:
    """顶/底背离的简化检测：比较最近两个价格极值点对应的 DIF。"""
    if not _HAS_SCIPY or len(df) < 30:
        return ""
    seg = df.tail(60).reset_index(drop=True)
    hi_idx = argrelextrema(seg["high"].values, np.greater, order=4)[0]
    lo_idx = argrelextrema(seg["low"].values, np.less, order=4)[0]
    if len(hi_idx) >= 2:
        a, b = hi_idx[-2], hi_idx[-1]
        if seg["high"][b] > seg["high"][a] and seg["DIF"][b] < seg["DIF"][a]:
            return "顶背离"
    if len(lo_idx) >= 2:
        a, b = lo_idx[-2], lo_idx[-1]
        if seg["low"][b] < seg["low"][a] and seg["DIF"][b] > seg["DIF"][a]:
            return "底背离"
    return ""


def _signals(df: pd.DataFrame, snap: dict) -> list:
    """逐指标产出信号卡片：name/status/tone(pos|neg|neutral)/desc/score。"""
    out = []
    prev = snap.get("_prev", {})

    # MACD
    dif, dea, macd = snap.get("DIF"), snap.get("DEA"), snap.get("MACD")
    pdif, pdea = prev.get("DIF"), prev.get("DEA")
    if None not in (dif, dea, pdif, pdea):
        cross = "金叉" if (pdif <= pdea and dif > dea) else ("死叉" if (pdif >= pdea and dif < dea) else "")
        zone = "零轴上方" if dif > 0 else "零轴下方"
        div = _macd_divergence(df)
        if cross == "金叉":
            tone, sc = "pos", 75
        elif cross == "死叉":
            tone, sc = "neg", 28
        else:
            tone, sc = ("pos", 62) if macd and macd > 0 else ("neg", 40)
        if div == "顶背离":
            tone, sc = "neg", min(sc, 35)
        elif div == "底背离":
            tone, sc = "pos", max(sc, 62)
        status = (cross or ("红柱" if macd and macd > 0 else "绿柱")) + (f"·{div}" if div else "")
        out.append({"name": "MACD", "status": status, "tone": tone, "score": sc,
                    "desc": f"DIF={safe_round(dif,3)}，DEA={safe_round(dea,3)}，柱={safe_round(macd,3)}，{zone}。"})

    # KDJ
    k, d, j = snap.get("K"), snap.get("D"), snap.get("J")
    pk, pd_ = prev.get("K"), prev.get("D")
    if None not in (k, d):
        cross = "金叉" if (pk is not None and pk <= pd_ and k > d) else ("死叉" if (pk is not None and pk >= pd_ and k < d) else "")
        if k >= C.KDJ_OVERBOUGHT:
            zone, tone, sc = "超买", "neg", 35
        elif k <= C.KDJ_OVERSOLD:
            zone, tone, sc = "超卖", "pos", 65
        else:
            zone, tone, sc = "中性区", "neutral", 50
        if cross == "金叉":
            tone, sc = "pos", max(sc, 68)
        elif cross == "死叉":
            tone, sc = "neg", min(sc, 38)
        out.append({"name": "KDJ", "status": f"{cross or zone}", "tone": tone, "score": sc,
                    "desc": f"K={safe_round(k,1)}，D={safe_round(d,1)}，J={safe_round(j,1)}，处于{zone}。"})

    # RSI
    r6 = snap.get("RSI6")
    if r6 is not None:
        if r6 >= C.RSI_OVERBOUGHT:
            tone, sc, st = "neg", 38, "超买"
        elif r6 <= C.RSI_OVERSOLD:
            tone, sc, st = "pos", 62, "超卖"
        elif r6 >= 55:
            tone, sc, st = "pos", 64, "偏强"
        elif r6 <= 45:
            tone, sc, st = "neg", 44, "偏弱"
        else:
            tone, sc, st = "neutral", 52, "中性"
        out.append({"name": "RSI", "status": st, "tone": tone, "score": sc,
                    "desc": f"RSI6={safe_round(r6,1)}，RSI12={safe_round(snap.get('RSI12'),1)}，RSI24={safe_round(snap.get('RSI24'),1)}。"})

    # WR
    wr6 = snap.get("WR6")
    if wr6 is not None:
        if wr6 >= C.WR_OVERSOLD:
            tone, sc, st = "pos", 60, "超卖区"
        elif wr6 <= C.WR_OVERBOUGHT:
            tone, sc, st = "neg", 42, "超买区"
        else:
            tone, sc, st = "neutral", 50, "中性"
        out.append({"name": "WR", "status": st, "tone": tone, "score": sc,
                    "desc": f"WR6={safe_round(wr6,1)}（值大超卖、值小超买）。"})

    # 量价
    vr = snap.get("vol_ratio")
    pct = snap.get("pct_chg") or 0
    if vr is not None and not np.isnan(vr):
        if vr >= C.VOL_SURGE and pct > 0:
            tone, sc, st = "pos", 70, "放量上涨"
        elif vr >= C.VOL_SURGE and pct < 0:
            tone, sc, st = "neg", 32, "放量下跌"
        elif vr <= C.VOL_SHRINK and pct > 0:
            tone, sc, st = "neutral", 55, "缩量上涨"
        elif vr <= C.VOL_SHRINK and pct < 0:
            tone, sc, st = "pos", 56, "缩量下跌"
        else:
            tone, sc, st = "neutral", 50, "量能正常"
        out.append({"name": "量价", "status": st, "tone": tone, "score": sc,
                    "desc": f"量比={safe_round(vr,2)}，当日涨跌={safe_round(pct,2)}%。"})

    # BOLL 位置
    up, mid, low = snap.get("BOLL_UP"), snap.get("BOLL_MID"), snap.get("BOLL_LOW")
    close = snap.get("close")
    if None not in (up, low, close) and up > low:
        pos = (close - low) / (up - low)            # 0=下轨 1=上轨
        if pos >= 0.8:
            tone, sc, st = "pos", 64, "贴近上轨(强)"
        elif pos <= 0.2:
            tone, sc, st = "neg", 44, "贴近下轨(弱)"
        else:
            tone, sc, st = "neutral", 52, "中轨附近"
        out.append({"name": "BOLL", "status": st, "tone": tone, "score": sc,
                    "desc": f"价格位于布林带{safe_round(pos*100,0)}%分位（上轨{safe_round(up,2)}/下轨{safe_round(low,2)}）。"})
    return out


# ----------------------------- 形态 -----------------------------

def _patterns(df: pd.DataFrame, snap: dict) -> list:
    """经典形态的启发式识别（仅供参考）。"""
    if not _HAS_SCIPY or len(df) < 40:
        return []
    seg = df.tail(80).reset_index(drop=True)
    out = []
    hi = argrelextrema(seg["high"].values, np.greater, order=4)[0]
    lo = argrelextrema(seg["low"].values, np.less, order=4)[0]

    if len(lo) >= 2:
        l1, l2 = seg["low"][lo[-2]], seg["low"][lo[-1]]
        if abs(l1 - l2) / max(l1, 1e-9) < 0.03 and lo[-1] - lo[-2] >= 5:
            out.append({"name": "双底(W底)", "tone": "pos",
                        "desc": f"近期两个低点{safe_round(l1,2)}/{safe_round(l2,2)}接近，存在筑底反弹结构。"})
    if len(hi) >= 2:
        h1, h2 = seg["high"][hi[-2]], seg["high"][hi[-1]]
        if abs(h1 - h2) / max(h1, 1e-9) < 0.03 and hi[-1] - hi[-2] >= 5:
            out.append({"name": "双顶(M顶)", "tone": "neg",
                        "desc": f"近期两个高点{safe_round(h1,2)}/{safe_round(h2,2)}接近，警惕见顶回落。"})
    if len(hi) >= 2 and len(lo) >= 2:
        h_down = seg["high"][hi[-1]] < seg["high"][hi[-2]]
        l_up = seg["low"][lo[-1]] > seg["low"][lo[-2]]
        if h_down and l_up:
            out.append({"name": "对称三角形(收敛)", "tone": "neutral",
                        "desc": "高点降低、低点抬高，多空趋于平衡，方向选择临近。"})
        elif (not h_down) and l_up:
            out.append({"name": "上升三角形", "tone": "pos",
                        "desc": "高点持平、低点抬高，多方占优，向上突破概率较大。"})
    return out[:2]


# ----------------------------- 主入口 -----------------------------

def analyze(df: pd.DataFrame, snap: dict) -> dict:
    """技术面综合分析，返回结构化结果 + 加权得分。"""
    trend = _trend(df, snap)
    sr = _support_resistance(df, snap)
    signals = _signals(df, snap)
    patterns = _patterns(df, snap)

    # —— 子项得分映射到 TECH_SUB_WEIGHTS ——
    sig_map = {s["name"]: s["score"] for s in signals}
    sub = {
        "trend": trend["score"],
        "macd": sig_map.get("MACD", 50),
        "kdj": sig_map.get("KDJ", 50),
        "rsi": sig_map.get("RSI", 50),
        "boll": sig_map.get("BOLL", 50),
        "volume": sig_map.get("量价", 50),
        "momentum": clamp(50 + (df["close"].pct_change(5).iloc[-1] * 100 if len(df) > 6 else 0) * 3),
    }
    score = clamp(sum(sub[k] * w for k, w in C.TECH_SUB_WEIGHTS.items()))

    pos = sum(1 for s in signals if s["tone"] == "pos")
    neg = sum(1 for s in signals if s["tone"] == "neg")
    summary = (f"当前处于【{trend['state']}】格局。{trend['desc']} "
               f"指标信号偏多 {pos} 项、偏空 {neg} 项。"
               f"上方最近压力 {sr['nearest_res']}，下方最近支撑 {sr['nearest_sup']}。"
               + (f" 形态参考：{patterns[0]['name']}。" if patterns else ""))

    return {
        "trend": trend, "support_resistance": sr, "signals": signals,
        "patterns": patterns, "sub_scores": {k: safe_round(v, 1) for k, v in sub.items()},
        "score": safe_round(score, 1), "summary": summary,
    }
