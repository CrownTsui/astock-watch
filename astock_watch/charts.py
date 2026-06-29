# -*- coding: utf-8 -*-
"""
图表生成层：输出 Plotly.js 可直接消费的 figure 字典 {"data":[...], "layout":{...}}。

不依赖 plotly Python 包 —— Python 端只负责把真实数据组织成 trace/layout 结构，
HTML 端通过 Plotly.js CDN 调 Plotly.newPlot 渲染。好处：零安装、完全交互式
（缩放/平移/十字光标/tooltip）、报告可离线打开。
"""
from __future__ import annotations

import pandas as pd

from . import config as C

_FONT = {"family": "Noto Sans SC, Microsoft YaHei, sans-serif", "size": 12, "color": "#333"}
_PLOT_BG = "#ffffff"


def _base_layout(height: int, title: str = "") -> dict:
    return {
        "height": height, "title": {"text": title, "font": {"size": 15}},
        "paper_bgcolor": _PLOT_BG, "plot_bgcolor": _PLOT_BG, "font": _FONT,
        "margin": {"l": 50, "r": 30, "t": 40, "b": 30},
        "hovermode": "x unified", "dragmode": "zoom",
        "legend": {"orientation": "h", "y": 1.02, "x": 0, "font": {"size": 11}},
    }


def _bar_colors(cond) -> list:
    return [C.COLOR_UP if x else C.COLOR_DOWN for x in cond]


# ============================ 技术主图（联动多子图） ============================

def main_chart(df: pd.DataFrame, max_bars: int = 120) -> dict:
    """K线+MA+BOLL / 成交量 / MACD / KDJ / RSI 五段共享 x 轴联动子图。"""
    d = df.tail(max_bars).reset_index(drop=True)
    x = d["date"].tolist()

    def col(name):
        return d[name].tolist() if name in d else []

    data = []
    # —— 主图：K线 ——
    data.append({
        "type": "candlestick", "name": "K线", "x": x,
        "open": col("open"), "high": col("high"), "low": col("low"), "close": col("close"),
        "increasing": {"line": {"color": C.COLOR_UP}, "fillcolor": C.COLOR_UP},
        "decreasing": {"line": {"color": C.COLOR_DOWN}, "fillcolor": C.COLOR_DOWN},
        "yaxis": "y", "xaxis": "x",
    })
    ma_colors = {"MA5": "#f0932b", "MA10": "#3498db", "MA20": "#9b59b6", "MA60": "#7f8c8d"}
    for ma, cl in ma_colors.items():
        if ma in d:
            data.append({"type": "scatter", "mode": "lines", "name": ma, "x": x,
                         "y": col(ma), "line": {"color": cl, "width": 1}, "yaxis": "y", "xaxis": "x"})
    for b, cl in (("BOLL_UP", "#95a5a6"), ("BOLL_LOW", "#95a5a6")):
        if b in d:
            data.append({"type": "scatter", "mode": "lines", "name": b.replace("BOLL_", "BOLL·"),
                         "x": x, "y": col(b), "line": {"color": cl, "width": 1, "dash": "dot"},
                         "yaxis": "y", "xaxis": "x", "showlegend": False})

    # —— 成交量 ——
    vcond = (d["close"] >= d["open"])
    data.append({"type": "bar", "name": "成交量", "x": x, "y": col("volume"),
                 "marker": {"color": _bar_colors(vcond)}, "yaxis": "y2", "xaxis": "x", "showlegend": False})
    for vm, cl in (("VOLMA5", "#f0932b"), ("VOLMA10", "#3498db")):
        if vm in d:
            data.append({"type": "scatter", "mode": "lines", "name": vm, "x": x, "y": col(vm),
                         "line": {"color": cl, "width": 1}, "yaxis": "y2", "xaxis": "x", "showlegend": False})

    # —— MACD ——
    if "MACD" in d:
        mcond = (d["MACD"] >= 0)
        data.append({"type": "bar", "name": "MACD柱", "x": x, "y": col("MACD"),
                     "marker": {"color": _bar_colors(mcond)}, "yaxis": "y3", "xaxis": "x", "showlegend": False})
        data.append({"type": "scatter", "mode": "lines", "name": "DIF", "x": x, "y": col("DIF"),
                     "line": {"color": "#e67e22", "width": 1}, "yaxis": "y3", "xaxis": "x", "showlegend": False})
        data.append({"type": "scatter", "mode": "lines", "name": "DEA", "x": x, "y": col("DEA"),
                     "line": {"color": "#2980b9", "width": 1}, "yaxis": "y3", "xaxis": "x", "showlegend": False})

    # —— KDJ ——
    for kk, cl in (("K", "#e67e22"), ("D", "#2980b9"), ("J", "#9b59b6")):
        if kk in d:
            data.append({"type": "scatter", "mode": "lines", "name": kk, "x": x, "y": col(kk),
                         "line": {"color": cl, "width": 1}, "yaxis": "y4", "xaxis": "x", "showlegend": False})

    # —— RSI ——
    for rr, cl in (("RSI6", "#e74c3c"), ("RSI12", "#27ae60"), ("RSI24", "#2980b9")):
        if rr in d:
            data.append({"type": "scatter", "mode": "lines", "name": rr, "x": x, "y": col(rr),
                         "line": {"color": cl, "width": 1}, "yaxis": "y5", "xaxis": "x", "showlegend": False})

    layout = _base_layout(940)
    layout.update({
        "xaxis": {"type": "category", "domain": [0, 1], "anchor": "y5",
                  "rangeslider": {"visible": False}, "showgrid": True, "gridcolor": "#f0f0f0",
                  "nticks": 12, "tickangle": -30, "tickfont": {"size": 10}},
        "yaxis":  {"domain": [0.50, 1.0], "title": {"text": "价格"}, "gridcolor": "#f0f0f0", "anchor": "x"},
        "yaxis2": {"domain": [0.36, 0.46], "title": {"text": "量"}, "gridcolor": "#f7f7f7", "anchor": "x"},
        "yaxis3": {"domain": [0.24, 0.34], "title": {"text": "MACD"}, "gridcolor": "#f7f7f7", "anchor": "x"},
        "yaxis4": {"domain": [0.12, 0.22], "title": {"text": "KDJ"}, "gridcolor": "#f7f7f7", "anchor": "x"},
        "yaxis5": {"domain": [0.0, 0.10], "title": {"text": "RSI"}, "gridcolor": "#f7f7f7", "anchor": "x"},
    })
    return {"data": data, "layout": layout}


