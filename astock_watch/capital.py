# -*- coding: utf-8 -*-
"""
资金面分析：主力资金流向力度与连续性、主力 vs 散户行为对比、北向资金倾向，
输出 0-100 资金面得分与文字研判。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import clamp, fmt_money, safe_round


def _streak(values: list) -> int:
    """从最后一天往前数：连续同号天数（正数=连续净流入，负数=连续净流出）。"""
    if not values:
        return 0
    sign = np.sign(values[-1])
    if sign == 0:
        return 0
    cnt = 0
    for v in reversed(values):
        if np.sign(v) == sign:
            cnt += 1
        else:
            break
    return int(cnt * sign)


def analyze(capital: pd.DataFrame, north: pd.DataFrame) -> dict:
    """资金面综合分析。capital/north 允许为 None。"""
    if capital is None or capital.empty:
        return {
            "available": False, "score": 50.0,
            "summary": "未获取到资金流数据（接口暂不可用或个股无沪深股通通道），资金面以中性计入。",
            "today_main": None, "streak": 0, "sum5": None, "sum10": None,
            "north": None, "rows": [],
        }

    df = capital.sort_values("date").reset_index(drop=True)
    main = df["main_net"].fillna(0).values
    today_main = float(main[-1])
    today_pct = float(df["main_pct"].iloc[-1]) if "main_pct" in df else np.nan
    sum5 = float(np.nansum(main[-5:]))
    sum10 = float(np.nansum(main[-10:]))
    streak = _streak(list(main[-10:]))

    # —— 评分：当日方向(40%) + 近5日累计(35%) + 连续性(25%) ——
    def _dir_score(x, scale):
        return clamp(50 + np.tanh(x / scale) * 50)
    s_today = _dir_score(today_main, 5e7)
    s_sum5 = _dir_score(sum5, 1.5e8)
    s_streak = clamp(50 + streak * 8)
    score = clamp(0.40 * s_today + 0.35 * s_sum5 + 0.25 * s_streak)

    # —— 主力 vs 散户 ——
    sm = float(df["sm_net"].iloc[-1]) if "sm_net" in df else np.nan
    if not np.isnan(sm):
        if today_main > 0 and sm < 0:
            behavior = "主力流入、散户流出，筹码向主力集中（偏多）"
        elif today_main < 0 and sm > 0:
            behavior = "主力流出、散户接盘，警惕派发（偏空）"
        elif today_main > 0:
            behavior = "主力与散户同向流入"
        else:
            behavior = "主力与散户同向流出"
    else:
        behavior = "散户数据缺失"

    # —— 北向 ——
    north_info = None
    if north is not None and not north.empty and len(north) >= 2:
        chg = float(north["north_hold_mv"].iloc[-1] - north["north_hold_mv"].iloc[0])
        trend = "增持" if chg > 0 else ("减持" if chg < 0 else "基本持平")
        north_info = {"trend": trend, "change_mv": safe_round(chg, 0),
                      "latest": safe_round(float(north["north_hold_mv"].iloc[-1]), 0)}
        score = clamp(score + (5 if chg > 0 else -5 if chg < 0 else 0))

    direction = "净流入" if today_main >= 0 else "净流出"
    streak_txt = (f"已连续 {abs(streak)} 日{'净流入' if streak > 0 else '净流出'}"
                  if streak else "流向反复")
    summary = (f"当日主力{direction} {fmt_money(abs(today_main))}"
               f"（占比 {safe_round(today_pct,2)}%），{streak_txt}；"
               f"近5日累计 {fmt_money(sum5)}、近10日累计 {fmt_money(sum10)}。{behavior}。"
               + (f" 北向资金近期{north_info['trend']}。" if north_info else ""))

    # 供图表使用的近 10 日明细
    rows = df.tail(10)[["date", "main_net", "pct_chg"]].to_dict("records")
    cum = np.cumsum([r["main_net"] for r in rows]).tolist()
    for r, c in zip(rows, cum):
        r["cum_main"] = c

    return {
        "available": True, "score": safe_round(score, 1), "summary": summary,
        "today_main": safe_round(today_main, 0), "today_pct": safe_round(today_pct, 2),
        "streak": streak, "sum5": safe_round(sum5, 0), "sum10": safe_round(sum10, 0),
        "behavior": behavior, "north": north_info, "rows": rows,
    }
