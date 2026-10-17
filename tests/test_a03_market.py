"""FIX-A03（OKX-P1-01/02/09）：行情归属 fail-closed、K 线时间边界确认、来源时区。"""
import pandas as pd
import pytest

from okx_reverse.ingest import import_market_bars, import_trades


def _bars_csv(tmp_path, name, rows):
    p = tmp_path / name
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def _bar(ts, inst="BTC-USDT", **kw):
    d = {"inst_id": inst, "bar_start_ms": ts, "bar_end_ms": ts + 3600000,
         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}
    d.update(kw)
    return d


def test_market_inst_mismatch_fails_closed(tmp_path):
    """行情交易对与成交不符时必须 fail closed，不得拿别的币种 K 线冒充。"""
    p = _bars_csv(tmp_path, "eth.csv", [_bar(1000, inst="ETH-USDT"), _bar(4600000, inst="ETH-USDT")])
    bars = import_market_bars(p)
    from okx_reverse.cli import find_market_for
    # 旧实现：_find_market 会返回 ETH-USDT 的 K 线给 BTC-USDT 分析
    with pytest.raises(ValueError, match="MARKET_INST_MISMATCH"):
        find_market_for(bars, "BTC-USDT")


def test_bar_missing_time_boundary_rejected(tmp_path):
    """缺少 bar_start/bar_end 时间边界的记录必须被拒绝，不得静默推断为 0。"""
    rows = [_bar(1000),
            {"inst_id": "BTC-USDT", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]
    p = _bars_csv(tmp_path, "gap.csv", rows)
    bars, rejected = import_market_bars(p, return_rejected=True)
    assert len(bars) == 1 and len(rejected) == 1
    assert "MISSING_TIME_BOUNDARY" in rejected.iloc[0]["reason"]


def test_bar_confirmed_flag_from_source(tmp_path):
    """confirmed 必须来自源数据；缺省为 False（未确认），不得一律当已收盘。"""
    rows = [_bar(1000, confirmed="True"), _bar(4600000)]
    p = _bars_csv(tmp_path, "conf.csv", rows)
    bars = import_market_bars(p)
    assert bars["confirmed"].tolist() == [True, False]


def test_source_timezone_applied(tmp_path):
    """naive 本地时间必须按来源时区解释：上海 08:00 == UTC 00:00。"""
    p = tmp_path / "tz.csv"
    pd.DataFrame([{"time": "2025-01-01 08:00:00", "side": "buy", "price": 100.0, "quantity": 1.0}]).to_csv(p, index=False)
    fills, manifest = import_trades(p, tmp_path, timezone="Asia/Shanghai")
    expected = int(pd.Timestamp("2025-01-01T00:00:00Z").value // 10**6)
    assert int(fills["ts_ms"].iloc[0]) == expected
    assert manifest.timezone == "Asia/Shanghai"
