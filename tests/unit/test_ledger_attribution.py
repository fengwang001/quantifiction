"""T039：账本 net 拆解 + (币×策略×日) 聚合 + 日报卡片。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from quant.research.attribution import (
    by_symbol_strategy_day,
    daily_card,
)
from quant.research.ledger import TradeRecord, net_pnl


def _rec(uid, strat, tier, gross, fee, funding, day="2026-07-21"):
    return TradeRecord(
        trade_id=f"{uid}-{gross}", symbol_uid=uid, strategy=strat, tier=tier,
        open_ts=datetime.fromisoformat(f"{day}T10:00:00"), close_ts=None,
        side="BUY", entry_px=Decimal("3000"), exit_px=None, qty=Decimal("0.1"),
        notional_usd=Decimal("300"), gross_pnl=Decimal(gross), fee=Decimal(fee),
        funding_pnl=Decimal(funding), slippage_bps=Decimal("2"),
        llm_stance=None, llm_conviction=None, llm_veto=None, quant_score=None,
        config_version=1,
    )


def test_net_decomposition():
    # 方向对(毛正)但被费吃光 → net 负（宪法 V 拆列的意义）
    assert net_pnl(Decimal("6.10"), Decimal("6.60"), Decimal("0")) == Decimal("-0.50")


def test_record_net_property():
    r = _rec("binance_ums:ETHUSDT", "liq_reversal", "live", "6.10", "2.00", "0.10")
    assert r.net_pnl == Decimal("4.20")


def test_aggregate_by_symbol_strategy_day():
    recs = [
        _rec("binance_ums:ETHUSDT", "liq_reversal", "live", "5", "1", "0"),
        _rec("binance_ums:ETHUSDT", "liq_reversal", "live", "3", "1", "0"),
        _rec("binance_ums:BTCUSDT", "liq_reversal", "shadow", "8", "2", "0"),
    ]
    agg = by_symbol_strategy_day(recs)
    eth = agg[("binance_ums:ETHUSDT", "liq_reversal", "2026-07-21")]
    assert eth.trades == 2
    assert eth.net == Decimal("6")  # (5+3) - (1+1) + 0


def test_daily_card_live_shadow_side_by_side():
    recs = [
        _rec("binance_ums:ETHUSDT", "liq_reversal", "live", "5", "1", "0"),
        _rec("binance_ums:SOLUSDT", "liq_reversal", "shadow", "8", "1", "0"),
    ]
    card = daily_card(recs, "2026-07-21", Decimal("1003.20"))
    text = "\n".join(card["rows"])
    assert "[LIVE]" in text and "[SHADOW]" in text
    assert "ETHUSDT" in text and "SOLUSDT" in text
