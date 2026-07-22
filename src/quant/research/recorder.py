"""T011：tick 全量落盘骨架（data-model D 节，冷层）。

自录订单簿增量/逐笔/爆仓流为 Parquet，按天分区 → 阿里云 OSS。
这是本项目最具长期价值、不可复得的资产（宪法 V / research R11）。

本文件为 Foundational 骨架：定义数据集 schema 与写入接口；
实际 WS 接入在 US1（T041）完成。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Dataset(str, Enum):
    ORDERBOOK_DELTA = "orderbook_delta"
    AGG_TRADES = "agg_trades"
    FORCE_ORDERS = "force_orders"       # 爆仓流
    FUNDING_MARK = "funding_mark"


# 各数据集列定义（写入时校验，回放时依赖）
SCHEMAS: dict[Dataset, tuple[str, ...]] = {
    Dataset.ORDERBOOK_DELTA: ("ts", "side", "price", "qty", "first_update_id", "final_update_id", "pu"),
    Dataset.AGG_TRADES: ("ts", "price", "qty", "is_buyer_maker"),
    Dataset.FORCE_ORDERS: ("ts", "side", "price", "qty"),
    Dataset.FUNDING_MARK: ("ts", "mark_price", "funding_rate"),
}


@dataclass(frozen=True, slots=True)
class PartitionPath:
    dataset: Dataset
    symbol_uid: str
    date: str  # YYYY-MM-DD

    def relative(self) -> str:
        # uid 的 ':' 转为路径分隔（Windows 文件名不允许 ':'），如 binance_ums/ETHUSDT
        safe = self.symbol_uid.replace(":", "/")
        return f"{self.dataset.value}/{safe}/{self.date}.parquet"


class Recorder:
    """写入接口骨架。落地实现（pyarrow + oss2）在 T041。"""

    def __init__(self, local_root: Path, oss_prefix: str | None = None) -> None:
        self._root = local_root
        self._oss_prefix = oss_prefix

    def validate_columns(self, dataset: Dataset, columns: tuple[str, ...]) -> None:
        expected = SCHEMAS[dataset]
        if tuple(columns) != expected:
            raise ValueError(f"{dataset.value} 列不符：期望 {expected}，得到 {columns}")

    def write_batch(self, part: PartitionPath, rows: list[dict]) -> Path:
        """T041：批量落盘为 Parquet（本地），返回文件路径。OSS 上传见 upload()。"""
        import pyarrow as pa
        import pyarrow.parquet as pq

        cols = SCHEMAS[part.dataset]
        self.validate_columns(part.dataset, tuple(rows[0].keys()) if rows else cols)
        table = pa.table({c: [r[c] for r in rows] for c in cols})
        path = self._root / part.relative()
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
        return path

    def upload(self, part: PartitionPath, bucket) -> str:
        """将本地 Parquet 上传 OSS（bucket 注入，便于测试）。返回对象 key。"""
        local = self._root / part.relative()
        key = f"{self._oss_prefix or ''}{part.relative()}"
        bucket.put_object_from_file(key, str(local))
        return key
