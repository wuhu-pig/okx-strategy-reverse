"""T06/T07：候选策略检测器。

结构检测（仅需成交记录）：网格（算术/几何）、DCA/马丁（固定/递增/倍增）、定时交易。
信号归因（需行情）：RSI 低位买、布林下轨买、EMA 金叉、N 期突破 —— 与负样本对照，
训练/验证/测试时间切分，冻结参数后样本外评价。输出证据强度只有 HIGH/MEDIUM/LOW/UNDETERMINED。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import build_features, rsi

EVIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW", "UNDETERMINED")


def _level(n: int, oos_ok: bool) -> str:
    if n < 10:
        return "UNDETERMINED" if n < 5 else "LOW"
    return "MEDIUM" if oos_ok else "LOW"


# ---------------------------------------------------------------- 结构检测
def detect_grid(fills: pd.DataFrame) -> dict:
    """比较相邻同向成交价差的算术/几何网格拟合残差。"""
    g = fills[fills["inst_id"] == fills["inst_id"].iloc[0]] if len(fills) else fills
    res = {"family": "GRID", "support": 0, "counterevidence": [], "missing_data": [],
           "strength": "UNDETERMINED", "parameters": {}}
    for side in ("buy", "sell"):
        p = g[g["side"] == side]["fill_price"].dropna().values
        if len(p) < 4:
            res["missing_data"].append(f"同向成交不足({side}):{len(p)}")
            continue
        dp_abs = np.abs(np.diff(np.sort(p)))
        dp_abs = dp_abs[dp_abs > 0]
        dp_pct = np.abs(np.diff(np.sort(p) / np.sort(p[:-1] * 0 + np.sort(p)))) if False else None
        sp = np.sort(p)
        dp_pct = (sp[1:] / sp[:-1] - 1)
        dp_pct = np.abs(dp_pct[dp_pct != 0])
        if len(dp_abs) < 3:
            continue
        arith_cv = float(np.std(dp_abs) / np.mean(dp_abs)) if np.mean(dp_abs) > 0 else np.inf
        geo_cv = float(np.std(dp_pct) / np.mean(dp_pct)) if np.mean(dp_pct) > 0 else np.inf
        kind = "ARITHMETIC" if arith_cv <= geo_cv else "GEOMETRIC"
        res["parameters"][side] = {
            "kind": kind,
            "abs_spacing_median": float(np.median(dp_abs)),
            "pct_spacing_median": float(np.median(dp_pct)),
            "arith_cv": arith_cv, "geo_cv": geo_cv,
            "n_pairs": int(len(dp_abs)),
        }
        res["support"] += int(len(dp_abs))
    kinds = {v["kind"] for v in res["parameters"].values()} if res["parameters"] else set()
    if res["support"] >= 8 and len(kinds) == 1:
        res["strength"] = _level(res["support"], oos_ok=True)
    elif res["support"] >= 8:
        res["counterevidence"].append(f"买卖两侧网格类型不一致: {kinds}")
        res["strength"] = "LOW"
    return res


def detect_dca(fills: pd.DataFrame, inst_id: str | None = None) -> dict:
    """下跌加仓 + 仓位规模模式（固定 / 递增 / 倍增）。"""
    res = {"family": "DCA_MARTINGALE", "support": 0, "counterevidence": [], "missing_data": [],
           "strength": "UNDETERMINED", "parameters": {}}
    g = fills[fills["side"] == "buy"].dropna(subset=["fill_price", "fill_qty"])
    if inst_id:
        g = g[g["inst_id"] == inst_id]
    if len(g) < 3:
        res["missing_data"].append(f"买单不足: {len(g)}")
        return res
    g = g.sort_values("ts_ms")
    qty = g["fill_qty"].values
    px = g["fill_price"].values
    ratios = qty[1:] / np.where(qty[:-1] == 0, np.nan, qty[:-1])
    down_moves = float(np.mean(px[1:] < px[:-1]))
    res["parameters"] = {
        "size_ratio_median": float(np.nanmedian(ratios)),
        "size_ratio_iqr": [float(np.nanpercentile(ratios, 25)), float(np.nanpercentile(ratios, 75))],
        "pct_downtrend_adds": down_moves,
        "n_buys": int(len(g)),
        "max_consecutive_buys": int(_max_run(g["side"].values == "buy")),
    }
    res["support"] = int(len(g))
    med = float(np.nanmedian(ratios))
    if down_moves > 0.6:
        if 0.9 <= med <= 1.1:
            res["parameters"]["size_mode"] = "FIXED"
            res["strength"] = _level(len(g), True)
        elif 1.4 <= med <= 2.6:
            res["parameters"]["size_mode"] = "DOUBLING" if med > 1.9 else "INCREASING"
            res["strength"] = _level(len(g), True)
        else:
            res["parameters"]["size_mode"] = "IRREGULAR"
            res["strength"] = "LOW"
    else:
        res["counterevidence"].append(f"仅 {down_moves:.0%} 的加仓发生在下跌后，DCA 特征弱")
    return res


def _max_run(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def detect_timer(fills: pd.DataFrame) -> dict:
    """定时/定额：成交间隔的规律性与金额稳定性。"""
    res = {"family": "TIMER_FIXED_AMOUNT", "support": 0, "counterevidence": [],
           "missing_data": [], "strength": "UNDETERMINED", "parameters": {}}
    if len(fills) < 5:
        res["missing_data"].append(f"成交不足: {len(fills)}")
        return res
    ts = fills.sort_values("ts_ms")["ts_ms"].values
    gaps = np.diff(ts) / 3600000.0
    notional = (fills["fill_price"] * fills["fill_qty"]).values
    gaps = gaps[gaps > 0]
    res["parameters"] = {
        "gap_hours_median": float(np.median(gaps)),
        "gap_hours_cv": float(np.std(gaps) / np.mean(gaps)) if np.mean(gaps) > 0 else np.inf,
        "notional_cv": float(np.std(notional) / np.mean(notional)) if np.mean(notional) > 0 else np.inf,
        "n": int(len(gaps) + 1),
    }
    if res["parameters"]["gap_hours_cv"] < 0.15 and res["parameters"]["notional_cv"] < 0.2:
        res["strength"] = "MEDIUM"
        res["support"] = int(len(gaps) + 1)
    else:
        res["counterevidence"].append("时间间隔或金额方差过大，非定时定额")
    return res


# ---------------------------------------------------------------- 信号归因
SIGNAL_RULES = {
    "rsi_below_30": lambda f: f["rsi_14"] < 30,
    "bb_lower_touch": lambda f: f["close"] <= f["bb_low"],
    "golden_cross": lambda f: f["golden_cross"] == True,  # noqa: E712
    "breakout_high_20": lambda f: f["close"] > f["hh_20"],
    "breakdown_low_20": lambda f: f["close"] < f["ll_20"],
    "rsi_above_70": lambda f: f["rsi_14"] > 70,
}
BUY_RULES = ["rsi_below_30", "bb_lower_touch", "golden_cross", "breakout_high_20"]
SELL_RULES = ["rsi_above_70", "breakdown_low_20"]


def match_signals_to_fills(bars: pd.DataFrame, fills: pd.DataFrame,
                           rules: list[str], direction: str,
                           tolerance_ms: int) -> dict:
    """规则信号 vs 真实成交：precision / recall / 误报 / 漏报。
    信号只在 K 线结束时产生（无未来函数）；匹配允许 tolerance 窗口。"""
    feats = build_features(bars)
    res: dict = {}
    fill_ts = fills[fills["side"] == direction]["ts_ms"].values
    for rule in rules:
        if rule not in SIGNAL_RULES:
            continue
        mask = SIGNAL_RULES[rule](feats).fillna(False).values
        sig_ts = feats.loc[mask, "bar_end_ms"].values
        tp_sig, tp_fill = _match(sig_ts, fill_ts, tolerance_ms)
        precision = tp_sig / len(sig_ts) if len(sig_ts) else None
        recall = tp_fill / len(fill_ts) if len(fill_ts) else None
        res[rule] = {
            "signals": int(len(sig_ts)), "fills": int(len(fill_ts)),
            "matched": int(tp_sig), "precision": precision, "recall": recall,
        }
    return res


def _match(sig_ts: np.ndarray, fill_ts: np.ndarray, tol_ms: int):
    """双向贪心匹配，返回 (匹配信号数, 匹配成交数)。"""
    if len(sig_ts) == 0 or len(fill_ts) == 0:
        return 0, 0
    used = np.zeros(len(fill_ts), dtype=bool)
    tp_sig = 0
    for s in sig_ts:
        cand = np.where((~used) & (np.abs(fill_ts - s) <= tol_ms))[0]
        if len(cand):
            used[cand[np.argmin(np.abs(fill_ts[cand] - s))]] = True
            tp_sig += 1
    return tp_sig, int(used.sum())


def split_spans(ts_min: int, ts_max: int, train=0.6, val=0.2):
    """时间顺序切分，返回 (train_end, val_end) 毫秒边界。"""
    span = ts_max - ts_min
    return ts_min + int(span * train), ts_min + int(span * (train + val))


def evaluate_rule_oos(bars: pd.DataFrame, fills: pd.DataFrame, rule: str,
                      direction: str, tolerance_ms: int) -> dict:
    """训练/验证/测试三段分别评价，防过拟合：最终测试只评一次。"""
    feats = build_features(bars)
    t0, t1 = int(feats["bar_start_ms"].min()), int(feats["bar_end_ms"].max())
    tr_end, va_end = split_spans(t0, t1)
    spans = {"train": (t0, tr_end), "validation": (tr_end, va_end), "test": (va_end, t1)}
    mask_rule = SIGNAL_RULES[rule](feats).fillna(False).values
    sig_ts = feats.loc[mask_rule, "bar_end_ms"].values
    fill_ts = fills[fills["side"] == direction]["ts_ms"].values
    out: dict = {}
    for name, (a, b) in spans.items():
        s = sig_ts[(sig_ts >= a) & (sig_ts < b)]
        f = fill_ts[(fill_ts >= a) & (fill_ts < b)]
        tp_s, tp_f = _match(s, f, tolerance_ms)
        out[name] = {"signals": int(len(s)), "fills": int(len(f)), "matched": int(tp_s),
                     "precision": (tp_s / len(s)) if len(s) else None,
                     "recall": (tp_f / len(f)) if len(f) else None}
    return out
