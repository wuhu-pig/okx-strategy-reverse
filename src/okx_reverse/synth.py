"""合成演示数据生成器（SYNTHETIC_DEMO，明确标注，绝不冒充用户账户数据）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def synth_bars(n=1500, start="2025-01-01", seed=7, regime="range") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if regime == "range":
        t = np.arange(n)
        close = 100 + 10 * np.sin(2 * np.pi * t / 240) + rng.normal(0, 0.4, n).cumsum() * 0.05
    elif regime == "trend":
        drift = np.concatenate([np.zeros(n // 3), np.linspace(0, 40, n // 3), np.full(n - 2 * n // 3, 40)])
        close = 100 + drift + rng.normal(0, 0.8, n).cumsum() * 0.08
    else:
        close = 100 + rng.normal(0, 1, n).cumsum()
    close = np.maximum(close, 1.0)
    start_ms = int(pd.Timestamp(start, tz="UTC").value // 10**6)
    rows = []
    for i, c in enumerate(close):
        o = close[i - 1] if i else c
        h = max(o, c) * (1 + abs(rng.normal(0, 0.002)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.002)))
        rows.append({"inst_id": "DEMO-USDT", "bar_start_ms": start_ms + i * 3600000,
                     "bar_end_ms": start_ms + (i + 1) * 3600000, "interval": "1h",
                     "open": o, "high": h, "low": l, "close": c,
                     "volume": abs(rng.normal(100, 20)), "confirmed": True})
    return pd.DataFrame(rows)


def synth_grid_fills(bars: pd.DataFrame, spacing=1.5, seed=7) -> pd.DataFrame:
    """合成网格机器人：价格每变动 spacing 就低买高卖。"""
    rng = np.random.default_rng(seed)
    close = bars["close"].values
    ts = bars["bar_end_ms"].values
    rows, last = [], None
    tid = 0
    for i in range(1, len(close)):
        px = close[i]
        if last is None or abs(px - last) >= spacing:
            side = "buy" if (last is None or px < last) else "sell"
            if last is None:
                side = "buy"
            tid += 1
            rows.append({"trade_id": f"SXG{tid:05d}", "order_id": f"OG{tid:05d}",
                         "inst_id": "DEMO-USDT", "inst_type": "SPOT",
                         "ts_ms": int(ts[i]), "side": side, "pos_side": "",
                         "reduce_only": False, "fill_price": round(float(px - (0.2 if side == 'buy' else -0.2)), 4),
                         "fill_qty": 1.0, "qty_unit": "base", "fee": 0.001 * px,
                         "fee_ccy": "USDT", "maker_taker": "maker", "bot_id": "demo_grid_bot",
                         "origin_confidence": "CONFIRMED_BOT", "source_tag": "SYNTHETIC_DEMO",
                         "source_id": "synthetic", "row_hash": f"h{tid}"})
            last = px if side == "buy" else px
            last = px
    return pd.DataFrame(rows)


def synth_dca_fills(bars: pd.DataFrame, drop_pct=0.03, mult=2.0, seed=7) -> pd.DataFrame:
    """合成马丁 DCA：每从近期高点下跌 drop_pct 加仓，规模倍增，反弹到均价上方 2% 平仓。"""
    close = bars["close"].values
    ts = bars["bar_end_ms"].values
    rows, tid = [], 0
    peak = close[0]
    layer, base_qty, avg = 0, 1.0, None
    cost = 0.0
    for i in range(len(close)):
        px = close[i]
        peak = max(peak, px)
        if avg is None and px <= peak * (1 - drop_pct):
            layer, base_qty = 1, 1.0
            qty = base_qty
            cost += qty * px
            avg = cost / qty
            tid += 1
            rows.append(_row(tid, ts[i], "buy", px, qty))
            peak = px
        elif avg is not None and px <= avg * (1 - drop_pct) and layer < 6:
            layer += 1
            qty = base_qty * (mult ** (layer - 1))
            cost += qty * px
            total_q = base_qty * sum(mult ** k for k in range(layer))
            avg = cost / total_q
            tid += 1
            rows.append(_row(tid, ts[i], "buy", px, qty))
        elif avg is not None and px >= avg * 1.02:
            total_q = base_qty * sum(mult ** k for k in range(layer))
            tid += 1
            rows.append(_row(tid, ts[i], "sell", px, total_q))
            layer, avg, cost, peak = 0, None, 0.0, px
    return pd.DataFrame(rows)


def _row(tid, ts, side, px, qty):
    return {"trade_id": f"SXD{tid:05d}", "order_id": f"OD{tid:05d}",
            "inst_id": "DEMO-USDT", "inst_type": "SPOT", "ts_ms": int(ts),
            "side": side, "pos_side": "", "reduce_only": side == "sell",
            "fill_price": round(float(px), 4), "fill_qty": float(qty), "qty_unit": "base",
            "fee": 0.001 * px * qty, "fee_ccy": "USDT", "maker_taker": "taker",
            "bot_id": "demo_dca_bot", "origin_confidence": "CONFIRMED_BOT",
            "source_tag": "SYNTHETIC_DEMO", "source_id": "synthetic", "row_hash": f"h{tid}"}


def write_demo_files(out_dir):
    """生成 3 组合成 CSV（网格、DCA、趋势行情），返回路径字典。"""
    from pathlib import Path
    out = Path(out_dir)
    (out / "generated").mkdir(parents=True, exist_ok=True)
    paths = {}
    bars = synth_bars(regime="range")
    bars.to_csv(out / "generated" / "demo_bars_range.csv", index=False)
    synth_grid_fills(bars).to_csv(out / "generated" / "demo_fills_grid.csv", index=False)
    synth_dca_fills(bars).to_csv(out / "generated" / "demo_fills_dca.csv", index=False)
    paths = {"bars": str(out / "generated" / "demo_bars_range.csv"),
             "grid": str(out / "generated" / "demo_fills_grid.csv"),
             "dca": str(out / "generated" / "demo_fills_dca.csv")}
    return paths