# ============================ 资金流 ============================

def capital_chart(rows: list) -> dict:
    """近 10 日主力净流入柱状图 + 累计净流入折线（双轴）。"""
    if not rows:
        return {}
    x = [r["date"] for r in rows]
    main = [r["main_net"] for r in rows]
    cum = [r.get("cum_main") for r in rows]
    cond = [v >= 0 for v in main]
    data = [
        {"type": "bar", "name": "主力净流入", "x": x, "y": main,
         "marker": {"color": _bar_colors(cond)}, "yaxis": "y"},
        {"type": "scatter", "mode": "lines+markers", "name": "累计净流入", "x": x, "y": cum,
         "line": {"color": "#8e44ad", "width": 2}, "yaxis": "y2"},
    ]
    layout = _base_layout(330, "近10日主力资金流向（元）")
    layout.update({
        "xaxis": {"type": "category", "tickfont": {"size": 10}, "gridcolor": "#f0f0f0"},
        "yaxis": {"title": {"text": "单日净额"}, "gridcolor": "#f0f0f0", "zeroline": True, "zerolinecolor": "#ccc"},
        "yaxis2": {"title": {"text": "累计"}, "overlaying": "y", "side": "right", "showgrid": False},
    })
    return {"data": data, "layout": layout}


def north_chart(north: pd.DataFrame) -> dict:
    """北向持股市值变化折线。"""
    if north is None or north.empty:
        return {}
    data = [{"type": "scatter", "mode": "lines", "name": "北向持股市值",
             "x": north["date"].tolist(), "y": north["north_hold_mv"].tolist(),
             "fill": "tozeroy", "line": {"color": "#16a085"}}]
    layout = _base_layout(280, "北向资金持股市值变化（元）")
    layout.update({"xaxis": {"type": "category", "tickfont": {"size": 10}},
                   "yaxis": {"gridcolor": "#f0f0f0"}})
    return {"data": data, "layout": layout}


# ============================ 消息面 / 雷达 ============================

