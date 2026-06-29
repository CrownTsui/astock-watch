# -*- coding: utf-8 -*-
"""
报告渲染：用 Jinja2 把分析结果与图表 JSON 渲染为独立 HTML。

图表数据经 sanitize 清洗 NaN/Inf 后用 json.dumps 注入模板，前端 Plotly.js
从 CDN 加载并 newPlot 渲染，生成的 HTML 双击即可在浏览器打开。
"""
from __future__ import annotations

import datetime as dt
import json
import os

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config as C
from .utils import fmt_money, fmt_pct, sanitize


def to_json(fig: dict) -> str:
    """图表字典 -> 可嵌入 HTML 的 JSON 字符串（NaN 已转 null）。"""
    if not fig:
        return "null"
    # replace 防止图表文本意外包含 </script> 破坏页面（XSS 加固）
    return json.dumps(sanitize(fig), ensure_ascii=False).replace("</", "<\\/")


def _env() -> Environment:
    base = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(
        loader=FileSystemLoader(base),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # 注册中文格式化过滤器，供模板直接使用
    env.filters["money"] = fmt_money
    env.filters["pct"] = lambda v: fmt_pct(v, with_sign=True)
    env.filters["pct0"] = lambda v: fmt_pct(v, with_sign=False)
    return env


def render(payload: dict) -> str:
    """渲染 HTML 字符串。"""
    tpl = _env().get_template("report.html.j2")
    return tpl.render(**payload)


def save(html: str, out_path: str) -> str:
    """写入 HTML 文件，返回绝对路径。"""
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def render_summary(items: list, comp_chart_json: str, out_dir: str = ".",
                   gen_date: str = None, offline: bool = False, assets_inline: dict = None) -> str:
    """渲染多股横向对比汇总页（按综合分降序），返回文件路径。"""
    items = sorted(items, key=lambda x: (x.get("composite") or 0), reverse=True)
    payload = {
        "cdn": C.CDN,
        "offline": offline,
        "assets": assets_inline or {},
        "color": {"up": C.COLOR_UP, "down": C.COLOR_DOWN, "neutral": C.COLOR_NEUTRAL},
        "items": items,
        "comp_chart": comp_chart_json,
        "has_mock": any(i.get("is_mock") for i in items),
        "gen_date": gen_date or (items[0].get("date") if items else ""),
        "gen_time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    html = _env().get_template("summary.html.j2").render(**payload)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return save(html, os.path.join(out_dir, f"astock_watch_summary_{stamp}.html"))
