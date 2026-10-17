"""T05：技术指标特征 —— 严格无未来函数。

所有指标只用「当前及以前已结束的 K 线」。shift 语义：
bar i 的特征在 bar_end_ms 之前不可用，匹配成交时要求 bar_end_ms <= 决策时刻。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def bollinger(close: pd.Series, window: int = 20, ndev: float = 2.0):
    mid = sma(close, window)
    sd = close.rolling(window, min_periods=window).std(ddof=0)
    return mid - ndev * sd, mid, mid + ndev * sd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def rolling_max_min(df: pd.DataFrame, window: int):
    """突破参考：前一 window 期的高低点（不含当期，避免自我比较）。"""
    return (df["high"].shift(1).rolling(window, min_periods=window).max(),
            df["low"].shift(1).rolling(window, min_periods=window).min())


def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """在 K 线上追加指标列。返回带 bar_end_ms 的副本。"""
    f = bars.copy()
    c = f["close"]
    f["ret_1"] = c.pct_change()
    f["rsi_14"] = rsi(c, 14)
    f["ema_20"] = ema(c, 20)
    f["ema_50"] = ema(c, 50)
    f["sma_20"] = sma(c, 20)
    bb_l, _, bb_u = bollinger(c, 20, 2.0)
    f["bb_low"] = bb_l
    f["bb_high"] = bb_u
    f["atr_14"] = atr(f, 14)
    f["hh_20"], f["ll_20"] = rolling_max_min(f, 20)
    f["golden_cross"] = (ema(c, 20) > ema(c, 50)) & (ema(c, 20).shift(1) <= ema(c, 50).shift(1))
    f["death_cross"] = (ema(c, 20) < ema(c, 50)) & (ema(c, 20).shift(1) >= ema(c, 50).shift(1))
    f["utc_hour"] = pd.to_datetime(f["bar_start_ms"], unit="ms").dt.hour
    return f


def features_asof(features: pd.DataFrame, ts_ms: int) -> pd.Series | None:
    """决策时刻可用的最后一根【已结束】K 线特征。严格 bar_end_ms <= ts_ms。"""
    ok = features[features["bar_end_ms"] <= ts_ms]
    if ok.empty:
        return None
    return ok.iloc[-1]
