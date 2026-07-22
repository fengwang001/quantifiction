"""T051/T055：LangGraph 短路 + 调度决策。"""
from __future__ import annotations

import pytest

from quant.cognitive.scheduler import ScheduleState, TriggerKind, decide_trigger


# --- 图短路（需 langgraph）---
def test_graph_short_circuits_when_no_change():
    pytest.importorskip("langgraph")
    from quant.cognitive.graph import build_graph

    calls = []

    def mk(name, patch=None):
        def node(state):
            calls.append(name)
            return {**state, **(patch or {})}
        return node

    nodes = {
        "sentinel": mk("sentinel", {"changed": False, "severity": 0}),
        "analysts": mk("analysts"),
        "researchers": mk("researchers"),
        "trader": mk("trader", {"trader_verdict": {"stance": 0.5}}),
        "risk": mk("risk"),
    }
    app = build_graph(nodes)
    app.invoke({"symbol_uid": "binance_ums:BTCUSDT"})
    assert calls == ["sentinel"]  # 无变化 → 只跑哨兵，省钱


def test_graph_full_deliberation_when_changed():
    pytest.importorskip("langgraph")
    from quant.cognitive.graph import build_graph

    calls = []

    def mk(name, patch=None):
        def node(state):
            calls.append(name)
            return {**state, **(patch or {})}
        return node

    nodes = {
        "sentinel": mk("sentinel", {"changed": True, "severity": 3}),
        "analysts": mk("analysts"),
        "researchers": mk("researchers", {"bull": "b", "bear": "r"}),
        "trader": mk("trader", {"trader_verdict": {"stance": 0.5, "veto": False}}),
        "risk": mk("risk"),
    }
    app = build_graph(nodes)
    out = app.invoke({"symbol_uid": "u"})
    assert calls == ["sentinel", "analysts", "researchers", "trader", "risk"]
    assert out["trader_verdict"]["stance"] == 0.5


# --- 调度 ---
def _s(**o):
    base = dict(minute_of_day_utc=100, last_delib_min=0, delib_count_today=0,
                event_count_today=0, price_move_1h_pct=0.0, liq_spike_usd=0.0,
                fomc_within_h=None)
    base.update(o); return ScheduleState(**base)


def test_event_forces_when_price_moves():
    assert decide_trigger(_s(minute_of_day_utc=100, last_delib_min=0,
                             price_move_1h_pct=6.0)) is TriggerKind.EVENT


def test_scheduled_deliberation_at_utc_times():
    assert decide_trigger(_s(minute_of_day_utc=480, last_delib_min=0)) is TriggerKind.DELIBERATION


def test_sentinel_every_15min():
    assert decide_trigger(_s(minute_of_day_utc=105)) is TriggerKind.SENTINEL


def test_min_interval_blocks_deliberation():
    # 距上次辩论 <45min → 退回哨兵
    assert decide_trigger(_s(minute_of_day_utc=480, last_delib_min=460)) is TriggerKind.SENTINEL


def test_none_when_nothing_due():
    assert decide_trigger(_s(minute_of_day_utc=103)) is TriggerKind.NONE
