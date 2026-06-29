#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股每日盯盘分析 —— 命令行入口。

用法示例：
  python run.py --symbol 600519
  python run.py --symbol 600519,000858,300750 --out-dir reports
  python run.py --symbol 600519 --date 20260628 --open
"""
import argparse
import os
import sys
import webbrowser

# 允许在任意目录下直接 `python run.py` 运行
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from astock_watch.analyzer import analyze_many  # noqa: E402

# 默认自选股池：无任何传参时分析此文件中的标的
DEFAULT_WATCHLIST = os.path.join(SCRIPT_DIR, "watchlist.txt")


def read_codes_from_file(path):
    """从股票池文件读取代码：每行一个，# 开头为注释，取每行首个空白前的字段。"""
    codes = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                codes.append(line.split()[0])
    return codes


def main():
    p = argparse.ArgumentParser(
        description="A股每日盯盘分析，自动抓取技术/资金/消息三面数据并生成交互式 HTML 报告")
    p.add_argument("-s", "--symbol", "--code", dest="symbol", default="",
                   help="股票代码，逗号分隔，如 600519,000858")
    p.add_argument("-f", "--file", dest="file", default=None,
                   help="股票池文件，每行一个代码（# 开头为注释行）")
    p.add_argument("-d", "--date", dest="date", default=None,
                   help="分析日期 YYYYMMDD，默认最近交易日")
    p.add_argument("-o", "--out-dir", dest="out_dir", default=os.path.expanduser("~/Downloads/astock-watch-reports"),
                   help="报告输出目录（默认 ~/Downloads/astock-watch-reports/）")
    p.add_argument("--open", action="store_true", help="生成后自动用浏览器打开")
    p.add_argument("--offline", action="store_true",
                   help="内联本地资源生成完全离线报告（需先运行 python -m astock_watch.assets 下载）")
    args = p.parse_args()

    codes = []
    if args.file:
        try:
            codes += read_codes_from_file(args.file)
        except OSError as e:
            print(f"✗ 读取股票池文件失败：{e}")
            sys.exit(1)
    codes += [c.strip() for c in args.symbol.replace("，", ",").split(",") if c.strip()]
    codes = list(dict.fromkeys(codes))  # 去重并保持顺序

    # 未显式指定股票时，回退到默认自选股池
    if not codes and os.path.exists(DEFAULT_WATCHLIST):
        try:
            codes = read_codes_from_file(DEFAULT_WATCHLIST)
            if codes:
                print(f"ℹ 未指定股票，默认分析自选股（{DEFAULT_WATCHLIST}）")
        except OSError as e:
            print(f"✗ 读取默认自选股失败：{e}")
            sys.exit(1)

    if not codes:
        print("✗ 未提供股票代码：请用 --symbol / --file 指定，或在 watchlist.txt 写入自选股")
        sys.exit(1)

    print(f"▶ 开始分析 {len(codes)} 支股票：{', '.join(codes)}")
    results, summary_path = analyze_many(codes, analysis_date=args.date,
                                         out_dir=args.out_dir, offline=args.offline)

    print("\n===== 完成 =====")
    for code, path in results:
        ok = not str(path).startswith("ERROR")
        print(f"  {'✓' if ok else '✗'} {code}: {path}")
        if ok and args.open:
            try:
                webbrowser.open(f"file://{os.path.abspath(path)}")
            except Exception:
                pass
    if summary_path:
        print(f"  ★ 多股对比汇总: {summary_path}")
        if args.open:
            try:
                webbrowser.open(f"file://{os.path.abspath(summary_path)}")
            except Exception:
                pass


if __name__ == "__main__":
    main()
