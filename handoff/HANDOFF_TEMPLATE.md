---
schema_version: 1.0
document_type: EXECUTION_REPORT
run_id: YYYYMMDDTHHMMSSZ-executor-01
role: Executor
project: okx-strategy-reverse
audit_reference: OKX-REV-20261017-001
task_ids: [OKX-P0-01]
base_sha: REPLACE_WITH_40_CHARACTER_PARENT_SHA
head_sha: PENDING_COMMIT
tested_sha: NOT_RUN
branch: fix/OKX-P0-01-signal-causality
status: IN_PROGRESS
data_class: SYNTHETIC_DEMO
code_modified: true
handoff_to: Reviewer
---

# AGENT HANDOFF / v1.0 复制模板

> 本模板用于 Executor 或 Reviewer。Reviewer 将 document_type 改为 REVIEW_REPORT、role 改为 Reviewer、handoff_to 改为 Executor/Owner；不要将未运行记为 PASS。详见 docs/AGENT_HANDOFF_PROTOCOL.md。

## 1. Scope

- 问题/验收 ID：
- 本轮计划：
- 本轮明确不做：

## 2. Changes

| 文件 | 函数/范围 | 修改行为 | 对应审计 ID |
|---|---|---|---|
| path/to/file.py | method | description | OKX-P0-01 |

## 3. Evidence

- git HEAD：
- 工作目录 / Python / 依赖版本：
- 数据类型：SYNTHETIC_DEMO / REDACTED_REAL / REAL_PRIVATE / NO_DATA
- 输入文件 SHA-256（不得提交私有源数据）：
- 重现旧缺陷的命令与 stdout、exit code：
- 修复后测试命令与 stdout、exit code：
- Evidence 附件相对路径及哈希：

## 4. Results

| Acceptance ID | Expected | Observed | PASS/FAIL/NOT_RUN | Evidence |
|---|---|---|---|---|
| A01 | 未来信号不能匹配先前成交 | 待实测 | NOT_RUN | - |

## 5. Risks

- P0：
- P1：
- P2：
- 数据缺口和不能证明的事情：

## 6. Decision

- EXEC：READY_FOR_REVIEW / BLOCKED
- REVIEW：APPROVED / CHANGES_REQUIRED / BLOCKED
- 决定依据（独立测试摘要）：

## 7. Next Handoff

- 接手角色：
- 仓库 / 分支 / HEAD SHA / PR：
- 优先查看文件：
- 下一步确定动作：

## 8. Git 提交格式示例（提交时使用）

Commit subject: fix(inference): enforce causal signal matching [OKX-P0-01]

Commit body:
- Audit-Ref: OKX-REV-20261017-001
- Task-IDs: OKX-P0-01
- Tests: python -m pytest tests/test_causal_signal.py -q (n passed, exit=0)
- Data-Class: SYNTHETIC_DEMO
- Handoff: handoff/executions/EXEC-YYYYMMDDTHHMMSSZ-executor-01.md
- Known-Limitations: <explicit or none>

注意：每次实际提交后，报告中的 head_sha/tested_sha 必须是准确值；如果交接报告与代码在同一次提交造成自引用，可将报告中的 head_sha 写 PENDING_COMMIT，随后追加单独 metadata-only commit 固定已完成代码 SHA；始终明确 tested_sha 与最终 HEAD 的差异。
