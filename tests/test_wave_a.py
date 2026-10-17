"""Wave A 回归测试：A04–A06（OKX-P0-04）、A07–A09（OKX-P0-05）、行情/时区（P1-01/02/09）。

这些测试首先在旧实现上运行以复现缺陷（预期 FAIL），修复后必须全部通过。
"""
import json

import pandas as pd
import pytest

from okx_reverse.ingest import import_trades, merge_fills
from okx_reverse.episodes import rebuild_episodes


def _write_csv(tmp_path, name, rows):
    p = tmp_path / name
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


# ---------------------------------------------------------------- A04: 最小 CSV 可导入
def test_a04_minimal_csv_without_optional_columns(tmp_path):
    """仅 time/side/price/qty 四列的最小导出必须可导入，不因可选列缺失崩溃。"""
    p = _write_csv(tmp_path, "min.csv", [
        {"time": "2025-01-01 00:00:00", "side": "buy", "price": 100.0, "quantity": 1.0},
        {"time": "2025-01-01 01:00:00", "side": "sell", "price": 101.0, "quantity": 1.0},
    ])
    fills, manifest = import_trades(p, tmp_path)  # 旧实现此处抛 AttributeError
    assert len(fills) == 2
    assert fills["fill_price"].tolist() == [100.0, 101.0]


def test_a04_missing_required_column_fails_fast(tmp_path):
    """缺少必填列（无 price）必须显式报错，而不是静默产出坏数据。"""
    p = _write_csv(tmp_path, "bad.csv", [
        {"time": "2025-01-01 00:00:00", "side": "buy", "quantity": 1.0},
    ])
    with pytest.raises(ValueError, match="REQUIRED"):
        import_trades(p, tmp_path)


# ---------------------------------------------------------------- A05: 跨文件合并与幂等
def test_a05_two_month_files_merge_keeps_all_rows(tmp_path):
    """两个月份文件合并后记录均保留，最新文件不覆盖旧文件。"""
    p1 = _write_csv(tmp_path, "jan.csv", [
        {"time": "2025-01-15 00:00:00", "side": "buy", "price": 100.0, "quantity": 1.0, "trade id": "T1"},
    ])
    p2 = _write_csv(tmp_path, "feb.csv", [
        {"time": "2025-02-15 00:00:00", "side": "sell", "price": 110.0, "quantity": 1.0, "trade id": "T2"},
    ])
    f1, _ = import_trades(p1, tmp_path)
    f2, _ = import_trades(p2, tmp_path)
    merged = merge_fills([f1, f2])  # 旧实现无此函数/被 latest.json 覆盖
    assert len(merged) == 2
    assert set(merged["trade_id"]) == {"T1", "T2"}


def test_a05_same_trade_id_across_exports_deduped(tmp_path):
    """相同交易所 trade_id 跨导出不重复；同毫秒不同 trade_id 保留。"""
    jan = [{"time": "2025-01-15 00:00:00", "side": "buy", "price": 100.0, "quantity": 1.0, "trade id": "T1"},
           {"time": "2025-01-15 00:00:00", "side": "buy", "price": 100.0, "quantity": 0.5, "trade id": "T2"}]
    feb = [{"time": "2025-01-15 00:00:00", "side": "buy", "price": 100.0, "quantity": 1.0, "trade id": "T1"}]
    f1, _ = import_trades(_write_csv(tmp_path, "a.csv", jan), tmp_path)
    f2, _ = import_trades(_write_csv(tmp_path, "b.csv", feb), tmp_path)
    merged = merge_fills([f1, f2])
    assert len(merged) == 2  # T1 去重，T2 保留


# ---------------------------------------------------------------- A06: 多 bot / inst 隔离
def test_a06_mixed_bots_isolated_groups():
    from okx_reverse.ingest import analysis_groups
    fills = pd.DataFrame([
        {"inst_id": "BTC-USDT", "bot_id": "botA", "origin_confidence": "CONFIRMED_BOT", "side": "buy"},
        {"inst_id": "BTC-USDT", "bot_id": "botB", "origin_confidence": "CONFIRMED_BOT", "side": "buy"},
        {"inst_id": "BTC-USDT", "bot_id": "", "origin_confidence": "UNKNOWN", "side": "buy"},
        {"inst_id": "ETH-USDT", "bot_id": "botA", "origin_confidence": "CONFIRMED_BOT", "side": "buy"},
    ])
    groups = analysis_groups(fills)  # 旧实现无此函数，全部混在一起推断
    keys = set(groups.keys())
    assert ("BTC-USDT", "botA") in keys and ("BTC-USDT", "botB") in keys
    assert ("ETH-USDT", "botA") in keys
    # UNKNOWN 不得与 CONFIRMED 合并
    assert all(k[1] != "UNKNOWN" or k == ("BTC-USDT", "UNKNOWN") for k in keys)
    assert len(groups[("BTC-USDT", "UNKNOWN")]) == 1
