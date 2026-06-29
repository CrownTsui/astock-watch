# astock-watch · A 股每日盯盘分析 Skill

输入股票代码 → 自动抓取**技术面 / 资金面 / 消息面**三类数据 → 量化研判 → 生成**图文并茂、可交互、离线可打开的 HTML 报告**。

报告含：交互式 K 线（MA/BOLL）+ 量 + MACD/KDJ/RSI 联动子图、主力资金流图、情感分布饼图、三维评分雷达图、**评分模型回测净值曲线**，以及走势概率、操作建议、入场/止损/目标价位。多股分析自动生成**横向对比汇总页**，并支持 `--offline` **完全离线**打开。

---

## 一、架构设计

### 1. 数据流

```
用户输入代码
     │
     ▼
┌─────────────┐   akshare(东方财富/巨潮)   ┌──────────────────────────┐
│ DataFetcher │ ─────────────────────────▶ │ 技术面: 日K线 OHLCV        │
│ fetch_all() │   逐接口 try/except 降级    │ 资金面: 主力/北向资金流     │
│             │   全失败 → 模拟数据兜底      │ 消息面: 新闻/公告           │
└─────┬───────┘                            └──────────────────────────┘
      ▼
┌─────────────┐
│ indicators  │  纯 pandas/numpy 计算 MA/MACD/KDJ/RSI/BOLL/WR/DMI/ATR（通达信参数）
└─────┬───────┘
      ▼
┌──────────┬──────────┬──────────┐
│technical │ capital  │  news    │   三维独立分析，各产出 0-100 分 + 文字研判
└────┬─────┴────┬─────┴────┬─────┘
     └──────────┼──────────┘
                ▼
          ┌──────────┐
          │ scoring  │  加权综合分 → 走势概率分布 / 操作建议 / 仓位 / 量化价位
          └────┬─────┘
               ▼
     ┌──────────────────┐
     │ charts → report  │  Plotly.js figure(JSON) + Jinja2 模板 → 独立 HTML
     └──────────────────┘
```

### 2. 模块划分

| 文件 | 职责 |
|------|------|
| `astock_watch/config.py` | 全部参数：指标周期、阈值、评分权重、金融情感词库、CDN |
| `astock_watch/utils.py` | 代码标准化、网络重试、NaN 清洗、中文金额/百分比格式化 |
| `astock_watch/data_fetcher.py` | 数据抓取（akshare 为主，逐接口降级，模拟兜底） |
| `astock_watch/indicators.py` | 技术指标计算（纯 pandas/numpy，无需 talib） |
| `astock_watch/technical.py` | 技术面：趋势/支撑压力/指标信号/形态/打分 |
| `astock_watch/capital.py` | 资金面：主力力度/连续性/主散对比/北向/打分 |
| `astock_watch/news.py` | 消息面：金融情感词库打分 + 关键资讯提取 |
| `astock_watch/scoring.py` | 综合研判：加权分/走势概率/操作建议/量化价位 |
| `astock_watch/charts.py` | 生成 Plotly.js figure 字典（K线/资金/饼/雷达） |
| `astock_watch/backtest.py` | 评分模型回测与校准（IC、分档收益、策略净值 vs 基准） |
| `astock_watch/report.py` | Jinja2 渲染 + 图表 JSON 注入 + 写文件 |
| `astock_watch/assets.py` | 离线资源下载/内联（完全离线报告） |
| `astock_watch/analyzer.py` | `StockAnalyzer` 编排类 + `analyze_many` 批量 + 汇总 |
| `astock_watch/templates/report.html.j2` | 个股 HTML 报告模板（Bootstrap 5） |
| `astock_watch/templates/summary.html.j2` | 多股横向对比汇总页模板 |
| `run.py` | 命令行入口 |

### 3. 技术选型理由

- **akshare**：免费、无需 token，封装东方财富/巨潮等公开接口，覆盖行情/资金/新闻/公告，是 A 股开源数据事实标准。
- **不依赖 talib**：talib 需编译 C 库、安装门槛高。所有指标用 pandas/numpy 按通达信公式实现，结果与行情软件一致且零安装负担。
- **图表用 Plotly.js（CDN）而非 plotly Python 包**：Python 端只生成 figure 的 JSON 结构，浏览器端渲染。好处是**零额外安装、完全交互式（缩放/平移/十字光标/tooltip）、报告离线可开**。
- **自建金融情感词库**：通用 SnowNLP 对"利空/减持/商誉减值"等金融术语判断不准；自建词库 + 程度副词/否定词修饰更贴合 A 股语境。若已装 SnowNLP 则自动融合增强。
- **降级 + 模拟兜底**：每个接口独立容错，最坏情况（断网）也能产出结构完整的报告，并显著标注"模拟数据"，绝不误导。

