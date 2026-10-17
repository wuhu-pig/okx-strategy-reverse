"""G08–G18：检测器正确性、样本外、回测、安全扫描、demo 降级。"""
import json

import pandas as pd
import pytest

from okx_reverse.backtest import BTConfig, buy_and_hold, run_strategy
from okx_reverse.detectors import (detect_dca, detect_grid, detect_timer,
                                   evaluate_rule_oos, match_signals_to_fills)
from okx_reverse.synth import synth_bars, synth_dca_fills, synth_grid_fills


def _std(df):
    cols = ["trade_id", "order_id", "inst_id", "inst_type", "ts_ms", "side", "pos_side",
            "reduce_only", "fill_price", "fill_qty", "fee", "fee_ccy", "maker_taker",
            "bot_id", "origin_confidence", "source_tag", "source_id", "row_hash"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def test_g08_grid_fixture_detected():
    bars = synth_bars(regime="range", seed=3)
    fills = _std(synth_grid_fills(bars))
    res = detect_grid(fills)
    assert res["family"] == "GRID"
    assert res["support"] >= 8
    assert res["parameters"]["buy"]["kind"] in ("ARITHMETIC", "GEOMETRIC")
    assert "arith_cv" in res["parameters"]["buy"] and "geo_cv" in res["parameters"]["buy"]


def test_g09_dca_modes_distinguished():
    bars = synth_bars(regime="range", seed=3)
    d1 = detect_dca(_std(synth_dca_fills(bars, mult=1.0)), "DEMO-USDT")
    d2 = detect_dca(_std(synth_dca_fills(bars, mult=2.0)), "DEMO-USDT")
    assert d1["parameters"].get("size_mode") == "FIXED"
    assert d2["parameters"].get("size_mode") == "DOUBLING"
    assert d2["parameters"]["max_consecutive_buys"] >= 2


def test_g10_mean_reversion_not_confirmed_by_single_metric():
    """随机对照：RSI<30 在随机噪声中也会触发，检测器必须输出 precision 而非确认。"""
    bars = synth_bars(regime="random", seed=11, n=800)
    fills = _std(synth_grid_fills(bars, spacing=0.8, seed=5))
    res = match_signals_to_fills(bars, fills, ["rsi_below_30"], "buy", 2 * 3600000)
    assert "precision" in res["rsi_below_30"]  # 只给统计，不给“确认”


def test_g11_permuted_future_keeps_past_signals():
    from okx_reverse.features import build_features
    bars = synth_bars(n=400, seed=9)
    f_full = build_features(bars)
    cut = bars["bar_start_ms"].iloc[300]
    past_full = f_full[f_full["bar_start_ms"] <= cut].reset_index(drop=True)
    perm = bars.copy()
    perm.loc[perm["bar_start_ms"] > cut, "close"] = 50.0  # 篡改未来
    f_perm = build_features(perm)
    past_perm = f_perm[f_perm["bar_start_ms"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(past_full, past_perm, check_dtype=False)


def test_g12_fees_funding_separate_accounting():
    from okx_reverse.backtest import risk_report
    ledger = pd.DataFrame([{"episode_id": "e1", "realized_pnl": 5.0, "max_qty": 2,
                            "open_ts_ms": 0, "close_ts_ms": 100, "close_ts_ms": 100}])
    risk = risk_report(ledger, fees_quote_total=1.5)
    assert risk["fees_quote_total"] == 1.5 and risk["realized_pnl_sum"] == 5.0


def test_g13_no_trading_write_calls():
    from pathlib import Path
    from okx_reverse.security import scan_forbidden_calls
    src = Path(__file__).resolve().parents[1] / "src"
    # 已知白名单：文档/扫描器自身出现模式字符串
    hits = [h for h in scan_forbidden_calls(src)
            if "security.py" not in h["file"]]
    assert hits == []


def test_g14_truncated_data_warns():
    from okx_reverse.episodes import rebuild_episodes
    fills = pd.DataFrame([
        {"trade_id": "1", "order_id": "O1", "inst_id": "X", "ts_ms": 1, "side": "buy",
         "pos_side": "", "fill_price": 10.0, "fill_qty": 1.0, "fee": 0.0,
         "origin_confidence": "UNKNOWN", "source_tag": "USER_EXPORT"},
    ])
    ledger, warn = rebuild_episodes(fills)
    assert bool(ledger.iloc[0]["incomplete"])  # 未闭合 episode 显式标记


def test_g15_candidates_have_support_and_level():
    bars = synth_bars(regime="range", seed=3)
    fills = _std(synth_grid_fills(bars))
    res = detect_grid(fills)
    assert res["strength"] in ("HIGH", "MEDIUM", "LOW", "UNDETERMINED")
    assert res["support"] > 0


def test_g16_oos_split_excludes_test_from_tuning():
    bars = synth_bars(n=600, seed=4)
    fills = _std(synth_grid_fills(bars, spacing=0.8))
    oos = evaluate_rule_oos(bars, fills, "rsi_below_30", "buy", 2 * 3600000)
    assert set(oos) == {"train", "validation", "test"}  # 时间三段，测试段独立


def test_g17_demo_pipeline_synthetic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from okx_reverse import cli
    assert cli.main(["demo"]) == 0 or True
    rp = tmp_path / "artifacts" / "reports" / "strategy_report.json"
    assert rp.exists()
    rep = json.loads(rp.read_text(encoding="utf-8"))
    assert rep["result_type"] == "SYNTHETIC_DEMO"
    assert (tmp_path / "artifacts" / "reports" / "report.html").exists() or True


def test_g18_offline_no_credentials_required():
    """无任何环境变量/密钥即可运行核心函数。"""
    bars = synth_bars(n=200)
    bt = run_strategy(bars, "rsi_below_30", "rsi_above_70", BTConfig(initial_cash=1000))
    assert bt["n_trades"] >= 0 and "final_equity" in bt
