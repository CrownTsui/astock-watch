# -*- coding: utf-8 -*-
"""
StockAnalyzer：盯盘分析编排器。

串联 数据抓取 -> 指标计算 -> 技术/资金/消息分析 -> 综合研判 -> 图表 -> HTML 报告。
每个阶段独立 try/except，任一环节异常都不会中断整体流程（缺失部分以中性/占位降级）。
"""
from __future__ import annotations

import datetime as dt
import os

from . import backtest as backtest_mod
from . import capital as capital_mod
from . import charts
from . import config as C
from . import indicators
from . import news as news_mod
from . import report as report_mod
from . import scoring
from . import technical
from .data_fetcher import DataFetcher
from .utils import fmt_money, logger, safe_round


def _resolve_offline_assets(offline: bool) -> dict:
    """offline 时返回内联资源 dict；资源缺失则回退 CDN（返回 {}）并提示。"""
    if not offline:
        return {}
    from . import assets as assets_mod
    inline = assets_mod.load_inline()
    if not any(inline.values()):
        logger.warning("离线资源缺失，回退 CDN。请先联网运行：python -m astock_watch.assets")
        return {}
    return inline


class StockAnalyzer:
    """对单支股票执行完整盯盘分析并产出 HTML 报告。"""

    def __init__(self, code: str, analysis_date: str = None, out_dir: str = "."):
        self.code = str(code).strip()
        self.analysis_date = analysis_date          # 'YYYYMMDD' 或 None=最新
        self.out_dir = out_dir
        self.fetcher = DataFetcher()
        # 中间产物
        self.raw = None
        self.df = None
        self.snap = None
        self.result = {}

    # ------------------------------------------------------------
    def fetch_data(self) -> dict:
        """抓取全部原始数据并计算技术指标。"""
        self.raw = self.fetcher.fetch_all(self.code, self.analysis_date)
        self.df = indicators.compute_all(self.raw["kline"])
        self.snap = indicators.latest_snapshot(self.df)
        logger.info("数据就绪：%s %s（%d 根K线，%s）", self.raw["meta"]["name"],
                    self.code, len(self.df),
                    "模拟数据" if self.raw["meta"]["is_mock"] else "真实数据")
        return self.raw

    def technical_analysis(self) -> dict:
        try:
            self.result["technical"] = technical.analyze(self.df, self.snap)
        except Exception as e:                       # noqa: BLE001
            logger.warning("技术面分析异常：%s", e)
            self.result["technical"] = {"score": 50.0, "trend": {"state": "未知", "desc": ""},
                                        "signals": [], "patterns": [],
                                        "support_resistance": {}, "sub_scores": {},
                                        "summary": "技术面分析失败"}
        return self.result["technical"]

    def capital_flow_analysis(self) -> dict:
        try:
            self.result["capital"] = capital_mod.analyze(self.raw["capital"], self.raw["north"])
        except Exception as e:                       # noqa: BLE001
            logger.warning("资金面分析异常：%s", e)
            self.result["capital"] = {"available": False, "score": 50.0,
                                      "summary": "资金面分析失败", "rows": [], "north": None}
        return self.result["capital"]

    def news_analysis(self) -> dict:
        try:
            self.result["news"] = news_mod.analyze(self.raw["news"])
        except Exception as e:                       # noqa: BLE001
            logger.warning("消息面分析异常：%s", e)
            self.result["news"] = {"available": False, "score": 50.0, "items": [],
                                   "pos": 0, "neg": 0, "neutral": 0, "overall": "中性",
                                   "top": [], "summary": "消息面分析失败"}
        return self.result["news"]

    def synthesize(self) -> dict:
        self.result["scoring"] = scoring.synthesize(
            self.df, self.snap, self.result["technical"], self.result["capital"],
            self.result["news"], self.raw["meta"]["is_mock"])
        return self.result["scoring"]

    def run_backtest(self) -> dict:
        """评分模型校准 + 策略回测（数据不足时自动跳过）。"""
        try:
            self.result["backtest"] = backtest_mod.run_backtest(self.df)
        except Exception as e:                       # noqa: BLE001
            logger.warning("回测异常：%s", e)
            self.result["backtest"] = {"available": False, "reason": str(e)}
        return self.result["backtest"]

    # ------------------------------------------------------------
    def _build_header(self) -> dict:
        last = self.df.iloc[-1]
        prev_close = self.df["close"].iloc[-2] if len(self.df) >= 2 else last["close"]
        return {
            "name": self.raw["meta"]["name"],
            "code": self.code,
            "market": self.raw["meta"]["market"].upper(),
            "industry": (self.raw["basic"] or {}).get("industry") or "—",
            "date": str(last["date"]),
            "close": safe_round(last["close"], 2),
            "pct_chg": safe_round(last.get("pct_chg"), 2),
            "change": safe_round(last["close"] - prev_close, 2),
            "amount": fmt_money(last.get("amount")) if "amount" in last else "—",
            "turnover": safe_round(last.get("turnover"), 2) if "turnover" in last else None,
            "is_mock": self.raw["meta"]["is_mock"],
            "sources": self.raw["meta"]["sources"],
        }

    def _build_charts(self) -> dict:
        c = {}
        try:
            c["main"] = report_mod.to_json(charts.main_chart(self.df))
        except Exception as e:                       # noqa: BLE001
            logger.warning("主图生成失败：%s", e)
            c["main"] = "null"
        cap = self.result["capital"]
        c["capital"] = report_mod.to_json(charts.capital_chart(cap.get("rows", [])))
        c["north"] = report_mod.to_json(charts.north_chart(self.raw.get("north")))
        nw = self.result["news"]
        c["pie"] = report_mod.to_json(charts.sentiment_pie(nw["pos"], nw["neutral"], nw["neg"]))
        sc = self.result["scoring"]["dimension_scores"]
        c["radar"] = report_mod.to_json(charts.radar_chart(sc["technical"], sc["capital"], sc["news"]))
        bt = self.result.get("backtest", {})
        if bt.get("available"):
            c["equity"] = report_mod.to_json(charts.equity_chart(bt["dates"], bt["equity"], bt["benchmark"]))
            c["calibration"] = report_mod.to_json(charts.calibration_chart(bt["calibration"]))
        else:
            c["equity"] = c["calibration"] = "null"
        return c

    def generate_report(self, out_path: str = None, offline: bool = False) -> str:
        """组装 payload、渲染并保存 HTML，返回文件路径。offline=True 内联本地资源。"""
        header = self._build_header()
        charts_json = self._build_charts()
        assets_inline = _resolve_offline_assets(offline)
        payload = {
            "cdn": C.CDN,
            "offline": bool(assets_inline),
            "assets": assets_inline,
            "color": {"up": C.COLOR_UP, "down": C.COLOR_DOWN, "neutral": C.COLOR_NEUTRAL},
            "header": header,
            "tech": self.result["technical"],
            "capital": self.result["capital"],
            "news": self.result["news"],
            "scoring": self.result["scoring"],
            "backtest": self.result.get("backtest", {"available": False}),
            "charts": charts_json,
            "gen_time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        html = report_mod.render(payload)
        if not out_path:
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(self.out_dir, f"astock_watch_{self.code}_{stamp}.html")
        path = report_mod.save(html, out_path)
        logger.info("报告已生成：%s", path)
        return path

    # ------------------------------------------------------------
    def run(self, out_path: str = None, offline: bool = False) -> str:
        """一键执行完整流程，返回报告路径。offline=True 内联本地资源（完全离线）。"""
        self.fetch_data()
        self.technical_analysis()
        self.capital_flow_analysis()
        self.news_analysis()
        self.synthesize()
        self.run_backtest()
        return self.generate_report(out_path, offline=offline)

    def summary_item(self, report_path: str) -> dict:
        """提取用于多股横向对比汇总页的关键指标。"""
        h = self._build_header()
        sc = self.result["scoring"]
        ds = sc["dimension_scores"]
        return {
            "code": self.code, "name": h["name"], "date": h["date"],
            "close": h["close"], "pct_chg": h["pct_chg"], "is_mock": h["is_mock"],
            "composite": sc["composite"], "technical": ds["technical"],
            "capital": ds["capital"], "news": ds["news"],
            "action": sc["action"], "lead": sc["lead"], "risk_level": sc["risk_level"],
            "report_file": os.path.basename(report_path),
        }


def analyze_many(codes, analysis_date=None, out_dir=".", make_summary=True, offline=False):
    """批量分析多支股票。返回 (结果列表, 汇总页路径或 None)。

    结果列表为 [(code, 报告路径或 'ERROR: ...'), ...]；成功分析 ≥2 支时生成横向对比汇总页。
    offline=True 时所有报告与汇总页内联本地资源，完全离线可打开。
    """
    results, items = [], []
    for code in codes:
        try:
            a = StockAnalyzer(code, analysis_date=analysis_date, out_dir=out_dir)
            path = a.run(offline=offline)
            results.append((code, path))
            try:
                items.append(a.summary_item(path))
            except Exception as e:                   # noqa: BLE001
                logger.warning("汇总项生成失败 %s：%s", code, e)
        except Exception as e:                       # noqa: BLE001
            logger.error("分析 %s 失败：%s", code, e)
            results.append((code, f"ERROR: {e}"))

    summary_path = None
    if make_summary and len(items) >= 2:
        try:
            ordered = sorted(items, key=lambda x: (x.get("composite") or 0), reverse=True)
            comp_json = report_mod.to_json(charts.comparison_chart(ordered))
            assets_inline = _resolve_offline_assets(offline)
            summary_path = report_mod.render_summary(
                items, comp_json, out_dir, analysis_date,
                offline=bool(assets_inline), assets_inline=assets_inline)
        except Exception as e:                       # noqa: BLE001
            logger.warning("汇总页生成失败：%s", e)
    return results, summary_path
