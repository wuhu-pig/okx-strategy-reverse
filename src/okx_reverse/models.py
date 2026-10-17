"""规范化数据模型（schema 层）。

金额/数量语义上为 Decimal；为便于向量化分析，DataFrame 内部用 float 承载，
但账本级求和（PnL、费用）使用 Decimal（见 pnl.py），避免 float 累加误差。
所有字段带来源标注 SourceTag。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# 来源标注（MASTER PLAN 第 0 节第 4 条）
SOURCE_TAGS = [
    "EXCHANGE_BOT", "EXCHANGE_ORDER", "EXCHANGE_FILL", "EXCHANGE_BILL",
    "USER_EXPORT", "MARKET_DATA", "INFERRED", "SYNTHETIC_DEMO",
]

# 机器人归属分级
ATTRIBUTION_LEVELS = ["CONFIRMED_BOT", "PROBABLE_BOT", "AMBIGUOUS", "NOT_BOT", "UNKNOWN"]

NORMALIZED_FILL_COLUMNS = [
    "trade_id", "order_id", "inst_id", "inst_type", "ts_ms", "side",
    "pos_side", "reduce_only", "fill_price", "fill_qty", "qty_unit",
    "fee", "fee_ccy", "maker_taker", "bot_id", "origin_confidence",
    "source_tag", "source_id", "row_hash",
]

NORMALIZED_BAR_COLUMNS = [
    "inst_id", "bar_start_ms", "bar_end_ms", "interval", "open", "high",
    "low", "close", "volume", "confirmed",
]


@dataclass
class SourceManifest:
    source_id: str
    source_type: str          # okx_csv / okx_xlsx / market_csv / synthetic
    file_hash: str            # sha256
    imported_at_utc_ms: int
    timezone: str
    range_start_ms: int | None
    range_end_ms: int | None
    row_count: int
    schema_version: str = "1.0"
    completeness_notes: list[str] = field(default_factory=list)
    raw_path: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def to_decimal(x) -> Decimal:
    """金额/数量的唯一入口：字符串化后转 Decimal，禁止 float 直接参与账本累加。"""
    if x is None or x == "":
        return Decimal(0)
    return Decimal(str(x))
