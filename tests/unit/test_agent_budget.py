"""C2 修复验证：agent 日预算持久化 + 配置化定价（无网络）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

import quant.cognitive.agent_runner as ar
from quant.cognitive.budget import DAILY_CAP


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "BUDGET_FILE", tmp_path / "budget.json")


def test_budget_accumulates_and_caps():
    assert ar._budget_spent_today() == Decimal("0")
    ar._budget_charge(Decimal("0.5"))
    ar._budget_charge(Decimal("0.8"))
    assert ar._budget_spent_today() == Decimal("1.3")
    assert ar._budget_spent_today() >= DAILY_CAP   # 超 $1.20 → 主循环会跳过辩论


def test_pricing_loaded_from_config_not_hardcoded():
    pricing, rate = ar._load_provider_cfg()
    # 与 config/cognitive.yaml 一致（gemini-3.1-pro: in1.5/out7, 汇率7.2）
    assert pricing.input_per_m == Decimal("1.5")
    assert pricing.output_per_m == Decimal("7")
    assert rate == Decimal("7.2")
