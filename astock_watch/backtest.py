# -*- coding: utf-8 -*-
"""
评分模型回测与校准。

两个目的：
  1) 校准：检验"技术评分越高 → 未来收益越好"是否成立，输出信息系数 IC
     与分档（看空/中性/偏多/强多）的未来平均收益、胜率，给模型可信度背书。
  2) 策略回测：按评分驱动持仓（评分上穿买入阈值持仓、下穿卖出阈值空仓），
     计算累计/年化收益、Sharpe、最大回撤，与"买入持有"基准对比。

严格无前视偏差：
  - 第 t 日技术评分只用截至第 t 日的指标（指标本身为滚动计算）；
  - 持仓信号用 **前一日** 评分（shift(1)），即当日收盘出信号、次日才生效；
  - 未来收益 fwd 仅用于"事后统计校准"，绝不参与交易决策。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .utils import safe_round


def tech_score_series(df: pd.DataFrame) -> pd.Series:
    """向量化逐日技术评分，口径与 technical 子项一致（趋势/MACD/KDJ/RSI/BOLL/量价/动量）。"""
    idx = df.index
    g = lambda name: df[name] if name in df else pd.Series(np.nan, index=idx)

    # 趋势：均线排列 + ADX 强化
    ma5, ma10, ma20 = g("MA5"), g("MA10"), g("MA20")
    bull = (ma5 > ma10) & (ma10 > ma20)
    bear = (ma5 < ma10) & (ma10 < ma20)
    trend = pd.Series(50.0, index=idx)
    trend[bull & (g("close") >= ma20)] = 75
    trend[bear & (g("close") <= ma20)] = 28
    adx_ok = g("ADX") >= C.ADX_TREND
    trend[adx_ok & bull & (g("PDI") > g("MDI"))] += 10
    trend[adx_ok & bear & (g("MDI") > g("PDI"))] -= 10

    # MACD：金叉/死叉 + 零轴
    dif, dea, macd = g("DIF"), g("DEA"), g("MACD")
    gold = (dif.shift(1) <= dea.shift(1)) & (dif > dea)
    dead = (dif.shift(1) >= dea.shift(1)) & (dif < dea)
    m = pd.Series(50.0, index=idx)
    m[macd > 0] = 62
    m[macd <= 0] = 40
    m[gold] = 75
    m[dead] = 28

    # KDJ
    k, d = g("K"), g("D")
    kdj = pd.Series(50.0, index=idx)
    kdj[k >= C.KDJ_OVERBOUGHT] = 35
    kdj[k <= C.KDJ_OVERSOLD] = 65
    kdj[(k.shift(1) <= d.shift(1)) & (k > d)] = 68
    kdj[(k.shift(1) >= d.shift(1)) & (k < d)] = 38

    # RSI
    r6 = g("RSI6")
    rsi = pd.Series(52.0, index=idx)
    rsi[(r6 > 55) & (r6 < C.RSI_OVERBOUGHT)] = 64
    rsi[(r6 < 45) & (r6 > C.RSI_OVERSOLD)] = 44
    rsi[r6 >= C.RSI_OVERBOUGHT] = 38
    rsi[r6 <= C.RSI_OVERSOLD] = 62

    # BOLL 位置
    rng = (g("BOLL_UP") - g("BOLL_LOW")).replace(0, np.nan)
    pos = (g("close") - g("BOLL_LOW")) / rng
    boll = pd.Series(52.0, index=idx)
    boll[pos >= 0.8] = 64
    boll[pos <= 0.2] = 44

    # 量价
    vr, pct = g("vol_ratio"), g("pct_chg")
    volp = pd.Series(50.0, index=idx)
    volp[(vr >= C.VOL_SURGE) & (pct > 0)] = 70
    volp[(vr >= C.VOL_SURGE) & (pct < 0)] = 32
    volp[(vr <= C.VOL_SHRINK) & (pct < 0)] = 56

    # 动量
    mom = (50 + g("close").pct_change(5) * 100 * 3).clip(0, 100).fillna(50)

    w = C.TECH_SUB_WEIGHTS
    total = (trend * w["trend"] + m * w["macd"] + kdj * w["kdj"] + rsi * w["rsi"]
             + boll * w["boll"] + volp * w["volume"] + mom * w["momentum"])
    return total.fillna(50).clip(0, 100)


def _metrics(daily_ret: pd.Series, equity: pd.Series) -> dict:
    """绩效指标：累计/年化收益、Sharpe、最大回撤。"""
    n = max(len(daily_ret), 1)
    final = float(equity.iloc[-1])
    ann = final ** (250 / n) - 1 if final > 0 else -1
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(250)) if daily_ret.std() > 0 else 0.0
    mdd = float(((equity / equity.cummax()) - 1).min())
    return {"total": safe_round((final - 1) * 100, 2), "annual": safe_round(ann * 100, 2),
            "sharpe": safe_round(sharpe, 2), "mdd": safe_round(mdd * 100, 2)}


def run_backtest(df: pd.DataFrame, hold_days: int = None,
                 buy_th: float = None, sell_th: float = None) -> dict:
    """对一支股票运行评分校准 + 策略回测。"""
    if df is None or len(df) < C.BACKTEST_MIN_BARS:
        return {"available": False, "reason": "K线不足，跳过回测"}
    hold_days = hold_days or C.BACKTEST_HOLD_DAYS
    buy_th = buy_th or C.BACKTEST_BUY_TH
    sell_th = sell_th or C.BACKTEST_SELL_TH

    d = df.reset_index(drop=True)
    scores = tech_score_series(d)
    close = d["close"]
    fwd = close.shift(-hold_days) / close - 1          # 未来 hold_days 收益（仅校准统计用）

    # —— 信息系数 IC：评分与未来收益的相关性 ——
    valid = fwd.notna() & scores.notna()
    ic = None
    if valid.sum() > 5 and scores[valid].std() > 0 and fwd[valid].std() > 0:
        ic = safe_round(float(np.corrcoef(scores[valid], fwd[valid])[0, 1]), 3)

    # —— 分档校准 ——
    buckets = [(0, 45, "看空 <45"), (45, 55, "中性 45-55"),
               (55, 65, "偏多 55-65"), (65, 101, "强多 ≥65")]
    calibration = []
    for lo, hi, name in buckets:
        mask = (scores >= lo) & (scores < hi) & fwd.notna()
        if mask.sum() > 0:
            calibration.append({"bucket": name, "n": int(mask.sum()),
                                "avg_ret": safe_round(fwd[mask].mean() * 100, 2),
                                "win_rate": safe_round((fwd[mask] > 0).mean() * 100, 1)})
        else:
            calibration.append({"bucket": name, "n": 0, "avg_ret": None, "win_rate": None})

    # —— 策略：前一日评分驱动持仓（无前视）——
    daily_ret = close.pct_change().fillna(0)
    sig = scores.shift(1)
    pos = np.zeros(len(d))
    holding = False
    for i in range(len(d)):
        s = sig.iloc[i]
        if not np.isnan(s):
            if not holding and s >= buy_th:
                holding = True
            elif holding and s < sell_th:
                holding = False
        pos[i] = 1.0 if holding else 0.0
    pos = pd.Series(pos, index=d.index)

    strat_ret = pos * daily_ret
    equity = (1 + strat_ret).cumprod()
    bench = (1 + daily_ret).cumprod()
    trades = int((pos.diff() > 0).sum())

    # 持仓段胜率
    seg_rets, seg = [], None
    for i in range(len(d)):
        if pos.iloc[i] == 1 and seg is None:
            seg = close.iloc[i]
        elif pos.iloc[i] == 0 and seg is not None:
            seg_rets.append(close.iloc[i] / seg - 1)
            seg = None
    win_rate = safe_round(np.mean([r > 0 for r in seg_rets]) * 100, 1) if seg_rets else None

    m = _metrics(strat_ret, equity)
    m["trades"] = trades
    m["win_rate"] = win_rate

    return {
        "available": True, "hold_days": hold_days, "buy_th": buy_th, "sell_th": sell_th,
        "ic": ic, "calibration": calibration,
        "dates": d["date"].tolist(),
        "equity": [safe_round(x, 4) for x in equity.tolist()],
        "benchmark": [safe_round(x, 4) for x in bench.tolist()],
        "strategy": m, "bench": _metrics(daily_ret, bench),
        "summary": _summary(ic, m, _metrics(daily_ret, bench), calibration),
    }


def _summary(ic, strat, bench, calib) -> str:
    """回测文字结论。"""
    ic_txt = (f"评分与未来{C.BACKTEST_HOLD_DAYS}日收益的信息系数 IC={ic}"
              f"（{'正向有效' if (ic or 0) > 0.03 else '弱/无显著' }）") if ic is not None else "IC 不可用"
    excess = (strat["total"] or 0) - (bench["total"] or 0)
    return (f"{ic_txt}。策略累计收益 {strat['total']}%、年化 {strat['annual']}%、"
            f"Sharpe {strat['sharpe']}、最大回撤 {strat['mdd']}%，"
            f"相对买入持有{'跑赢' if excess >= 0 else '跑输'} {abs(safe_round(excess,2))}%；"
            f"共 {strat['trades']} 次交易，段胜率 {strat['win_rate']}%。")
