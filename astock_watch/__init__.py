# -*- coding: utf-8 -*-
"""astock_watch —— A 股每日盯盘分析 Skill。

对外暴露 StockAnalyzer：抓取技术/资金/消息三面数据，量化分析后生成
图文并茂的交互式 HTML 报告。
"""
from .analyzer import StockAnalyzer

__all__ = ["StockAnalyzer"]
__version__ = "1.0.0"