def sentiment_pie(pos: int, neu: int, neg: int) -> dict:
    """情感分布饼图。"""
    data = [{
        "type": "pie", "labels": ["正面", "中性", "负面"], "values": [pos, neu, neg],
        "marker": {"colors": [C.COLOR_UP, C.COLOR_NEUTRAL, C.COLOR_DOWN]},
        "textinfo": "label+percent", "hole": 0.45, "sort": False,
    }]
    layout = _base_layout(300, "消息情感分布")
    layout.update({"showlegend": True})
    return {"data": data, "layout": layout}


def radar_chart(technical: float, capital: float, news: float) -> dict:
    """技术/资金/消息三维综合评分雷达图。"""
    cats = ["技术面", "资金面", "消息面"]
    vals = [technical, capital, news]
    data = [{
        "type": "scatterpolar", "r": vals + [vals[0]], "theta": cats + [cats[0]],
        "fill": "toself", "name": "评分",
        "line": {"color": "#2980b9"}, "fillcolor": "rgba(41,128,185,0.35)",
    }]
    layout = _base_layout(320, "三维综合评分雷达")
    layout.update({
        "polar": {"radialaxis": {"visible": True, "range": [0, 100], "tickfont": {"size": 10}}},
        "showlegend": False,
    })
    return {"data": data, "layout": layout}


# ============================ 回测 ============================

def equity_chart(dates: list, equity: list, benchmark: list) -> dict:
    """评分策略净值 vs 买入持有基准。"""
    if not equity:
        return {}
    data = [
        {"type": "scatter", "mode": "lines", "name": "评分策略净值", "x": dates, "y": equity,
         "line": {"color": C.COLOR_UP, "width": 2}},
        {"type": "scatter", "mode": "lines", "name": "买入持有", "x": dates, "y": benchmark,
         "line": {"color": "#7f8c8d", "width": 1.5, "dash": "dot"}},
    ]
    layout = _base_layout(320, "评分策略回测净值 vs 买入持有")
    layout.update({"xaxis": {"type": "category", "nticks": 10, "tickfont": {"size": 10}},
                   "yaxis": {"title": {"text": "净值(初始=1)"}, "gridcolor": "#f0f0f0"}})
    return {"data": data, "layout": layout}


def calibration_chart(calib: list) -> dict:
    """评分分档 vs 未来收益（柱）+ 胜率（折线，右轴）。"""
    if not calib:
        return {}
    x = [c["bucket"] for c in calib]
    y = [c["avg_ret"] for c in calib]
    wr = [c["win_rate"] for c in calib]
    colors = [C.COLOR_UP if (v or 0) >= 0 else C.COLOR_DOWN for v in y]
    data = [
        {"type": "bar", "name": "未来N日平均收益%", "x": x, "y": y,
         "marker": {"color": colors}, "yaxis": "y"},
        {"type": "scatter", "mode": "lines+markers", "name": "胜率%", "x": x, "y": wr,
         "line": {"color": "#2980b9"}, "yaxis": "y2"},
    ]
    layout = _base_layout(300, "评分分档 vs 未来收益（校准）")
    layout.update({
        "xaxis": {"type": "category", "tickfont": {"size": 10}},
        "yaxis": {"title": {"text": "平均收益%"}, "gridcolor": "#f0f0f0", "zeroline": True, "zerolinecolor": "#ccc"},
        "yaxis2": {"title": {"text": "胜率%"}, "overlaying": "y", "side": "right", "range": [0, 100], "showgrid": False},
    })
    return {"data": data, "layout": layout}


# ============================ 多股对比 ============================

def comparison_chart(items: list) -> dict:
    """多支股票三维 + 综合评分分组柱状对比。"""
    if not items:
        return {}
    names = [i["name"] for i in items]
    series = [("技术面", "technical", "#3498db"), ("资金面", "capital", "#e67e22"),
              ("消息面", "news", "#9b59b6"), ("综合", "composite", "#2c3e50")]
    data = [{"type": "bar", "name": nm, "x": names, "y": [i.get(key) for i in items],
             "marker": {"color": cl}} for nm, key, cl in series]
    layout = _base_layout(360, "多股三维评分横向对比")
    layout.update({"barmode": "group", "xaxis": {"type": "category"},
                   "yaxis": {"range": [0, 100], "title": {"text": "评分"}, "gridcolor": "#f0f0f0"}})
    return {"data": data, "layout": layout}
