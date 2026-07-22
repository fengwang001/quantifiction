"""策略快照/版本/provenance 单测（P2 留痕）。"""
from __future__ import annotations

import pytest

import quant.research.strategy_registry as reg
from quant.research.shadow_engine import Strategy


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "REGISTRY", tmp_path / "registry.jsonl")


def _s(tp=0.0025):
    return Strategy("测试策略", "obi", "mom", 0.35, tp, 180)


def test_version_stable_and_content_addressed():
    v1 = reg.version_id(reg.strategy_def(_s()))
    v2 = reg.version_id(reg.strategy_def(_s()))
    assert v1 == v2                       # 定义未变 → 版本稳定
    v3 = reg.version_id(reg.strategy_def(_s(tp=0.006)))
    assert v3 != v1                       # 参数变 → 版本必变


def test_snapshot_idempotent_and_immutable_flag():
    s = _s()
    vid1 = reg.snapshot(s, author="human")
    vid2 = reg.snapshot(s, author="human")   # 幂等
    assert vid1 == vid2
    recs = reg.history("测试策略")
    assert len(recs) == 1
    assert recs[0]["immutable"] is True      # 人工策略不可被 agent 改


def test_provenance_agent_cannot_edit_human():
    vid = reg.snapshot(_s(), author="human")
    with pytest.raises(reg.ProvenanceError):
        reg.assert_editable_by(vid, actor="agent")
    reg.assert_editable_by(vid, actor="human")   # 人工可动


def test_provenance_agent_can_edit_own():
    s = Strategy("agent造的", "cvd", "rev", 0.5, 0.004, 200)
    vid = reg.snapshot(s, author="agent")
    reg.assert_editable_by(vid, actor="agent")   # 不抛


def test_trade_carries_version_id():
    s = _s()
    s.version_id = reg.snapshot(s, author="human")
    s.pos = 1; s.entry_px = 3000.0; s.open_ts = 0.0
    s._close(3010.0, 0.0033, 60, "tp", 100.0)
    assert s.trades[0]["strategy_version_id"] == s.version_id
