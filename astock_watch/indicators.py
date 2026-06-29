# -*- coding: utf-8 -*-
"""
技术指标计算（纯 pandas/numpy 实现，不依赖 talib）。

所有公式对齐通达信/同花顺默认参数，保证与用户在行情软件上看到的数值一致。
输入：含 ['open','high','low','close','volume'] 列、按日期升序的 DataFrame。
输出：在原 DataFrame 上追加各指标列后返回。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


# ---------- 基础工具 ----------

def _ema(series: pd.Series, span: int) -> pd.Series:
    """指数移动平均（EMA），adjust=False 与通达信一致。"""
    return series.ewm(span=span, adjust=False).mean()


def _sma_cn(series: pd.Series, n: int, m: int) -> pd.Series:
    """中国式 SMA：Y = (m*X + (n-m)*Y_prev)/n，等价 ewm(alpha=m/n)。

    用于 KDJ、RSI 的平滑，是通达信 SMA(X,N,M) 函数的实现。
    """
    return series.ewm(alpha=m / n, adjust=False).mean()


# ---------- 各指标 ----------

def add_ma(df: pd.DataFrame) -> pd.DataFrame:
    """均线系统 MA5/10/20/60/120/250 与量均线。"""
    for p in C.MA_PERIODS:
        df[f"MA{p}"] = df["close"].rolling(p, min_periods=1).mean()
    for p in C.VOL_MA_PERIODS:
        df[f"VOLMA{p}"] = df["volume"].rolling(p, min_periods=1).mean()
    return df


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    """MACD：DIF=EMA12-EMA26，DEA=EMA9(DIF)，柱=(DIF-DEA)*2。"""
    ema_fast = _ema(df["close"], C.MACD_FAST)
    ema_slow = _ema(df["close"], C.MACD_SLOW)
    df["DIF"] = ema_fast - ema_slow
    df["DEA"] = _ema(df["DIF"], C.MACD_SIGNAL)
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2
    return df


def add_kdj(df: pd.DataFrame) -> pd.DataFrame:
    """KDJ：RSV 周期9，K/D 用中国式 SMA(·,3,1)，J=3K-2D。"""
    low_n = df["low"].rolling(C.KDJ_N, min_periods=1).min()
    high_n = df["high"].rolling(C.KDJ_N, min_periods=1).max()
    rng = (high_n - low_n).replace(0, np.nan)          # 防止除零（一字板）
    rsv = (df["close"] - low_n) / rng * 100
    rsv = rsv.fillna(50)                                # 无波动时 RSV 取中性 50
    df["K"] = _sma_cn(rsv, 3, 1)
    df["D"] = _sma_cn(df["K"], 3, 1)
    df["J"] = 3 * df["K"] - 2 * df["D"]
    return df


def add_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """RSI6/12/24：通达信 SMA 平滑（等价 Wilder，alpha=1/N）。"""
    diff = df["close"].diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    for p in C.RSI_PERIODS:
        avg_up = _sma_cn(up, p, 1)
        avg_down = _sma_cn(down, p, 1)
        rs_denom = (avg_up + avg_down).replace(0, np.nan)
        df[f"RSI{p}"] = (avg_up / rs_denom * 100).fillna(50)
    return df


def add_boll(df: pd.DataFrame) -> pd.DataFrame:
    """BOLL：中轨 MA20，上下轨 ±2 倍总体标准差（ddof=0 贴近通达信）。"""
    mid = df["close"].rolling(C.BOLL_N, min_periods=1).mean()
    std = df["close"].rolling(C.BOLL_N, min_periods=1).std(ddof=0)
    df["BOLL_MID"] = mid
    df["BOLL_UP"] = mid + C.BOLL_K * std
    df["BOLL_LOW"] = mid - C.BOLL_K * std
    return df


def add_wr(df: pd.DataFrame) -> pd.DataFrame:
    """威廉指标 WR：(HHV-C)/(HHV-LLV)*100，值大=超卖。"""
    for p in C.WR_PERIODS:
        hh = df["high"].rolling(p, min_periods=1).max()
        ll = df["low"].rolling(p, min_periods=1).min()
        rng = (hh - ll).replace(0, np.nan)
        df[f"WR{p}"] = ((hh - df["close"]) / rng * 100).fillna(50)
    return df


def add_dmi_atr(df: pd.DataFrame) -> pd.DataFrame:
    """DMI/ADX 趋势强度 + ATR 真实波幅（Wilder 平滑，alpha=1/N）。"""
    n = C.DMI_N
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high, prev_low = high.shift(1), low.shift(1)

    # 真实波幅 TR
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    # Wilder 平滑
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()

    df["ATR"] = atr
    df["PDI"] = plus_di
    df["MDI"] = minus_di
    df["ADX"] = adx
    return df


def add_extras(df: pd.DataFrame) -> pd.DataFrame:
    """衍生列：涨跌幅、量比（当日量/5日均量）。"""
    df["pct_chg"] = df["close"].pct_change() * 100
    if "VOLMA5" in df:
        df["vol_ratio"] = df["volume"] / df["VOLMA5"].replace(0, np.nan)
    return df


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """一次性计算全部指标。返回新的 DataFrame（不修改入参）。"""
    if df is None or df.empty:
        return df
    df = df.copy()
    # 保证类型与排序
    df = df.sort_values("date").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    add_ma(df)
    add_macd(df)
    add_kdj(df)
    add_rsi(df)
    add_boll(df)
    add_wr(df)
    add_dmi_atr(df)
    add_extras(df)
    return df


def latest_snapshot(df: pd.DataFrame) -> dict:
    """提取最后一根 K 线上的全部指标，供分析模块直接读取。"""
    if df is None or df.empty:
        return {}
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    keys = [
        "date", "open", "high", "low", "close", "volume", "pct_chg", "vol_ratio",
        "MA5", "MA10", "MA20", "MA60", "MA120", "MA250", "VOLMA5", "VOLMA10",
        "DIF", "DEA", "MACD", "K", "D", "J",
        "RSI6", "RSI12", "RSI24", "BOLL_UP", "BOLL_MID", "BOLL_LOW",
        "WR6", "WR10", "ATR", "PDI", "MDI", "ADX",
    ]
    snap = {k: (last[k] if k in last else None) for k in keys}
    # 附带上一根用于判断金叉死叉
    snap["_prev"] = {k: (prev[k] if k in prev else None)
                     for k in ["DIF", "DEA", "K", "D", "close", "J"]}
    return snap
