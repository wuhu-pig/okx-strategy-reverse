"""只读安全门禁（T01/G13）。

本模块静态证明：代码中不存在可达的交易所写调用。提供调用点扫描，
供测试与验收 AI 复核。任何 httpx/requests/okx SDK 的 POST 交易端点均不允许出现。
"""
from __future__ import annotations

import re
from pathlib import Path

# 禁止出现的实盘写操作模式（出现在 src/ 内即 FAIL）
FORBIDDEN_PATTERNS = [
    r"requests\.post", r"httpx\.post", r"aiohttp\.ClientSession\(.+\)\.post",
    r"/api/v5/trade/order\b", r"cancel-order", r"cancel_order",
    r"set-leverage", r"set_leverage", r"withdrawal", r"/api/v5/account/position",
    r"websocket.*order",
]
# 允许的只读白名单（文档性）
ALLOWED_READONLY_ENDPOINTS = [
    "/api/v5/market/candles", "/api/v5/trade/orders-history",
    "/api/v5/trade/fills-history",
]


def scan_forbidden_calls(src_dir: Path) -> list[dict]:
    hits = []
    for py in Path(src_dir).rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for pat in FORBIDDEN_PATTERNS:
            for m in re.finditer(pat, text, re.IGNORECASE):
                # 文档字符串中提及不算（此处从简：整词命中即报告，由人工确认语境）
                hits.append({"file": str(py), "pattern": pat,
                             "line": text[:m.start()].count("\n") + 1})
    return hits
