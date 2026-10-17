"""A07–A09（OKX-P0-05）：Episode ID 单调、每回合费用隔离、币种会计降级、跨零反转。"""
import pandas as pd
import pytest

from okx_reverse.episodes import rebuild_episodes


def _f(ts, side, px, qty, fee=0.0, fee_ccy="USDT", inst="X"):
    return {"trade_id": f"T{ts}", "order_id": f"O{ts}", "inst_id": inst, "inst_type": "SPOT",
            "ts_ms": ts, "side": side, "pos_side": "", "reduce_only": side == "sell",
            "fill_price": px, "fill_qty": qty, "fee": fee, "fee_ccy": fee_ccy,
            "origin_confidence": "UNKNOWN", "source_tag": "SYNTHETIC_DEMO"}


def _ledger(rows):
    fills = pd.DataFrame(rows)
    ledger, warn = rebuild_episodes(fills)
    return ledger.sort_values("episode_id").reset_index(drop=True), warn


def test_a07_episode_ids_monotonic_and_fees_isolated():
    """两个独立往返：ID 必须只有 1、2（旧实现 1、3、4…跳号）；费用各自隔离不跨回合累计。"""
    ledger, _ = _ledger([
        _f(1000, "buy", 100.0, 1.0, fee=0.1),
        _f(2000, "sell", 110.0, 1.0, fee=0.1),   # Episode 1 闭合
        _f(3000, "buy", 105.0, 1.0, fee=0.2),
        _f(4000, "sell", 115.0, 1.0, fee=0.2),   # Episode 2 闭合
    ])
    assert ledger["episode_id"].tolist() == ["X_net_1", "X_net_2"]
    # 旧实现：第 2 回合 fees 会包含第 1 回合费用（累计不重置）
    assert ledger["fees_quote"].tolist() == pytest.approx([0.2, 0.4])
    # 净盈亏含各自费用：ep1 = (110-100)*1 - 0.2 = 9.8；ep2 = 10 - 0.4 = 9.6
    assert ledger["realized_pnl"].tolist() == pytest.approx([9.8, 9.6])


def test_a08_mixed_fee_ccy_degrades_to_unverifiable():
    """BTC+USDT 混合手续费且无兑换率：净 PnL 不得输出伪精确值，状态 UNVERIFIABLE。"""
    ledger, warn = _ledger([
        _f(1000, "buy", 100.0, 1.0, fee=0.001, fee_ccy="BTC"),
        _f(2000, "sell", 110.0, 1.0, fee=0.5, fee_ccy="USDT"),
    ])
    row = ledger.iloc[0]
    assert row["pnl_status"] == "UNVERIFIABLE_FEE_CCY"
    assert pd.isna(row["realized_pnl"])
    assert set(json.loads(row["fees_by_ccy"])) == {"BTC", "USDT"}


def test_a09_cross_zero_reversal_and_initial_position_unknown():
    """跨零反转：多头平仓后反手做空，必须产出已闭合回合且方向正确；先卖警告保留。"""
    ledger, warn = _ledger([
        _f(1000, "buy", 100.0, 1.0),
        _f(2000, "sell", 110.0, 2.0),   # 平多 + 反手做空 1.0（旧实现一笔 sell 只减仓）
        _f(3000, "buy", 105.0, 1.0),    # 空头回补闭合
    ])
    assert any("INITIAL_POSITION_UNKNOWN" in w for w in warn)
    assert len(ledger) == 2
    shorts = ledger[ledger["side"] == "sell"]
    assert len(shorts) == 1 and bool(shorts.iloc[0]["incomplete"]) is False


import json  # noqa: E402  (used in a08)
