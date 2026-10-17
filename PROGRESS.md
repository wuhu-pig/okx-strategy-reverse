# 项目进度（PROGRESS）

> 更新：2026-10-17 13:15 (Asia/Shanghai)｜状态：T01–T10 完成，等待独立 AI 验收（T12）

## 当前进度总览

| 阶段 | 状态 | 说明 |
|---|---|---|
| T01 工程初始化 / 安全门禁 | ✅ Done | CLI 六命令、只读门禁（无任何交易所写端点） |
| T02 导入/映射/归档 | ✅ Done | CSV/XLSX、中英表头映射、sha256 快照、幂等去重 |
| T03 归属与产品识别 | 🟡 Partial | bot_id→CONFIRMED_BOT；缺 AMBIGUOUS 启发式（P2） |
| T04 Episode 重建/对账 | ✅ Done | 净持仓开平仓回合、部分成交、对账异常表 |
| T05 行情与特征 | ✅ Done | 严格无未来函数（bar_end_ms ≤ 决策时刻） |
| T06 结构检测器 | ✅ Done | 网格算术/几何、DCA 固定/递增/倍增、定时定额 |
| T07 信号归因 + 样本外 | ✅ Done | 6 规则 × 训练/验证/测试三段冻结评估 |
| T08 近似策略 JSON + 回测 | ✅ Done | 保守事件驱动回测（下根 K 线开盘成交） |
| T09 风险分析 | ✅ Done | Episode PnL、费用单列、初始资金未知→UNVERIFIABLE |
| T10 可视化/一键 demo | ✅ Done | report.html（买卖点/持仓/RSI/净值） |
| T11 真实数据接入 | 🟡 Partial | 文件导入可用；OKX 只读 API 适配器未实现（可选项） |
| T12 独立 AI 验收 | ⬜ Pending | 见 `handoff/EXECUTION_REPORT.md` 复核命令 |

## 验证状态

- pytest：**18 passed / 0 failed**（G01–G18 门禁，1.5s，离线无凭证）
- demo 端到端：合成网格数据 → `SYNTHETIC_DEMO / GRID / MEDIUM`，`lookahead_check: PASS`

## 待办（按优先级）

1. **P1** 合约（SWAP/FUTURES）资金费率、双向持仓 PnL 复原
2. **P1** OKX 只读 API 适配器（orders-history / fills-history，Read-only key）
3. **P1** 把 DCA 合成数据接入 infer 主流程（现仅用于检测器测试）
4. **P2** 归属 PROBABLE_BOT 时序启发式；回测 DSL 支持加仓状态机；报告压力测试面板

## 如何继续（接手指南）

```powershell
$py='C:\Users\xin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'  # 或任意 Python 3.11+
Set-Location okx-strategy-reverse
$env:PYTHONPATH='src'
& $py -m pytest                # 应 18 passed
& $py -m okx_reverse.cli demo  # 一键合成演示
& $py -m okx_reverse.cli import --path <你的OKX成交导出.csv>
& $py -m okx_reverse.cli infer --market <K线.csv>
& $py -m okx_reverse.cli report --market <K线.csv>
```

交接细节（含真实运行输出、P0/P1/P2 清单、证据文件哈希）见
[`handoff/EXECUTION_REPORT.md`](handoff/EXECUTION_REPORT.md)。

## 安全边界

只读 / 离线：本项目不存在实盘下单、撤单、改杠杆、提币等任何交易所写调用
（`src/okx_reverse/security.py` 静态扫描，测试 G13 验证）。不请求、不存储 API Key。
