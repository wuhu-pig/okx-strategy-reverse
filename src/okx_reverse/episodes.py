"""T04：订单-成交-仓位-Episode 重建与对账。

约定：净持仓模式（net）。buy 增持、sell 减持；仅当持仓从 0 变非 0 视为开仓，
回到 0 视为平仓闭合一个 Episode。若首笔成交时已假设无初始仓，但存在先卖后买的
迹象（现货卖空不可能），标记 INITIAL_POSITION_UNKNOWN。双向持仓按 pos_side 分组。
"""
from __future__ import annotations

import pandas as pd


def rebuild_episodes(fills: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """返回 (episode_ledger, warnings)。episode_ledger 列：
    episode_id, inst_id, side, open_ts_ms, close_ts_ms, fills, max_qty,
    avg_entry_price, avg_exit_price, realized_pnl, fees_quote, incomplete
    """
    warnings: list[str] = []
    rows: list[dict] = []
    if fills.empty:
        return pd.DataFrame(columns=["episode_id"]), ["NO_FILLS"]

    for inst_id, g in fills.groupby("inst_id"):
        g = g.sort_values("ts_ms")
        if (g["side"] == "sell").iloc[0] and g["pos_side"].astype(str).isin(["", "net", "nan"]).all():
            warnings.append(f"INITIAL_POSITION_UNKNOWN:{inst_id}")
        groups = [("net", g)]
        if g["pos_side"].astype(str).str.len().gt(0).any() and not g["pos_side"].astype(str).isin(["net", "nan"]).all():
            groups = [(ps, gg) for ps, gg in g.groupby("pos_side")]

        for pos_side, gg in groups:
            pos = 0.0
            cost = 0.0
            ep_id = 0
            open_side, open_ts = None, None
            entry_notional = 0.0
            exit_notional = 0.0
            entry_qty = 0.0
            exit_qty = 0.0
            fees = 0.0
            max_pos = 0.0
            n_fills = 0

            def close_row(close_ts, close_price, incomplete):
                nonlocal ep_id
                ep_id += 1
                avg_entry = entry_notional / entry_qty if entry_qty else None
                avg_exit = exit_notional / exit_qty if exit_qty else None
                pnl = None
                if avg_entry and avg_exit:
                    pnl = (avg_exit - avg_entry) * min(entry_qty, exit_qty) * (1 if open_side == "buy" else -1)
                rows.append({
                    "episode_id": f"{inst_id}_{pos_side}_{ep_id}",
                    "inst_id": inst_id, "pos_side": pos_side, "side": open_side,
                    "open_ts_ms": open_ts, "close_ts_ms": close_ts,
                    "fills": n_fills, "max_qty": max_pos,
                    "avg_entry_price": avg_entry, "avg_exit_price": avg_exit,
                    "realized_pnl": pnl, "fees_quote": fees,
                    "close_price_ref": close_price, "incomplete": incomplete,
                })

            for r in gg.itertuples(index=False):
                qty = float(r.fill_qty or 0.0)
                px = float(r.fill_price or 0.0)
                fees += float(r.fee or 0.0)
                n_fills += 1
                signed = qty if r.side == "buy" else -qty
                if pos == 0.0:
                    ep_id += 1
                    open_side, open_ts = r.side, r.ts_ms
                    entry_notional = entry_qty = exit_notional = exit_qty = 0.0
                if (pos >= 0 and signed > 0) or (pos <= 0 and signed < 0):
                    entry_notional += px * qty
                    entry_qty += qty
                else:
                    exit_notional += px * qty
                    exit_qty += qty
                prev = pos
                pos += signed
                max_pos = max(max_pos, abs(pos))
                if abs(prev) > 0 and abs(pos) < abs(prev):
                    pass  # 部分减仓已在上面统计
                if abs(pos) < 1e-12:
                    close_row(r.ts_ms, px, incomplete=False)
                    pos = 0.0
                    n_fills = 0
            if abs(pos) > 1e-12:
                close_row(None, None, incomplete=True)

    ledger = pd.DataFrame(rows)
    return ledger, warnings


def reconcile(fills: pd.DataFrame) -> pd.DataFrame:
    """订单级对账：同一 order_id 的 fill 数量与价格合理性检查。
    输出 reconciliation_exceptions.csv 内容。"""
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
