# OKX 交易机器人策略逆向分析系统（okx-reverse）

只读 / 离线研究工具：从历史成交记录（CSV/XLSX）推断未知交易机器人的
买卖、加仓、平仓规则，给出竞争性策略假设、证据与样本外验证。
**本项目不含任何实盘下单、撤单、改杠杆、提币等交易所写操作。**

## 快速开始（无需 API Key）

```bash
# 依赖：Python 3.11+，pandas numpy openpyxl matplotlib
$env:PYTHONPATH='src'   # PowerShell；Linux: export PYTHONPATH=src

# 1) 合成数据一键演示（SYNTHETIC_DEMO，明确标注非真实账户）
python -m okx_reverse.cli demo

# 2) 导入你自己的 OKX 成交记录导出（CSV/XLSX）
python -m okx_reverse.cli import --path ./my_export.csv --type auto
python -m okx_reverse.cli audit
python -m okx_reverse.cli infer --market ./data/market/klines.csv
python -m okx_reverse.cli backtest --market ./data/market/klines.csv
python -m okx_reverse.cli report --market ./data/market/klines.csv --output artifacts/reports/report.html

# 3) 测试
python -m pytest
```

- 行情 CSV（可选，用于技术指标归因与买卖点图）：
  列 `inst_id,bar_start_ms,open,high,low,close,volume`，时间支持毫秒时间戳或 `YYYY-MM-DD HH:MM:SS`。
- 无行情时 `infer` 自动降级为「结构假设 + 缺失行情提示」，不会伪造指标结论。

## 命令

| 命令 | 作用 |
|---|---|
| `import` | 导入 CSV/XLSX 成交，字段自动映射、sha256 归档、幂等去重 |
| `audit` | 订单-成交对账 + Episode（开平仓回合）重建 |
| `infer` | 网格/DCA/定时 结构检测 + RSI/布林/EMA/突破 信号归因（训练/验证/测试三段样本外） |
| `backtest` | 近似策略离线回测 + 买入持有基准 + 风险分析 |
| `report` | 生成 HTML 报告（买卖点图、持仓曲线、RSI、净值） |
| `demo` | 合成数据完整流程（SYNTHETIC_DEMO） |

## 检测的候选策略族

网格（算术/几何拟合残差）、DCA/马丁（固定/递增/倍增加仓）、定时定额、
RSI 均值回归、布林带、EMA 金叉趋势、20 期突破。证据强度仅
`HIGH/MEDIUM/LOW/UNDETERMINED`，不输出虚假概率百分比。

## 安全

- 无交易所写端点调用（`security.py` 静态扫描，测试 G13 验证）。
- 不请求/存储 API Key；默认完全离线。
- 金额账本级求和使用 Decimal 语义（见 `models.py`），费用币种单独保留不混加。

## 目录

- `artifacts/` 证据表、候选策略 JSON、HTML 报告
- `data/raw/` 原始文件只读快照（含 sha256）
- `tests/` G01–G18 验收测试
- `handoff/` 交接与验收报告

## 多 Agent 审计与整改交接（2026-10-17）

- [独立静态审计报告](docs/reviews/REVIEW-20261017-001.md)：以 main@f909164 为基线；问题清单、源码证据、验收门禁。
- [统一 Agent/Git 交接协议](docs/AGENT_HANDOFF_PROTOCOL.md)：Executor/Reviewer 职责、分支/commit、状态机及验收证据规范。
- [下一轮整改任务单](handoff/REMEDIATION-20261017-001.md)：Wave A 数据、Wave B 识别、Wave C 回测。
- [交接报告模板](handoff/HANDOFF_TEMPLATE.md)：所有 AI 提交时按同一 schema 记录。

**重要：当前 18 passed 来源于原开发报告，未完成独立实测验收；暂不得将 SYNTHETIC_DEMO 的 GRID/MEDIUM 识别结果解释为用户真实机器人的策略。**