---

## 二、安装

### 1. 获取代码

```bash
git clone https://github.com/CrownTsui/astock-watch.git
cd astock-watch
```

### 2. 创建虚拟环境（推荐，避免污染全局依赖）

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

需要 **Python 3.9+**。核心依赖：akshare / pandas / numpy / scipy / jinja2。可选：snownlp（情感增强，缺失自动降级，不影响运行）。

### 4. 验证安装

```bash
python run.py --symbol 600519 --open
```

若浏览器自动弹出一份贵州茅台的分析报告，即安装成功。首次运行需联网拉取行情数据；若报告标注「模拟数据」，多为网络或盘前接口问题，可换网络稍后重试（见第九节 FAQ）。

### 5.（可选）作为 Agent Skill 安装

本仓库自带 `SKILL.md`，符合 [Agent Skills Standard](https://skills.sh)，可在任何 skills-compatible runtime（Claude Code / Codex / Cursor / OpenClaw 等）中使用。安装方式：把仓库目录放到对应 runtime 的技能目录即可，之后在对话中说「帮我盯盘 600519」会自动触发。

```bash
# 一行安装（自动检测 runtime 技能目录）
SKILL_DIR="${CLAUDE_SKILLS:-${CODEX_SKILLS:-${CURSOR_SKILLS:-~/.claude/skills}}}"
git clone https://github.com/CrownTsui/astock-watch.git "$SKILL_DIR/astock-watch"
cd "$SKILL_DIR/astock-watch" && pip install -r requirements.txt

# 手动指定路径（各 runtime 默认技能目录参考）
# Claude Code : ~/.claude/skills/
# Codex       : ~/.codex/skills/
# Cursor      : ~/.cursor/skills/
```

---

## 三、使用

### 命令行

```bash
python run.py --symbol 600519                      # 单只
python run.py --symbol 600519,000858,300750        # 多只（逗号分隔）
python run.py --file watchlist.example.txt         # 从股票池文件读取
python run.py --symbol 600519 --date 20260628      # 指定历史交易日
python run.py --symbol 600519 --out-dir reports --open   # 指定目录并自动打开
```

> 代码无需带交易所前缀，沪深北均可（如 `600519` / `000858` / `300750` / `688981`），程序自动识别。

| 参数 | 说明 |
|------|------|
| `-s, --symbol` | 股票代码，逗号分隔 |
| `-f, --file` | 股票池文件，每行一个代码（`#` 注释） |
| `-d, --date` | 分析日期 `YYYYMMDD`，默认最近交易日 |
| `-o, --out-dir` | 报告输出目录（默认 `reports/`） |
| `--open` | 生成后自动用浏览器打开 |
| `--offline` | 内联本地资源生成完全离线报告（先运行 `python -m astock_watch.assets`） |

### 查看报告

运行完成后，报告生成在输出目录（默认 `reports/`）：

```
reports/
├── astock_watch_600519_20260629_160644.html      # 个股报告
└── astock_watch_summary_20260629_160644.html      # 多股汇总页（分析 ≥2 只时生成）
```

文件名格式为 `astock_watch_<代码>_<日期>_<时间>.html`，**双击即可用浏览器打开**，无需启动任何服务；加 `--open` 则生成后自动打开。报告默认从 CDN 加载图表库，首次打开需联网；无网环境请改用 `--offline`（见第八节）。

### 编程接口

```python
from astock_watch import StockAnalyzer

# 一键生成报告
path = StockAnalyzer("600519").run()

# 或分步执行，读取中间结果
a = StockAnalyzer("600519", out_dir="reports")
a.fetch_data()                 # 抓数据 + 算指标
a.technical_analysis()         # → a.result['technical']
a.capital_flow_analysis()      # → a.result['capital']
a.news_analysis()              # → a.result['news']
a.synthesize()                 # → a.result['scoring']
report_path = a.generate_report()
```

---

## 四、自定义

- **股票池**：编辑 `watchlist.example.txt`（或自建文件），`python run.py --file 你的文件.txt`。
- **指标参数 / 评分权重 / 情感词库**：全部集中在 `astock_watch/config.py`，例如：
  - `DIMENSION_WEIGHTS` 调整技术/资金/消息三维权重；
  - `TECH_SUB_WEIGHTS` 调整技术面内部子项权重；
  - `POSITIVE_WORDS / NEGATIVE_WORDS` 扩充情感词库；
  - `ACTION_BANDS`、`suggest_position()` 调整操作建议与仓位映射。

---

## 五、每日定时运行

### macOS / Linux（cron）

```bash
crontab -e
# 每个交易日 15:30（收盘后）分析自选股
30 15 * * 1-5 cd /path/to/astock-watch && /usr/bin/python3 run.py --file watchlist.example.txt --out-dir reports >> run.log 2>&1
```

### Windows（任务计划程序）

新建任务，操作设为 `python.exe`，参数 `run.py --file watchlist.example.txt`，起始于项目目录，触发器设为工作日 15:30。

---

## 六、量化评分模型（可审查）

| 维度 | 0-100 分计算依据 |
|------|------------------|
| 技术面 | 趋势(均线排列/ADX/斜率) 30% + MACD 18% + KDJ 12% + RSI 10% + BOLL 10% + 量价 12% + 动量 8% |
| 资金面 | 当日主力净额(tanh 归一) 40% + 近5日累计 35% + 连续性 25%，北向倾向 ±5 |
| 消息面 | 50 + 平均情感分 × 50（情感分 = 金融词库命中极性均值，叠加程度/否定修饰） |
| **综合** | 技术 × 0.45 + 资金 × 0.35 + 消息 × 0.20 |

- **走势概率**：综合分偏离 50 的幅度映射为看涨/震荡/看跌三类概率（越极端，震荡概率越低）。
- **操作建议**：综合分查 `ACTION_BANDS`（买入/加仓/持有/减仓/卖出），高波动或三维分歧大时下调仓位。
- **关键价位**：止损 = max(支撑下方, 收盘−1.8×ATR)；目标 = 最近压力位或 收盘+ATR 倍数；并给出盈亏比。**全部基于 ATR 与支撑压力量化，非主观设定。**

---

## 七、报告模块

头部（名称/代码/收盘/涨跌）→ 综合研判卡片（操作建议/走势概率条/价位）→ 三维评分雷达 → 技术面（联动主图 + 趋势/支撑压力/信号卡 + 形态）→ 资金面（资金流图 + 北向 + 指标）→ 消息面（情感饼 + 关键资讯 + 新闻列表）→ 数据来源 + 免责声明。

---

## 八、进阶功能

### 评分模型回测校准
每份报告自动附带回测模块，用历史数据检验"技术评分 → 未来收益"是否有效：
- **信息系数 IC**：评分与未来 N 日收益的相关系数（>0.03 视为正向有效）；
- **分档校准**：看空/中性/偏多/强多四档的未来平均收益与胜率柱状图；
- **策略净值**：评分上穿买入阈值持仓、下穿卖出阈值空仓，与"买入持有"对比，给出累计/年化收益、Sharpe、最大回撤、段胜率。
- **严格无前视**：持仓信号用前一日评分、次日生效；回测仅用技术评分（资金/消息面缺乏可靠历史对齐数据）。参数见 `config.py` 的 `BACKTEST_*`。

### 多股横向对比汇总页
分析 ≥2 支股票时，自动额外生成 `astock_watch_summary_*.html`：
- 三维 + 综合评分分组柱状对比图；
- 按综合分降序的研判一览表（收盘/涨跌/各维评分/操作/走势/风险）；
- 一键跳转各个股详细报告。

### 完全离线报告
默认图表与样式走 CDN。如需在无网环境打开报告：

```bash
python -m astock_watch.assets            # 首次联网，下载 Bootstrap/Plotly 到本地 assets/
python run.py --symbol 600519 --offline  # 把资源内联进 HTML，完全离线
```

内联后报告体积约 +3.5MB，但不依赖任何外部网络即可打开；若本地已装 `plotly` 包会直接复用其 `plotly.min.js`。资源缺失时自动回退 CDN，不报错。

## 九、FAQ / 故障排查

- **报告显示"模拟数据"？** 说明未能联网抓到真实行情（断网/接口风控/盘前）。换网络或稍后重试即可用真实数据。
- **资金流/北向为"无数据"？** 北向个股持股 2024-08 后官方停披露，接口可能失效；部分股票无沪深股通通道。程序已自动降级，资金面以中性计入，不影响其它分析。
- **图表空白？** 报告依赖 Plotly.js CDN，请确保打开报告时能联网（或自行把 CDN 改为本地文件）。
- **akshare 接口报错？** 升级 `pip install -U akshare`；接口口径偶有变动，程序对关键接口已做容错。
- **中文乱码？** 确保以 UTF-8 打开；模板已指定 `charset=UTF-8` 与中文字体。

---

## ⚠️ 免责声明

本工具产出为**量化模型的机械计算结果**，不构成任何投资建议。模型存在局限（数据延迟、接口口径差异、指标钝化、无法预测黑天鹅等），历史规律不代表未来。股市有风险，据此操作风险自负。
