"""T02：CSV/XLSX 导入、字段映射、哈希归档、幂等去重。

- 原始文件复制到 data/raw/（只读快照），记录 sha256。
- 字段映射可配置（--mapping json），内置常见 OKX 导出表头别名。
- 幂等：同一 source_id（sha256）重复导入不追加；同毫秒不同 tradeId 保留。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

from .models import NORMALIZED_FILL_COLUMNS, SourceManifest, to_decimal

# 常见 OKX 导出表头（中英）-> 规范字段
DEFAULT_FIELD_MAP = {
    "trade id": "trade_id", "tradeid": "trade_id", "交易id": "trade_id", "成交id": "trade_id",
    "order id": "order_id", "orderid": "order_id", "订单id": "order_id",
    "instrument": "inst_id", "instid": "inst_id", "交易对": "inst_id", "产品": "inst_id", "币对": "inst_id",
    "time": "ts_ms", "fill time": "ts_ms", "成交时间": "ts_ms", "时间": "ts_ms", "创建时间": "ts_ms",
    "side": "side", "方向": "side", "buy/sell": "side",
    "fill price": "fill_price", "price": "fill_price", "成交价格": "fill_price", "价格": "fill_price",
    "fill quantity": "fill_qty", "fill size": "fill_qty", "size": "fill_qty", "quantity": "fill_qty",
    "成交数量": "fill_qty", "数量": "fill_qty",
    "fee": "fee", "手续费": "fee", "费用": "fee",
    "fee currency": "fee_ccy", "手续费币种": "fee_ccy",
    "posside": "pos_side", "持仓方向": "pos_side",
    "bot id": "bot_id", "机器人id": "bot_id",
    "type": "order_type", "订单类型": "order_type",
    "status": "state", "状态": "state",
    "reduce only": "reduce_only", "只减仓": "reduce_only",
}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_header(col: str, mapping: dict) -> str | None:
    key = str(col).strip().lower()
    return mapping.get(key, key.replace(" ", "_").lower())


def _parse_ts(v) -> int | None:
    """时间 -> UTC 毫秒。支持 毫秒整数、秒数、ISO 字符串、'2024/01/02 03:04:05'。"""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
        v = float(v)
        return int(v if v > 1e11 else v * 1000)
    s = str(v).strip().replace("T", " ").replace("Z", "").split("+")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return int(pd.Timestamp.strptime(s, fmt).tz_localize("UTC").value // 10**6)
        except Exception:
            continue
    try:
        return int(pd.Timestamp(s).tz_convert("UTC").value // 10**6)
    except Exception:
        return int(pd.Timestamp(s, tz="UTC").value // 10**6) if pd.Timestamp(s).tzinfo else int(pd.Timestamp(s).tz_localize("UTC").value // 10**6)


def load_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    # CSV：尝试多种编码与分隔符
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            df = pd.read_csv(path, dtype=str, encoding=enc, sep=None, engine="python")
            if df.shape[1] >= 3:
                return df
        except Exception:
            continue
    raise ValueError(f"无法解析文件: {path}")


def import_trades(path: Path, data_dir: Path, timezone: str = "UTC",
                  mapping: dict | None = None, source_type: str = "okx_csv") -> tuple[pd.DataFrame, SourceManifest]:
    """导入成交记录 -> 规范 DataFrame + manifest。不修改原始文件。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"DATA_NOT_AVAILABLE: {path}")
    mapping = {**DEFAULT_FIELD_MAP, **(mapping or {})}
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    sha = file_sha256(path)
    source_id = sha[:16]
    snapshot = raw_dir / f"{source_id}_{path.name}"
    if not snapshot.exists():
        shutil.copy2(path, snapshot)

    df = load_table(path)
    ren = {c: _normalize_header(c, mapping) for c in df.columns}
    df = df.rename(columns=ren)
    # 同一规范列出现多次时保留第一列
    df = df.loc[:, ~df.columns.duplicated()]

    notes: list[str] = []
    for required in ("ts_ms", "side", "fill_price", "fill_qty"):
        if required not in df.columns:
            notes.append(f"MISSING_COLUMN:{required}")

    out = pd.DataFrame()
    out["trade_id"] = df["trade_id"] if "trade_id" in df.columns else ""
    out["order_id"] = df.get("order_id", "")
    out["inst_id"] = df.get("inst_id", "UNKNOWN")
    out["inst_type"] = df.get("inst_type", "UNKNOWN")
    out["ts_ms"] = df["ts_ms"].map(_parse_ts) if "ts_ms" in df.columns else None
    side = df.get("side", "").astype(str).str.strip().str.lower()
    out["side"] = side.map({"buy": "buy", "b": "buy", "买入": "buy", "sell": "sell", "s": "sell", "卖出": "sell"}).fillna(side)
    out["pos_side"] = df.get("pos_side", "").astype(str).str.strip().str.lower().fillna("")
    out["reduce_only"] = df.get("reduce_only", "").astype(str).str.strip().str.lower().isin(["true", "yes", "1", "是"])
    out["fill_price"] = pd.to_numeric(df.get("fill_price"), errors="coerce")
    out["fill_qty"] = pd.to_numeric(df.get("fill_qty"), errors="coerce")
    out["qty_unit"] = df.get("qty_unit", "base")
    out["fee"] = pd.to_numeric(df.get("fee"), errors="coerce").fillna(0.0)
    out["fee_ccy"] = df.get("fee_ccy", "")
    out["maker_taker"] = df.get("maker_taker", "")
    out["bot_id"] = df.get("bot_id", "").fillna("")
    out["origin_confidence"] = "UNKNOWN"
    out.loc[out["bot_id"].astype(str).str.len() > 0, "origin_confidence"] = "CONFIRMED_BOT"
    out["source_tag"] = df.get("source_tag", "").fillna("") if "source_tag" in df.columns else ""
    out.loc[out["source_tag"] == "", "source_tag"] = ("USER_EXPORT" if source_type in ("okx_csv", "auto") else source_type.upper())
    out["source_id"] = source_id
    out["row_hash"] = [hashlib.sha256("|".join(map(str, r)).encode()).hexdigest()[:16]
                       for r in df.itertuples(index=False)]

    # 去重：先按 row_hash 整行去重；再按 (source_id, inst_id, trade_id) 去重；
    # 无 tradeId 行保留（同毫秒不同真实成交不能盲目合并）。
    before = len(out)
    out = out.drop_duplicates(subset=["row_hash"])
    if out["trade_id"].astype(str).str.len().gt(0).any():
        has_id = out["trade_id"].astype(str).str.len() > 0
        out = pd.concat([out[~has_id].drop_duplicates(subset=["ts_ms", "inst_id", "side", "fill_price", "fill_qty"]),
                         out[has_id].drop_duplicates(subset=["source_id", "inst_id", "trade_id"])])
    out = out.sort_values("ts_ms").reset_index(drop=True)
    dedup_removed = before - len(out)

    for c in NORMALIZED_FILL_COLUMNS:
        if c not in out.columns:
            out[c] = ""
    out = out[NORMALIZED_FILL_COLUMNS]

    manifest = SourceManifest(
        source_id=source_id, source_type=source_type, file_hash=sha,
        imported_at_utc_ms=int(pd.Timestamp.now(tz="UTC").value // 10**6),
        timezone=timezone,
        range_start_ms=int(out["ts_ms"].min()) if out["ts_ms"].notna().any() else None,
        range_end_ms=int(out["ts_ms"].max()) if out["ts_ms"].notna().any() else None,
        row_count=len(out),
        completeness_notes=notes + ([f"DEDUP_REMOVED:{dedup_removed}"] if dedup_removed else []),
        raw_path=str(snapshot),
    )
    return out, manifest


def import_market_bars(path: Path) -> pd.DataFrame:
    """导入离线行情 CSV/XLSX：inst_id,bar_start_ms,open,high,low,close,volume[,interval,bar_end_ms,confirmed]"""
    path = Path(path)
    df = load_table(path)
    ren = {c: _normalize_header(c, DEFAULT_FIELD_MAP) for c in df.columns}
    ren = {c: {"symbol": "inst_id", "date": "bar_start_ms", "timestamp": "bar_start_ms", "open time": "bar_start_ms"}.get(c, c) for c in ren}
    df = df.rename(columns=ren)
    df = df.loc[:, ~df.columns.duplicated()]
    out = pd.DataFrame()
    out["inst_id"] = df.get("inst_id", "UNKNOWN")
    out["bar_start_ms"] = df["bar_start_ms"].map(_parse_ts)
    interval_ms = None
    if len(out) > 1:
        diffs = out["bar_start_ms"].diff().dropna()
        interval_ms = int(diffs.mode().iloc[0])
    out["bar_end_ms"] = df.get("bar_end_ms").map(_parse_ts) if "bar_end_ms" in df.columns else None
    if out["bar_end_ms"].isna().all():
        out["bar_end_ms"] = out["bar_start_ms"] + (interval_ms or 0)
    out["interval"] = df.get("interval", f"{(interval_ms or 0)//60000}m")
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(df.get(c), errors="coerce")
    out["confirmed"] = True
    return out.dropna(subset=["bar_start_ms", "close"]).sort_values("bar_start_ms").reset_index(drop=True)
