"""T040：trade_ledger 记录构建（宪法 V）。

fee / funding / gross 分列（否则「方向对但被费吃光」会被误判为策略无效）。
net = gross - fee + funding。记录构建为纯逻辑，DB 写入注入连接。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TradeRecord:
    trade_id: str
    symbol_uid: str
    strategy: str
    tier: str            # live | shadow
    open_ts: datetime
    close_ts: datetime | None
    side: str
    entry_px: Decimal
    exit_px: Decimal | None
    qty: Decimal
    notional_usd: Decimal
    gross_pnl: Decimal
    fee: Decimal
    funding_pnl: Decimal
    slippage_bps: Decimal
    llm_stance: float | None
    llm_conviction: float | None
    llm_veto: bool | None
    quant_score: float | None
    config_version: int

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fee + self.funding_pnl


def net_pnl(gross: Decimal, fee: Decimal, funding: Decimal) -> Decimal:
    """宪法 V：三者分离，net 由三者派生。"""
    return gross - fee + funding


INSERT_SQL = """
INSERT INTO trade_ledger
 (trade_id, symbol_uid, strategy, tier, open_ts, close_ts, side,
  entry_px, exit_px, qty, notional_usd, gross_pnl, fee, funding_pnl, net_pnl,
  slippage_bps, llm_stance, llm_conviction, llm_veto, quant_score, config_version)
VALUES
 (%(trade_id)s, %(symbol_uid)s, %(strategy)s, %(tier)s, %(open_ts)s, %(close_ts)s, %(side)s,
  %(entry_px)s, %(exit_px)s, %(qty)s, %(notional_usd)s, %(gross_pnl)s, %(fee)s,
  %(funding_pnl)s, %(net_pnl)s, %(slippage_bps)s, %(llm_stance)s, %(llm_conviction)s,
  %(llm_veto)s, %(quant_score)s, %(config_version)s)
"""


def to_row(rec: TradeRecord) -> dict:
    d = {k: getattr(rec, k) for k in rec.__slots__}  # type: ignore[attr-defined]
    d["net_pnl"] = rec.net_pnl
    return d


def write_record(conn, rec: TradeRecord) -> None:
    """注入 psycopg 连接落库；无连接的纯逻辑测试直接用 TradeRecord.net_pnl。"""
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, to_row(rec))
    conn.commit()
