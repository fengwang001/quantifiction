"""T042/T043：归因报表（宪法 V/VI）。

PnL 可拆解到 (币×策略×日)；live 与 shadow 并排，驱动数据化升降级。
纯聚合函数，输入 TradeRecord 列表。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from quant.research.ledger import TradeRecord


@dataclass(frozen=True, slots=True)
class Cell:
    trades: int
    gross: Decimal
    fee: Decimal
    funding: Decimal
    net: Decimal


def _empty() -> dict[str, Decimal | int]:
    return {"trades": 0, "gross": Decimal(0), "fee": Decimal(0), "funding": Decimal(0)}


def aggregate(records: list[TradeRecord], *keys: str) -> dict[tuple, Cell]:
    """按给定维度聚合。keys 取自 symbol_uid/strategy/day/tier。"""
    buckets: dict[tuple, dict] = defaultdict(_empty)
    for r in records:
        key = tuple(_key_val(r, k) for k in keys)
        b = buckets[key]
        b["trades"] += 1
        b["gross"] += r.gross_pnl
        b["fee"] += r.fee
        b["funding"] += r.funding_pnl
    return {
        k: Cell(v["trades"], v["gross"], v["fee"], v["funding"],
                v["gross"] - v["fee"] + v["funding"])
        for k, v in buckets.items()
    }


def _key_val(r: TradeRecord, k: str):
    if k == "day":
        return r.open_ts.date().isoformat()
    return getattr(r, k)


def by_symbol_strategy_day(records: list[TradeRecord]) -> dict[tuple, Cell]:
    return aggregate(records, "symbol_uid", "strategy", "day")


def daily_card(records: list[TradeRecord], date: str, equity: Decimal) -> dict:
    """构建飞书日报卡片数据：live 与 shadow 各币并排。"""
    per_tier_symbol = aggregate(records, "tier", "symbol_uid")
    rows: list[str] = []
    for tier in ("live", "shadow"):
        section = {k[1]: v for k, v in per_tier_symbol.items() if k[0] == tier}
        if not section:
            continue
        rows.append(f"[{tier.upper()}]")
        for uid, c in sorted(section.items()):
            rows.append(
                f"  {uid.split(':')[-1]}  {c.trades}笔  净{c.net:+}"
                f"  (毛{c.gross:+} 费{-c.fee})"
            )
    return {"date": date, "equity": f"${equity}", "rows": rows}
