"""T027/T028：Watchdog 决策 + 飞书双通道/去重 单测。"""
from __future__ import annotations

from decimal import Decimal

from quant.ops.feishu import FeishuAlerter
from quant.ops.watchdog import WatchAction, WatchState, assess


def _state(**o):
    base = dict(now_ms=100_000, last_heartbeat_ms=100_000, equity=Decimal("1000"),
                hard_floor=Decimal("850"), hourly_pnl_pct=0.0, reconcile_ok=True, api_errors=0)
    base.update(o); return WatchState(**base)


# --- Watchdog ---
def test_floor_breach_flats_and_halts():
    a, _ = assess(_state(equity=Decimal("840")))
    assert a is WatchAction.FLAT_AND_HALT


def test_heartbeat_stale_flats():
    a, _ = assess(_state(now_ms=200_000, last_heartbeat_ms=100_000))  # 100s > 60s
    assert a is WatchAction.FLAT_AND_HALT


def test_hourly_loss_flats():
    assert assess(_state(hourly_pnl_pct=-3.5))[0] is WatchAction.FLAT_AND_HALT


def test_reconcile_mismatch_pauses():
    assert assess(_state(reconcile_ok=False))[0] is WatchAction.PAUSE


def test_healthy_ok():
    assert assess(_state())[0] is WatchAction.OK


# --- 飞书 ---
class FakeTransport:
    def __init__(self):
        self.webhook: list = []
        self.urgent: list = []

    async def post_webhook(self, text, urgent):
        self.webhook.append((text, urgent))

    async def post_urgent(self, text):
        self.urgent.append(text)


async def test_fatal_dual_channel():
    t = FakeTransport()
    al = FeishuAlerter(t)
    await al.fatal("全平停机", "破地板", now=0)
    assert len(t.webhook) == 1 and t.webhook[0][1] is True  # 群消息 urgent 标记
    assert len(t.urgent) == 1                                 # 加急第二通道


async def test_warn_dedup_within_window():
    t = FakeTransport()
    al = FeishuAlerter(t)
    await al.warn("对账异常", now=0)
    await al.warn("对账异常", now=30_000)   # 窗口内 → 抑制
    await al.warn("对账异常", now=70_000)   # 超窗 → 再发
    assert len(t.webhook) == 2


async def test_fatal_urgent_always_sent_even_if_webhook_deduped():
    t = FakeTransport()
    al = FeishuAlerter(t)
    await al.fatal("全平停机", now=0)
    await al.fatal("全平停机", now=10_000)  # 群消息被去重，但加急仍送达
    assert len(t.webhook) == 1
    assert len(t.urgent) == 2
