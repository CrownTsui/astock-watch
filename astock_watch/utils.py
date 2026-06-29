# -*- coding: utf-8 -*-
"""
通用工具：股票代码标准化、网络重试、NaN 清洗（供 JSON 序列化）、
数字格式化、日志。所有模块共享。
"""
from __future__ import annotations

import logging
import math
import time
from functools import wraps
from typing import Any, Callable

import numpy as np

logger = logging.getLogger("astock_watch")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ----------------------------- 股票代码 -----------------------------

def normalize_code(raw: str) -> dict:
    """把用户输入的代码标准化为统一结构。

    支持 '600519'、'sh600519'、'600519.SH'、'000858' 等写法。
    A 股规则（简化但覆盖主流）：
      6/9 开头 -> 上交所(sh)，0/2/3 开头 -> 深交所(sz)，4/8 开头 -> 北交所(bj)。
    返回包含 code/market/secid/symbol 的字典；secid 用于东方财富接口。
    """
    s = "".join(ch for ch in str(raw).strip().upper() if ch.isdigit())
    if len(s) != 6:
        raise ValueError(f"非法股票代码: {raw!r}，应为 6 位数字")

    head = s[0]
    is_fund = False
    if head == "5":                        # 沪市基金/ETF（如 518880 黄金ETF）
        market, secid_pre, is_fund = "sh", "1", True
    elif head == "1":                      # 深市基金/ETF（如 159915 创业板ETF）
        market, secid_pre, is_fund = "sz", "0", True
    elif head in ("6", "9"):               # 沪市股票 / B股
        market, secid_pre = "sh", "1"
    elif head in ("0", "2", "3"):          # 深市股票（含创业板/B股）
        market, secid_pre = "sz", "0"
    elif head in ("4", "8"):               # 北交所（东财归类同深市前缀）
        market, secid_pre = "bj", "0"
    else:
        market, secid_pre = "sz", "0"

    return {
        "code": s,                          # 纯 6 位
        "market": market,                   # sh / sz / bj
        "symbol": f"{market}{s}",           # sh600519
        "secid": f"{secid_pre}.{s}",        # 东财 secid: 1.600519
        "is_fund": is_fund,                 # 是否 ETF/基金
    }


# ----------------------------- 网络重试 -----------------------------

def retry(times: int = 2, backoff: float = 1.5, default: Any = None):
    """简单重试装饰器：失败时退避重试，最终仍失败则返回 default 并记录警告。

    用于包裹每个数据抓取函数，保证单点失败不会中断整体流程。
    """
    def deco(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for i in range(times + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:  # noqa: BLE001  —— 抓取层需要兜住一切异常
                    last_err = e
                    if i < times:
                        time.sleep(backoff * (i + 1))
            logger.warning("[%s] 多次重试仍失败: %s", func.__name__, last_err)
            return default
        return wrapper
    return deco


# ----------------------------- NaN 清洗 -----------------------------

def sanitize(obj: Any) -> Any:
    """递归把 NaN/Inf/numpy 标量转换为可被 json.dumps 接受的纯 Python 值。

    Plotly.js 解析 JSON 时遇到裸 NaN 会抛错；NaN -> None（图表上呈现为断点）。
    """
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    # 兜底：其他类型转字符串，避免序列化失败
    try:
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except (TypeError, ValueError):
        return str(obj)


# ----------------------------- 格式化 -----------------------------

def fmt_money(value: float) -> str:
    """金额按亿/万自动换算，中文易读。输入单位：元。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(v):
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e8:
        return f"{sign}{a / 1e8:.2f}亿"
    if a >= 1e4:
        return f"{sign}{a / 1e4:.2f}万"
    return f"{sign}{a:.0f}"


def fmt_pct(value: float, with_sign: bool = True) -> str:
    """百分比格式化，保留两位小数。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(v):
        return "—"
    s = f"{v:+.2f}%" if with_sign else f"{v:.2f}%"
    return s


def safe_round(value: Any, n: int = 2) -> Any:
    """安全四舍五入，非数返回 None。"""
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, n)
    except (TypeError, ValueError):
        return None


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """把数值夹紧到 [lo, hi]。用于评分边界保护。"""
    return max(lo, min(hi, value))
