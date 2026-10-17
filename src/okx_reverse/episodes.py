"""T04：订单-成交-仓位-Episode 重建与对账（OKX-P0-05 修复版）。

账本模型：逐笔现金流/持仓更新。
- Episode：持仓从 0 → 开仓 → 回到 0 的一个回合；ID 单调递增，不跳号。
- 跨零反转：一笔成交跨越 0 仓时拆分为「平旧仓 + 开新仓」两段处理。
- 费用：按币种记账（fees_by_ccy），每回合重置；任一费用币种 ≠ 计价币且无兑换率时，
  realized_pnl 不输出精确值，pnl_status = UNVERIFIABLE_FEE_CCY。
- 已实现盈亏在每次减仓时按当时加权均价结转（部分减仓正确）。
- 先出现 sell（现货卖空不可能）→ INITIAL_POSITION_UNKNOWN 警告，回合标 incomplete。
"""
from __future__ import annotations

import json

import pandas as pd

LEDGER_COLUMNS = [
    "episode_id", "inst_id", "pos_side", "side", "open_ts_ms", "close_ts_ms",
    "fills", "max_qty", "avg_entry_price", "avg_exit_price",
    "realized_pnl", "fees_quote", "fees_by_ccy", "pnl_status",
    "close_price_ref", "incomplete",
]


def reconcile(fills: pd.DataFrame) -> pd.DataFrame:
    """订单级对账：同一 order_id 的 fill 合理性检查。"""
    exc = []
    if "order_id" not in fills.columns:
        return pd.DataFrame(columns=["order_id", "issue"])
    for oid, g in fills[fills["order_id"].astype(str).str.len() > 0].groupby("order_id"):
        if g["fill_qty"].isna().any():
            exc.append({"order_id": oid, "issue": "FILL_QTY_MISSING"})
        if g["fill_price"].isna().any():
            exc.append({"order_id": oid, "issue": "FILL_PRICE_MISSING"})
        if g["inst_id"].nunique() > 1:
            exc.append({"order_id": oid, "issue": "MULTIPLE_INSTRUMENTS"})
    return pd.DataFrame(exc, columns=["order_id", "issue"])


def rebuild_episodes(fills: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """返回 (episode_ledger, warnings)。"""
    warnings: list[str] = []
    if fills.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS), ["NO_FILLS"]

    all_rows: list[dict] = []
    for inst_id, g in fills.groupby("inst_id"):
        g = g.sort_values("ts_ms")
        quote_ccy = _infer_quote(inst_id, g)
        if (g["side"] == "sell").iloc[0]:
            warnings.append(f"INITIAL_POSITION_UNKNOWN:{inst_id}")
        # 双向持仓按 pos_side 独立建账
        pos_sides = g["pos_side"].astype(str)
        if pos_sides.str.len().gt(0).any() and not pos_sides.isin(["net", "nan", ""]).all():
            for ps, gg in g.groupby(pos_sides):
                all_rows += _ledger_for_stream(gg, inst_id, str(ps), quote_ccy, warnings)
        else:
            all_rows += _ledger_for_stream(g, inst_id, "net", quote_ccy, warnings)

    ledger = pd.DataFrame(all_rows, columns=LEDGER_COLUMNS)
    return ledger, warnings


def _infer_quote(inst_id: str, g: pd.DataFrame) -> str:
    """计价币推断：优先从 inst_id 后缀（-USDT 等），否则从常见 fee_ccy。"""
    if isinstance(inst_id, str) and "-" in inst_id:
        return inst_id.split("-")[-1]
    fccy = [c for c in g.get("fee_ccy", pd.Series(dtype=str)).astype(str).unique() if c]
    return fccy[0] if len(set(fccy)) == 1 else "UNKNOWN"


