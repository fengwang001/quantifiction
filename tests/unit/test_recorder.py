"""T041：recorder Parquet 落盘 + OSS 上传（bucket 注入）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from quant.research.recorder import Dataset, PartitionPath, Recorder


def test_write_batch_parquet(tmp_path: Path):
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    rec = Recorder(tmp_path)
    part = PartitionPath(Dataset.FORCE_ORDERS, "binance_ums:ETHUSDT", "2026-07-21")
    rows = [
        {"ts": 1, "side": "SELL", "price": 3000.0, "qty": 1.5},
        {"ts": 2, "side": "BUY", "price": 3001.0, "qty": 0.2},
    ]
    path = rec.write_batch(part, rows)
    assert path.exists()
    table = pq.read_table(path)
    assert table.num_rows == 2
    assert set(table.column_names) == set(("ts", "side", "price", "qty"))


def test_write_batch_rejects_wrong_columns(tmp_path: Path):
    pytest.importorskip("pyarrow")
    rec = Recorder(tmp_path)
    part = PartitionPath(Dataset.AGG_TRADES, "u", "2026-07-21")
    with pytest.raises(ValueError):
        rec.write_batch(part, [{"ts": 1, "wrong": 2}])


def test_upload_uses_injected_bucket(tmp_path: Path):
    pytest.importorskip("pyarrow")
    rec = Recorder(tmp_path, oss_prefix="tick/")
    part = PartitionPath(Dataset.AGG_TRADES, "binance_ums:ETHUSDT", "2026-07-21")
    rec.write_batch(part, [{"ts": 1, "price": 3000.0, "qty": 1.0, "is_buyer_maker": True}])

    class FakeBucket:
        def __init__(self): self.calls = []
        def put_object_from_file(self, key, local): self.calls.append((key, local))

    b = FakeBucket()
    key = rec.upload(part, b)
    assert key.startswith("tick/agg_trades/")
    assert b.calls
