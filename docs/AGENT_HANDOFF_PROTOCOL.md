---
document_type: AGENT_HANDOFF_PROTOCOL
schema_version: 1.0
protocol_id: OKX-HANDOFF-001
effective_date: 2026-10-17
scope: okx-strategy-reverse
---

# OKX 多 Agent 协作与 Git 交接协议 v1.0

## 1. 职责与权限

| 角色 | 职责 | 禁止 |
|---|---|---|
| Architect（ChatGPT/需求方） | 定义目标、风险、验收门槛、审查静态证据 | 将猜测写成已验证事实 |
| Executor（本地 Codex 或其他开发 AI） | 领任务、修代码、增加回归测试、执行命令、提交 PR 和执行报告 | 修改验收结果、跳过失败、不经授权执行真实交易 |
| Reviewer（独立 AI） | 基于**新** commit 独立运行、构造反例、记录复现和结论 | 用 Executor 自报结果代替独立复测、未经授权改业务代码 |
| Owner（用户） | 提供真实数据、决定是否接受风险、批准合并/上线 | 不适用 |

**单一事实来源**：Git commit SHA + 仓库中已提交的 Markdown 交接文件。聊天、截图、终端临时输出不是唯一权威证据。接手 AI 必须先执行 git fetch/pull，核实当前 SHA 和协议；与所写 base_sha 不同则停止并说明差异，不可默默在错的版本上操作。

## 2. 工作流与状态机

需求/审计 OPEN → Executor IN_PROGRESS → Executor READY_FOR_REVIEW → Reviewer PASS/FAIL → 失败则 NEEDS_FIX 回 Executor；通过且 Owner 同意才 ACCEPTED/MERGED。尚未执行测试用 NOT_RUN，遇到无法完成标记 BLOCKED 并写阻塞证据。

**禁止**使用“全部完成”掩盖 Partial/Not Implemented/Not Tested。一个任务可以有多次执行尝试，每次唯一 run_id；审计/任务 ID 在多次尝试中保持不变。

## 3. Git 规范（适用于之后所有 Agent）

- 修复分支：fix/OKX-P0-01-signal-causality、fix/OKX-P0-04-import-history；不要直接提交未经审查的算法修复到 main。
- 单个 PR 处理一个问题或高度相关的小组。必须包含关闭的 Issue/审计 ID、被修改模块、测试用例和原始失败复现。
- 统一 commit message（主体）格式：type(scope): summary [issue-id]
  - type：audit/docs/test/fix/refactor/feat
  - scope：ingest/ledger/inference/backtest/report/security/handoff
  - 示例：fix(inference): enforce causal signal matching [OKX-P0-01]
  - 示例：test(ingest): reject cross-source duplicate fills [OKX-P0-04]
  - 本次审计文档可以直接提交 main，不含程序变更；将审计文档与算法修复拆分提交。
- PR 标题：[OKX-P0-01] Causal signal matching — code + tests
- 严禁 git push --force 到共享分支，严禁覆盖无关文件，严禁在公开仓库提交 API key、账户导出原件、UID、资产、私人订单。
- 正式验收以 SHA 为准，任何修复或追加提交都会使先前的 PASS 失效，须重新验收该 SHA。

## 4. 交接报告统一 schema (Handoff v1)

使用 handoff/HANDOFF_TEMPLATE.md，生成以下两类报告，**提交进 Git**：
- Executor：handoff/executions/EXEC-<run_id>.md
- Reviewer：handoff/reviews/REVIEW-<run_id>.md

YAML frontmatter 必填字段：

- schema_version: 1.0
- document_type: EXECUTION_REPORT 或 REVIEW_REPORT
- run_id: YYYYMMDDTHHMMSSZ-<short-tag>（唯一）
- role: Executor / Reviewer
- base_sha, head_sha（至少 40 位或填 PENDING_COMMIT 并在提交后补全；不能填错）
- branch, task_ids（数组）, audit_reference, status
- data_class: SYNTHETIC_DEMO / REDACTED_REAL / REAL_PRIVATE / NO_DATA
- code_modified: true / false
- tested_sha: 必填；未运行填 NOT_RUN
- handoff_to: Reviewer / Executor / Owner

正文固定 7 节：

1. **Scope**：目标及不在本次范围的事项。
2. **Changes**：实际变更的文件、函数、行为和对应 task ID。
3. **Evidence**：输入路径及 SHA-256（脱敏）、测试数据来源、复现命令、stdout/exit code，绝不可只写“测试通过”。
4. **Results**：逐项验收表：Axx、Expected、Observed、PASS/FAIL/NOT_RUN、证据文件。
5. **Risks**：P0/P1/P2 未关闭项、数据不完整、剩余不确定性。
6. **Decision**：READY_FOR_REVIEW / CHANGES_REQUIRED / APPROVED / BLOCKED，仅 Reviewer 可 APPROVED。
7. **Next Handoff**：下一角色、下一动作、需读取的 commit/PR/文件。

报告只允许引用当前 tested_sha 产生的日志和制品；旧报告必须明确标记为历史参考，不得复制旧 PASS 当新 PASS。

## 5. 机器可读的验收约束

- 每个整改 ID 必须对应至少 1 个应失败的旧实现复现（regression/negative）+ 至少 1 个修复后的正例 + 不影响邻近功能的回归测试。
- “PASS” 必须写明具体命令、工作目录、退出码、测试数、输入数据类别、运行环境和 evidence 文件。
- 验收覆盖的 main commit 与实际 tested_sha 不同：结论一律 NOT_VALID_FOR_CURRENT_HEAD。
- 若 API/账户数据未接入，不得声称真实策略已确认；如数据有缺口，结论 INSUFFICIENT_DATA/UNDETERMINED。
- 三层结论独立呈现：observed facts / hypotheses / validated executable replay，不可混成一个 “strategy_class=GRID 即复现成功”。

## 6. 公共仓库隐私与交易安全

- 真实 OKX 订单/成交 CSV、密钥、token、Cookie、设备路径中的用户信息不得进入公开仓库。只提交脱敏或合成最小 fixture。真实数据本地运行，报告引用 hash + 聚合统计。
- 默认只读离线；任何交易、撤单、账户变更、资金划转和写权限 API 均不在本项目范围。新增 API 必须独立通过网络负面测试与只读权限验证。
- 报告不能含“盈利保证”或未经证据支持的高可信度策略结论。