def _ledger_for_stream(g: pd.DataFrame, inst_id: str, pos_side: str,
                       quote_ccy: str, warnings: list[str]) -> list[dict]:
    """对一个时间有序的成交流执行逐笔账本，返回该流所有闭合/未闭合回合。"""
    rows: list[dict] = []
    ep_seq = 0
    # 开仓侧状态
    side = None            # 'buy'(多) / 'sell'(空)
    open_ts = None
    entry_qty = 0.0
    entry_cost = 0.0       # 加权成本累计（按绝对数量）
    realized = 0.0         # 本回合已实现毛盈亏（计价币）
    fees: dict[str, float] = {}
    n_fills = 0
    max_pos = 0.0
    exit_qty = 0.0
    exit_cost = 0.0
    fee_mixed = False
    last_avg_entry = None

    def open_new(s, ts):
        nonlocal side, open_ts, entry_qty, entry_cost, realized, fees, n_fills, max_pos, exit_qty, exit_cost, fee_mixed, ep_seq, last_avg_entry
        ep_seq += 1
        side, open_ts = s, ts
        entry_qty = entry_cost = realized = 0.0
        fees = {}
        n_fills = 1  # 触发开仓的这笔成交即本回合第一笔
        max_pos = 0.0
        exit_qty = exit_cost = 0.0
        fee_mixed = False
        last_avg_entry = None

    def close(close_ts, close_px, incomplete):
        nonlocal ep_seq
        avg_entry = (entry_cost / entry_qty) if entry_qty else last_avg_entry
        avg_exit = exit_cost / exit_qty if exit_qty else None
        fee_quote = fees.get(quote_ccy, 0.0)
        other = {k: v for k, v in fees.items() if k != quote_ccy and v != 0}
        if other:
            status = "UNVERIFIABLE_FEE_CCY"
            pnl = None  # 无兑换率：禁止伪精确净收益
        else:
            status = "VERIFIED" if not incomplete else "PARTIAL"
            pnl = realized - fee_quote if exit_qty else None
        rows.append({
            "episode_id": f"{inst_id}_{pos_side}_{ep_seq}",
            "inst_id": inst_id, "pos_side": pos_side, "side": side,
            "open_ts_ms": open_ts, "close_ts_ms": close_ts if not incomplete else None,
            "fills": n_fills, "max_qty": max_pos,
            "avg_entry_price": avg_entry, "avg_exit_price": avg_exit,
            "realized_pnl": pnl,
            "fees_quote": fee_quote,
            "fees_by_ccy": json.dumps(fees, ensure_ascii=False),
            "pnl_status": status,
            "close_price_ref": close_px, "incomplete": incomplete,
        })

    for r in g.itertuples(index=False):
        qty = float(r.fill_qty or 0.0)
        px = float(r.fill_price or 0.0)
        fccy = str(getattr(r, "fee_ccy", "") or quote_ccy)
        signed = qty if r.side == "buy" else -qty
        n_fills += 1

        # 无持仓：先开新仓（必须在费用累计前，避免新回合费用被重置）
        if side is None:
            open_new(r.side, r.ts_ms)
        fees[fccy] = fees.get(fccy, 0.0) + float(r.fee or 0.0)
        if fccy != quote_ccy:
            fee_mixed = True
        # 反向成交：先按均价结转平仓，必要时跨零反手
        if r.side != side:
            # 结转可平部分
            closable = min(qty, entry_qty)
            if closable > 0 and entry_qty > 0:
                avg_e = entry_cost / entry_qty
                realized += (px - avg_e) * closable * (1 if side == "buy" else -1)
                entry_cost -= avg_e * closable
                entry_qty -= closable
                exit_qty += closable
                exit_cost += px * closable
            remain = qty - closable
            if remain > 1e-12:
                # 跨零反手：闭合当前回合，剩余数量开反向新仓
                close(r.ts_ms, px, incomplete=False)
                open_new(r.side, r.ts_ms)
                entry_qty = remain
                entry_cost = px * remain
                last_avg_entry = px
                fees = {fccy: 0.0}  # 新回合费用从 0 起；该笔费用已计入旧回合
                n_fills = 1
                # 反手后该笔费用归属旧回合（上面已累计），新回合不重复计
                warnings.append(f"INITIAL_POSITION_UNKNOWN:{inst_id}:CROSS_ZERO_REVERSAL")
            if entry_qty <= 1e-12 and not (remain > 1e-12):
                close(r.ts_ms, px, incomplete=False)
                side = None
        else:
            entry_qty += qty
            entry_cost += px * qty
            last_avg_entry = entry_cost / entry_qty
        max_pos = max(max_pos, entry_qty)

    if side is not None:
        close(None, None, incomplete=True)
    return rows
