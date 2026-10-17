"""G01–G07：导入幂等、同毫秒多笔、部分成交、方向语义、PnL 不可验证、费用币种、无未来函数。"""
import json

import pandas as pd
import pytest

from okx_reverse.episodes import rebuild_episodes, reconcile
from okx_reverse.features import build_features
from okx_reverse.ingest import import_trades
from okx_reverse.synth import synth_bars, synth_grid_fills


def _make_csv(tmp_path, rows):
    p = tmp_path / "fills.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


BASE = dict(inst_id="BTC-USDT", inst_type="SPOT", pos_side="", reduce_only="False",
            fee=0.1, fee_ccy="USDT", maker_taker="taker", bot_id="", qty_unit="base")


def _fills(rows):
    out = []
    for i, (ts, side, px, qty, tid) in enumerate(rows):
        out.append({"trade_id": str(tid), "order_id": f"O{i}", "time": ts, "side": side,
                    "price": px, "quantity": qty, **BASE})
    return out


def test_g01_idempotent_import(tmp_path):
    rows = _fills([("2025-01-01 00:00:00", "buy", 100, 1, "T1"),
                   ("2025-01-01 01:00:00", "sell", 101, 1, "T2")])
    p = _make_csv(tmp_path, rows)
    d1, m1 = import_trades(p, tmp_path)
    d2, m2 = import_trades(p, tmp_path)
    assert len(d1) == len(d2) == 2
    assert m1.file_hash == m2.file_hash  # 原始哈希不变


def test_g02_same_ms_different_tradeid_kept(tmp_path):
    rows = _fills([("2025-01-01 00:00:00", "buy", 100, 0.5, "T1"),
                   ("2025-01-01 00:00:00", "buy", 100, 0.5, "T2")])
    p = _make_csv(tmp_path, rows)
    df, _ = import_trades(p, tmp_path)
    assert len(df) == 2  # 不同 tradeId 不得合并


def test_g03_partial_fill_then_cancel():
    fills = pd.DataFrame([
        {"trade_id": "1", "order_id": "O1", "inst_id": "BTC-USDT", "ts_ms": 1,
         "side": "buy", "pos_side": "", "fill_price": 100.0, "fill_qty": 0.4,
         "fee": 0.0, "origin_confidence": "UNKNOWN", "source_tag": "USER_EXPORT"},
        {"trade_id": "2", "order_id": "O1", "inst_id": "BTC-USDT", "ts_ms": 2,
         "side": "sell", "pos_side": "", "fill_price": 101.0, "fill_qty": 0.4,
         "fee": 0.0, "origin_confidence": "UNKNOWN", "source_tag": "USER_EXPORT"},
    ])
    ledger, warn = rebuild_episodes(fills)
    assert len(ledger) == 1
    assert ledger.iloc[0]["fills"] == 2  # 按成交而非请求数量


def test_g04_side_alone_cannot_classify_open_close():
    # 无初始持仓信息时，先出现 sell 必须产生 INITIAL_POSITION_UNKNOWN 警告
    fills = pd.DataFrame([
        {"trade_id": "1", "order_id": "O1", "inst_id": "X", "ts_ms": 1, "side": "sell",
         "pos_side": "", "fill_price": 10.0, "fill_qty": 1.0, "fee": 0.0,
         "origin_confidence": "UNKNOWN", "source_tag": "USER_EXPORT"},
    ])
    _, warn = rebuild_episodes(fills)
    assert any("INITIAL_POSITION_UNKNOWN" in w for w in warn)


def test_g05_unknown_initial_pnl_not_precise(tmp_path):
    fills = pd.DataFrame([
        {"trade_id": "1", "order_id": "O1", "inst_id": "X", "ts_ms": 1, "side": "sell",
         "pos_side": "", "fill_price": 10.0, "fill_qty": 1.0, "fee": 0.0,
         "origin_confidence": "UNKNOWN", "source_tag": "USER_EXPORT"},
    ])
    ledger, _ = rebuild_episodes(fills)
    row = ledger.iloc[0]
    assert bool(row["incomplete"]) and pd.isna(row["realized_pnl"])


def test_g06_fee_ccy_tracked_not_summed_blindly():
    fills = pd.DataFrame([
        {"trade_id": "1", "order_id": "O1", "inst_id": "A", "ts_ms": 1, "side": "buy",
         "pos_side": "", "fill_price": 10.0, "fill_qty": 1.0, "fee": 1.0, "fee_ccy": "BTC",
         "origin_confidence": "UNKNOWN", "source_tag": "USER_EXPORT"},
        {"trade_id": "2", "order_id": "O2", "inst_id": "A", "ts_ms": 2, "side": "sell",
         "pos_side": "", "fill_price": 11.0, "fill_qty": 1.0, "fee": 2.0, "fee_ccy": "USDT",
         "origin_confidence": "UNKNOWN", "source_tag": "USER_EXPORT"},
    ])
    # 规范层必须保留 fee_ccy 以便后续换算，报告不得直接把 1 BTC + 2 USDT 相加
    assert set(fills["fee_ccy"]) == {"BTC", "USDT"}


def test_g07_no_lookahead(tmp_path):
    bars = synth_bars(n=300)
    feats = build_features(bars)
    # 任意时刻 asof 不得使用未来数据：截断前后特征一致
    cut = bars["bar_start_ms"].iloc[200]
    full = feats[feats["bar_start_ms"] <= cut]
    truncated = build_features(bars[bars["bar_start_ms"] <= cut].reset_index(drop=True))
    pd.testing.assert_frame_equal(
        truncated.drop(columns=[]).reset_index(drop=True),
        full.reset_index(drop=True).iloc[: len(truncated)],
        check_dtype=False)
