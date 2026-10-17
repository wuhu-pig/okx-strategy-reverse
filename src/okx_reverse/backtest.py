"""T08/T09：近似策略离线回测 + 风险分析（事件驱动，保守模拟，无任何交易 API）。

策略 DSL（reconstructed_strategy.json 的 execution 部分）：
{"entry_rule": "...", "exit_rule": "...", "add_rule": {...} 可选,
 "fee_rate": 0.001, "initial_cash": 10000}
保守假设：信号在 K 线结束后生效，以下一根 K 线 open 成交（避免用当 K 收盘冒充触发价）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .detectors import SIGNAL_RULES
from .features import build_features


@dataclass
class BTConfig:
    initial_cash: float = 10000.0
    fee_rate: float = 0.001
    qty_per_trade: float = 0.0  # 0 = 每次用全部现金的 95%


def run_strategy(bars: pd.DataFrame, entry_rule: str, exit_rule: str,
                 cfg: BTConfig = BTConfig()) -> dict:
    """多頭现货式回测。返回 equity 曲线、交易列表与风险指标。"""
    f = build_features(bars).reset_index(drop=True)
    cash, qty = cfg.initial_cash, 0.0
    entry_px, fees_paid = 0.0, 0.0
    trades, equity = [], []
    pending_entry = pending_exit = False

    for i in range(len(f)):
        row = f.iloc[i]
        px = float(row["open"]) if np.isfinite(row["open"]) else float(row["close"])
        # 执行上一根 K 线产生的挂起决策
        if pending_exit and qty > 0:
            gross = qty * px
            fee = gross * cfg.fee_rate
            pnl = gross - fee - (entry_px * qty + qty * entry_px * cfg.fee_rate)
            trades.append({"entry_i": int(trade_entry_i), "exit_i": i, "pnl": pnl, "fees": fee})
            cash += gross - fee
            fees_paid += fee
            qty = 0.0
        if pending_entry and qty == 0:
            spend = cash * 0.95 if cfg.qty_per_trade <= 0 else cfg.qty_per_trade * px
            spend = min(spend, cash)
            if spend > 0 and px > 0:
                qty = spend / px
                fee = spend * cfg.fee_rate
                cash -= spend + fee
                fees_paid += fee
                entry_px = px
                trade_entry_i = i
        pending_entry = pending_exit = False
        # 信号（基于当前已结束 K 线），下一根 K 线执行
        if i + 1 < len(f):
            nxt_rule_in = SIGNAL_RULES.get(entry_rule)
            nxt_rule_out = SIGNAL_RULES.get(exit_rule)
            if nxt_rule_in and qty == 0 and bool(nxt_rule_in(row)):
                pending_entry = True
            if nxt_rule_out and qty > 0 and bool(nxt_rule_out(row)):
                pending_exit = True
        equity.append(cash + qty * (float(row["close"])))

    eq = pd.Series(equity, dtype=float)
    roll_max = eq.cummax()
    dd = (eq / roll_max - 1.0)
    closed = [t for t in trades]
    wins = [t for t in closed if t["pnl"] > 0]
    result = {
        "entry_rule": entry_rule, "exit_rule": exit_rule,
        "initial_cash": cfg.initial_cash, "final_equity": float(eq.iloc[-1]) if len(eq) else cfg.initial_cash,
        "net_pnl": float(eq.iloc[-1] - cfg.initial_cash) if len(eq) else 0.0,
        "max_drawdown": float(dd.min()) if len(dd) else 0.0,
        "n_trades": len(closed),
        "win_rate": (len(wins) / len(closed)) if closed else None,
        "profit_factor": (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in closed if t["pnl"] <= 0)))
                          if closed and any(t["pnl"] <= 0 for t in closed) else None,
        "total_fees": fees_paid,
        "equity": eq.tolist(),
        "bars": f[["bar_start_ms", "close"]].values.tolist(),
    }
    return result


def buy_and_hold(bars: pd.DataFrame, cfg: BTConfig = BTConfig()) -> dict:
    if bars.empty:
        return {"net_pnl": None}
    px0 = float(bars["open"].iloc[0])
    qty = cfg.initial_cash * 0.999 / px0
    eq = qty * bars["close"].astype(float)
    return {"net_pnl": float(eq.iloc[-1] - cfg.initial_cash),
            "max_drawdown": float((eq / eq.cummax() - 1).min())}


def risk_report(episodes: pd.DataFrame, fees_quote_total: float) -> dict:
    """基于 Episode 账本的风险分析。初始资金未知时标注 UNVERIFIABLE。"""
    out: dict = {"pnl_status": "VERIFIABLE_REALIZED_ONLY", "n_episodes": int(len(episodes))}
    if episodes.empty:
        out["pnl_status"] = "UNVERIFIABLE"
        out["reason"] = "无闭合 Episode 或初始持仓/资金未知"
        return out
    pnl = episodes["realized_pnl"].dropna().astype(float)
    if pnl.empty:
        out["pnl_status"] = "UNVERIFIABLE"
        return out
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    out.update({
        "realized_pnl_sum": float(pnl.sum()),
        "fees_quote_total": float(fees_quote_total),
        "win_rate": float(len(wins) / len(pnl)),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "max_single_loss": float(pnl.min()),
        "max_episode_qty": float(episodes["max_qty"].max()),
        "avg_hold_ms": float((episodes["close_ts_ms"] - episodes["open_ts_ms"]).dropna().mean()),
        "unverifiable_note": "初始资金/入金未知，绝对收益与账户级 MDD 不可验证（PNL_UNVERIFIABLE for account equity）",
    })
    return out
