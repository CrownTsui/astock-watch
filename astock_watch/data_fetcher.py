# -*- coding: utf-8 -*-
"""
数据抓取层。

数据来源（全部免费、无需 token）：
  - 行情/K线 ：akshare.stock_zh_a_hist          （东方财富，前复权日线）
  - 个股资金流：akshare.stock_individual_fund_flow （东方财富，主力/超大/大/中/小单）
  - 北向持股 ：akshare.stock_hsgt_individual_em    （沪深股通，2024-08 后或失效，自动降级）
  - 个股新闻 ：akshare.stock_news_em              （东方财富资讯）
  - 公司公告 ：akshare.stock_zh_a_disclosure_report_cninfo（巨潮资讯）
  - 基本信息 ：akshare.stock_individual_info_em    （名称/行业/市值）

设计原则（对抗审查要点）：
  1. 每个接口独立 try/except + 重试，单点失败不影响其它数据；
  2. 全部失败（如断网）时，用确定性随机游走生成"模拟数据"兜底，并打 is_mock 标记，
     报告会显著提示，绝不让用户把模拟数据误当真实行情；
  3. akshare 列名为中文，统一映射为英文标准列名，下游模块与数据源解耦。
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

from . import config as C
from .utils import logger, normalize_code, retry

try:
    import akshare as ak
except Exception as e:  # pragma: no cover  —— 缺库时降级到纯模拟
    ak = None
    logger.warning("akshare 导入失败（将使用模拟数据）：%s", e)


_KLINE_COLS = {
    "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
    "最低": "low", "成交量": "volume", "成交额": "amount",
    "涨跌幅": "pct_chg", "换手率": "turnover",
}

# 全市场代码-名称映射缓存（首次查询时填充，避免重复拉取）
_CODE_NAME_MAP = None
_FUND_NAME_MAP = None


class DataFetcher:
    """负责把一支股票所需的全部原始数据抓齐。"""

    def __init__(self, timeout: int = C.REQUEST_TIMEOUT):
        self.timeout = timeout

    # ============================================================
    # 行情 / K线
    # ============================================================
    @retry(times=C.REQUEST_RETRY, backoff=C.RETRY_BACKOFF, default=None)
    def fetch_kline(self, code: str, end_date: Optional[str] = None,
                    days: int = C.KLINE_DAYS, is_fund: bool = False,
                    market: str = "sh") -> Optional[pd.DataFrame]:
        """前复权日 K 线。end_date 形如 '20260629'，默认取最新交易日。

        多数据源互为兜底，按顺序尝试直到拿到真实数据：
          - 东方财富：股票 stock_zh_a_hist / ETF fund_etf_hist_em（含 end_date 过滤、qfq）
          - 新浪    ：股票 stock_zh_a_daily / ETF fund_etf_hist_sina（不同服务器，绕开东财限流）
        东财历史接口高频请求时常返回 RemoteDisconnected，新浪源作为关键兜底保证真实数据可得。
        """
        if ak is None:
            return None
        end = end_date or dt.date.today().strftime("%Y%m%d")
        # 多预留日历日以覆盖足够交易日（含周末/节假日）
        start_dt = dt.datetime.strptime(end, "%Y%m%d") - dt.timedelta(days=int(days * 1.7))
        start = start_dt.strftime("%Y%m%d")
        symbol = f"{market}{code}"                    # 新浪接口需带市场前缀，如 sh515030

        def _em_stock():
            return ak.stock_zh_a_hist(symbol=code, period="daily",
                                      start_date=start, end_date=end, adjust="qfq")

        def _em_etf():
            return ak.fund_etf_hist_em(symbol=code, period="daily",
                                       start_date=start, end_date=end, adjust="qfq")

        def _sina_stock():
            return ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")

        def _sina_etf():
            return ak.fund_etf_hist_sina(symbol=symbol)

        sources = ([_em_etf, _sina_etf, _em_stock, _sina_stock] if is_fund
                   else [_em_stock, _sina_stock, _em_etf, _sina_etf])
        raw = None
        for fn in sources:
            try:
                raw = fn()
                if raw is not None and not raw.empty:
                    break
            except Exception:                        # noqa: BLE001  —— 换下一个数据源
                continue
        if raw is None or raw.empty:
            return None
        # 东财列名为中文需映射；新浪本就是英文列，rename 不影响
        df = raw.rename(columns=_KLINE_COLS)
        keep = [c for c in ["date", "open", "high", "low", "close",
                            "volume", "amount", "pct_chg", "turnover"] if c in df.columns]
        df = df[keep].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values("date").reset_index(drop=True)
        # 新浪接口返回全量历史且不按 end 过滤，这里统一按分析日截断
        end_iso = dt.datetime.strptime(end, "%Y%m%d").strftime("%Y-%m-%d")
        df = df[df["date"] <= end_iso].reset_index(drop=True)
        # 新浪换手率为小数比例（如 0.0024），东财为百分比（如 0.24）；统一成百分比
        if "turnover" in df.columns and df["turnover"].notna().any() \
                and df["turnover"].median() < 1:
            df["turnover"] = df["turnover"] * 100
        # 新浪源无涨跌幅列，用收盘价补算，保证下游/报告口径一致
        if "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
        return df.tail(days).reset_index(drop=True)

    def fetch_basic(self, code: str, is_fund: bool = False) -> dict:
        """基本信息：名称、行业、总/流通市值。多接口容错，名称必有兜底。

        股票主接口 stock_individual_info_em 在部分 akshare 版本与东财返回结构不兼容
        （Length mismatch），此时退化到代码-名称表；ETF/基金走基金名称表。
        """
        out = {"name": None, "industry": None, "total_mv": None,
               "circ_mv": None, "list_date": None, "latest": None}
        if ak is None:
            return out
        if is_fund:
            out["industry"] = "ETF/基金"
        else:
            try:
                info = ak.stock_individual_info_em(symbol=code)
                if (info is not None and not info.empty
                        and "item" in info.columns and "value" in info.columns):
                    d = dict(zip(info["item"], info["value"]))
                    out.update(name=d.get("股票简称") or d.get("简称"),
                               industry=d.get("行业"), total_mv=d.get("总市值"),
                               circ_mv=d.get("流通市值"), list_date=d.get("上市时间"),
                               latest=d.get("最新"))
            except Exception as e:                   # noqa: BLE001
                logger.warning("个股信息接口异常（降级用代码名称表）：%s", str(e)[:70])
        if not out.get("name"):
            out["name"] = self._lookup_name(code, is_fund)
        return out

    @staticmethod
    def _lookup_name(code: str, is_fund: bool = False):
        """用代码-名称表查简称（模块级缓存）。ETF/基金用基金行情表，股票用代码表。"""
        global _CODE_NAME_MAP, _FUND_NAME_MAP
        try:
            if is_fund:
                if _FUND_NAME_MAP is None:
                    tbl = ak.fund_etf_spot_em()
                    cc = next(c for c in tbl.columns if "代码" in c)
                    nc = next(c for c in tbl.columns if "名称" in c)
                    _FUND_NAME_MAP = dict(zip(tbl[cc].astype(str).str.zfill(6), tbl[nc]))
                return _FUND_NAME_MAP.get(code)
            if _CODE_NAME_MAP is None:
                tbl = ak.stock_info_a_code_name()
                _CODE_NAME_MAP = dict(zip(tbl["code"].astype(str).str.zfill(6), tbl["name"]))
            return _CODE_NAME_MAP.get(code)
        except Exception:                            # noqa: BLE001
            return None

    # ============================================================
    # 资金面
    # ============================================================
    @retry(times=C.REQUEST_RETRY, backoff=C.RETRY_BACKOFF, default=None)
    def fetch_capital_flow(self, code: str, market: str) -> Optional[pd.DataFrame]:
        """个股历史资金流（主力/超大单/大单/中单/小单净额，单位：元）。"""
        if ak is None:
            return None
        mkt = "sh" if market == "sh" else "sz"  # 北交所归 sz 前缀尝试
        raw = ak.stock_individual_fund_flow(stock=code, market=mkt)
        if raw is None or raw.empty:
            return None
        ren = {
            "日期": "date", "收盘价": "close", "涨跌幅": "pct_chg",
            "主力净流入-净额": "main_net", "主力净流入-净占比": "main_pct",
            "超大单净流入-净额": "xl_net", "大单净流入-净额": "lg_net",
            "中单净流入-净额": "md_net", "小单净流入-净额": "sm_net",
        }
        df = raw.rename(columns=ren)
        keep = [c for c in ren.values() if c in df.columns]
        df = df[keep].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        for c in ["close", "pct_chg", "main_net", "main_pct",
                  "xl_net", "lg_net", "md_net", "sm_net"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values("date").reset_index(drop=True)

    @retry(times=1, backoff=1.0, default=None)
    def fetch_north_hold(self, code: str) -> Optional[pd.DataFrame]:
        """北向（沪深股通）个股持股变化。2024-08 后官方停披露，失败自动降级。"""
        if ak is None:
            return None
        raw = ak.stock_hsgt_individual_em(symbol=code)
        if raw is None or raw.empty:
            return None
        # 接口列名随版本变动，做尽力而为的字段对齐
        df = raw.copy()
        date_col = next((c for c in df.columns if "日期" in c), None)
        hold_col = next((c for c in df.columns if "持股" in c and "市值" in c), None)
        if not date_col or not hold_col:
            return None
        out = pd.DataFrame({
            "date": pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d"),
            "north_hold_mv": pd.to_numeric(df[hold_col], errors="coerce"),
        })
        return out.sort_values("date").reset_index(drop=True).tail(60)

    # ============================================================
    # 消息面
    # ============================================================
    @retry(times=C.REQUEST_RETRY, backoff=C.RETRY_BACKOFF, default=[])
    def fetch_news(self, code: str, days: int = C.NEWS_DAYS) -> list:
        """个股近 N 日新闻（标题/摘要/时间/来源/链接）。"""
        if ak is None:
            return []
        raw = ak.stock_news_em(symbol=code)
        if raw is None or raw.empty:
            return []
        cutoff = dt.datetime.now() - dt.timedelta(days=days)
        items = []
        for _, r in raw.iterrows():
            t = str(r.get("发布时间", ""))
            try:
                ts = pd.to_datetime(t)
                if ts < cutoff:
                    continue
            except Exception:
                ts = None
            items.append({
                "title": str(r.get("新闻标题", "")).strip(),
                "summary": str(r.get("新闻内容", "")).strip()[:120],
                "time": t,
                "source": str(r.get("文章来源", "")).strip(),
                "url": str(r.get("新闻链接", "")).strip(),
                "kind": "news",
            })
        return items[:30]

    @retry(times=1, backoff=1.0, default=[])
    def fetch_notices(self, code: str, days: int = 30) -> list:
        """公司公告（巨潮资讯）。失败自动降级为空。"""
        if ak is None:
            return []
        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        raw = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=code, market="沪深京",
            start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
        if raw is None or raw.empty:
            return []
        title_col = next((c for c in raw.columns if "标题" in c), None)
        time_col = next((c for c in raw.columns if "时间" in c or "日期" in c), None)
        url_col = next((c for c in raw.columns if "链接" in c or "url" in c.lower()), None)
        items = []
        for _, r in raw.iterrows():
            items.append({
                "title": str(r.get(title_col, "")).strip() if title_col else "",
                "summary": "",
                "time": str(r.get(time_col, "")).strip() if time_col else "",
                "source": "公司公告",
                "url": str(r.get(url_col, "")).strip() if url_col else "",
                "kind": "notice",
            })
        return items[:15]

    # ============================================================
    # 汇总
    # ============================================================
    def fetch_all(self, code: str, analysis_date: Optional[str] = None) -> dict:
        """抓取一支股票的全部数据，返回标准化字典。

        强约束：行情为分析的基石，必须是真实数据。多数据源（东财+新浪）全部失败时
        直接抛出异常，由上层跳过该标的——禁止使用任何模拟/伪造数据。
        """
        meta = normalize_code(code)
        is_fund = meta.get("is_fund", False)
        sources = {}

        # —— 行情（核心，必须真实，多源兜底）——
        kline = self.fetch_kline(meta["code"], end_date=analysis_date,
                                 is_fund=is_fund, market=meta["market"])
        if kline is None or kline.empty or len(kline) < 30:
            raise RuntimeError(
                f"{code} 行情数据抓取失败（已尝试东方财富+新浪多源），"
                f"按要求不使用模拟数据，跳过该标的")
        sources["kline"] = "东方财富/新浪(akshare)"

        # —— 基本信息 ——
        basic = self.fetch_basic(meta["code"], is_fund=is_fund)
        name = (basic.get("name") or f"{'基金' if is_fund else '股票'}{meta['code']}")

        # —— 资金面（ETF 无个股资金流口径属正常，非模拟）——
        capital = self.fetch_capital_flow(meta["code"], meta["market"])
        sources["capital"] = ("东方财富(akshare)" if capital is not None
                              else ("ETF/基金无个股资金流口径" if is_fund else "无数据"))

        north = self.fetch_north_hold(meta["code"])
        sources["north"] = "沪深股通(akshare)" if north is not None else "无数据/已停披露"

        # —— 消息面 ——
        news = self.fetch_news(meta["code"])
        notices = self.fetch_notices(meta["code"])
        sources["news"] = "东方财富(akshare)" if news else "无数据"

        return {
            "meta": {**meta, "name": name, "is_mock": False,
                     "analysis_date": analysis_date, "sources": sources},
            "basic": basic,
            "kline": kline,
            "capital": capital,
            "north": north,
            "news": (news or []) + (notices or []),
        }
