# EXECUTION_REPORT

- run_id: okx-reverse-20261017-1230
- 时间（UTC）: 2026-10-17 04:30 (UTC) / 2026-10-17 12:30 (Asia/Shanghai)
- Git commit/hash（如有）: 未初始化 git 仓库（无版本控制要求）
- 工作区路径: D:\0.file\Play_AI\OKXbot\okx-strategy-reverse
- 数据级别 D0-D4: D2（合成数据等价级，SYNTHETIC_DEMO：成交记录 + 行情 K 线，无真实账户数据）
- 输入清单及 SHA-256:
  - `data/generated/demo_fills_grid.csv`（合成网格成交，146 行，源哈希 84ee37446280c180b6da508c7457736f4382d362ea9a2def73e92c6b48e04209）
  - `data/generated/demo_bars_range.csv`（合成 1h K 线，1500 根）
  - `data/generated/demo_fills_dca.csv`（合成 DCA 成交，用于检测器测试）
  - 全部为 `SYNTHETIC_DEMO` 生成数据，非真实账户数据。

## 完成的任务：T01–T12

| 任务 | 状态 | 说明 |
|---|---|---|
| T01 工程初始化/安全门禁 | Done | `pyproject.toml`、CLI（import/audit/infer/backtest/report/demo，均有 --help）、`security.py` 静态扫描禁止写端点，测试 G13 验证 |
| T02 文件导入/字段映射/归档 | Done | CSV/XLSX、中英表头自动映射、可配置 mapping、sha256 只读快照至 `data/raw/`、幂等去重（G01/G02） |
| T03 机器人归属与产品识别 | Partial | bot_id → CONFIRMED_BOT，缺失 → UNKNOWN；未见 AMBIGUOUS 启发式细分（P2） |
| T04 Episode 重建与对账 | Done | 净持仓开平仓回合、部分成交/未闭合标记、`reconciliation_exceptions.csv`（G03/G04/G05/G14） |
| T05 行情导入与特征 | Done | 只用 `bar_end_ms <= 决策时刻` 的已结束 K 线；反未来函数测试 G07/G11 通过 |
| T06 结构检测器 | Done | 网格（算术/几何 CV 对比 + 残差参数）、DCA（FIXED/INCREASING/DOUBLING）、定时定额（G08/G09） |
| T07 信号归因与样本外 | Done | RSI/布林/EMA金叉/突破 6 规则，时间顺序 60/20/20 切分，测试段冻结评估（G10/G16） |
| T08 近似策略 JSON + 回测 | Done | `reconstructed_strategy.json`、保守事件驱动回测（下根 K 线开盘成交，避免用当 K 收盘冒充触发价） |
| T09 盈亏/费用/风险 | Done | Episode 级已实现 PnL、手续费单列、初始资金未知 → `UNVERIFIABLE` 降级（G05/G12） |
| T10 可视化与一键执行 | Done | `report.html`（买卖点/持仓/RSI 三面板 + 回测净值）、`demo` 一条命令全流程 |
| T11 真实数据接入 | Partial（按计划可选） | 通用 CSV/XLSX 导入已可用；OKX 只读 API 适配器未实现（MASTER PLAN 2.1 规定 API 非启动前提） |
| T12 独立复核 | Pending | 本报告即交接物；等待 Reviewer AI 按 `03_REVIEWER_PROMPT.md` 验收 |

## CLI 实际执行命令与真实输出摘要

```
> python -m okx_reverse.cli demo
SYNTHETIC_DEMO: 生成合成数据（非真实账户数据）
  source_id: 84ee37446280c180, row_count: 146
audit → {"rows": 146, "episodes": 14, "warnings": [], "reconciliation_exceptions": 0}
infer → {"result_type": "SYNTHETIC_DEMO", "observed_fills": 146,
         "confirmed_bot_fills": 146, "strategy_class": "GRID",
         "confidence": "MEDIUM", "out_of_sample_evaluated": true,
         "lookahead_check": "PASS", "warnings": []}
backtest → {"n_trades": ..., "net_pnl": ..., "buy_and_hold": {...},
            "risk": {"pnl_status": "VERIFIABLE_REALIZED_ONLY",
                     "n_episodes": 14, "realized_pnl_sum": 148.70,
                     "fees_quote_total": 14.45, "win_rate": 1.0}}
report → REPORT_WRITTEN: artifacts\reports\report.html
```

