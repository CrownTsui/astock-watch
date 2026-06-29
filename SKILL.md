---
name: astock-watch
description: >
  A 股每日盯盘分析。输入一个或多个股票代码，自动抓取技术面（K线/MA/MACD/KDJ/RSI/BOLL/WR/ADX）、
  资金面（主力资金流向/北向持股）、消息面（新闻公告 + 情感分析）三类数据，进行量化研判，给出
  未来 1-3 日走势概率、操作建议、仓位与关键价位（入场/止损/目标），并生成图文并茂、可交互、
  离线可打开的 HTML 报告；含评分模型回测校准与多股横向对比汇总页。
  当用户提到「盯盘」「看盘」「股票分析」「A股」「每日复盘」「技术分析」「资金流」「主力资金」
  「个股研判」「炒股」「选股」「回测」「多股对比」「帮我看看某某股票」时使用此 skill。
  English triggers: "A-share stock watch", "stock analysis", "daily stock review", "backtest".
---

# A 股每日盯盘分析 Skill

对输入的 A 股股票执行技术面 + 资金面 + 消息面三维量化分析，输出交互式 HTML 报告。

## 快速使用

```bash
# 安装依赖（首次）
pip install -r requirements.txt

# 不带任何参数：默认分析自选股（watchlist.txt 中的标的）
python run.py

# 单只股票
python run.py --symbol 600519

# 多只股票（逗号分隔）
python run.py --symbol 600519,000858,300750 --out-dir reports

# 指定分析日期 + 自动打开浏览器
python run.py --symbol 600519 --date 20260628 --open
```

报告默认输出到 `reports/astock_watch_<代码>_<时间戳>.html`，双击即可在浏览器打开。

> 💡 **默认自选股**：直接运行 `python run.py`（不传 `--symbol`/`--file`）时，会读取 skill 根目录下的
> `watchlist.txt` 并分析其中全部标的。编辑该文件即可维护自己的盯盘池。

## 分析维度

| 维度 | 内容 |
|------|------|
| 技术面 | 趋势（均线排列/ADX/斜率）、支撑压力、MACD/KDJ/RSI/WR/BOLL 信号、量价、形态识别 |
| 资金面 | 主力净流入力度与连续性、主力 vs 散户、北向资金倾向 |
| 消息面 | 近 7 日新闻/公告，金融情感词库打分，关键资讯提取 |
| 综合 | 三维加权评分、走势概率分布、操作建议、仓位、入场/止损/目标价位 |
| 回测 | 评分模型 IC 校准、分档收益、策略净值 vs 买入持有（严格无前视） |
| 对比 | 多股分析自动生成横向对比汇总页（可点击下钻各报告） |

## 数据来源（免费、无需 token）

- 行情/资金/新闻：akshare（封装东方财富、巨潮资讯等公开接口）
- 接口失败自动降级；全部失败时用模拟数据兜底并显著标注。

## 编程调用

```python
from astock_watch import StockAnalyzer
path = StockAnalyzer("600519").run()      # 返回报告路径
```

详见 README.md（架构设计、自定义、每日定时运行）。

> ⚠️ 本工具产出为量化模型的机械计算结果，不构成投资建议。股市有风险，决策需谨慎。