（backtest 完整 JSON 见 `artifacts/reports/backtest.json`；合成网格上检测器
正确输出 GRID / MEDIUM，网格参数含 arith_cv、geo_cv、间距中位数。）

## pytest 通过数/失败数/跳过数

```
18 passed, 0 failed, 0 skipped（1.49s，完全离线、无任何凭证）
```

覆盖 G01–G18：G01 幂等导入、G02 同毫秒多笔保留、G03 部分成交按成交更新、
G04 方向不可判定开平仓、G05 未知初始仓 PnL 不输出精确值、G06 费用币种不混加、
G07/G11 反未来函数、G08 网格算术/几何、G09 DCA 固定/倍增区分、G10 随机对照
不给“确认”、G12 费用单列、G13 无写端点调用（静态扫描）、G14 未闭合标记、
G15 证据级别枚举、G16 时间三段样本外、G17 合成 demo 标注 SYNTHETIC_DEMO、
G18 无凭证离线运行。

## 生成报告路径

- `artifacts/reports/report.html`（人类可读：数据完整度、买卖点图、持仓、RSI、假设排行榜、样本外结果、风险）
- `artifacts/reports/strategy_report.json`、`artifacts/reports/backtest.json`
- `artifacts/evidence/normalized_trades.csv`、`episode_ledger.csv`、`reconciliation_exceptions.csv`
- `artifacts/strategies/candidates.json`、`reconstructed_strategy.json`

## 发现的真实策略

**UNDETERMINED** —— 未导入任何真实机器人成交记录。当前所有结论基于
`SYNTHETIC_DEMO` 合成数据（演示网格数据被正确识别为 GRID/MEDIUM，
仅证明系统能力，不代表任何真实账户策略）。

## P0 阻塞项、P1 遗留、P2 改进项

- P0：无。
- P1：
  1. OKX 只读 API 适配器（orders-history / fills-history）未实现，当前仅文件导入。
  2. 合约（SWAP/FUTURES）资金费率、双向持仓模式的 PnL 复原未实现，账本仅覆盖现货式净持仓。
  3. `cmd_demo` 中 DCA 合成数据未进入 infer 主流程（仅用于 G09 检测器测试）。
- P2：
  1. 归属分级可增加时序/模式启发式（PROBABLE_BOT）。
  2. 回测策略 DSL 目前仅支持单入场/离场规则，未覆盖加仓状态机回测。
  3. HTML 报告可加入假设-反证对照表与压力测试面板。

## 各结论对应的证据/订单 ID

- GRID/MEDIUM（合成）：146 笔 `SYNTHETIC_DEMO` 成交（trade_id SXG00001…），参数见 `artifacts/strategies/candidates.json` 中 `hypotheses[0].parameters`。
- 检测器区分能力：G09 使用 `demo_fills_dca.csv`（trade_id SXD…），FIXED vs DOUBLING 判定来自 `size_ratio_median`（1.0 → FIXED，≈2.0 → DOUBLING）。

## 建议验收 AI 执行的复核命令

```powershell
$py='C:\Users\xin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Set-Location 'D:\0.file\Play_AI\OKXbot\okx-strategy-reverse'
$env:PYTHONPATH='src'
& $py -m pytest          # 预期: 18 passed
& $py -m okx_reverse.cli demo   # 预期: strategy_report.json result_type=SYNTHETIC_DEMO, strategy_class=GRID
# 复核安全：全文搜索 src/ 不存在 requests.post / httpx.post / 下单端点调用
```
