"""T057：Web 控制台契约 CT-WEB-1..5。"""
from __future__ import annotations

import pytest

from quant.webui.api.control import Command, ControlWriter, parse_command
from quant.webui.api.guards import (
    FORBIDDEN_FIELDS,
    ForbiddenFieldError,
    assert_editable,
    filter_editable,
)


class FakeRedis:
    def __init__(self):
        self.added = []

    async def xadd(self, stream, payload):
        self.added.append((stream, payload))
        return "1-0"


# CT-WEB-2：禁改风控参数
def test_ct_web_2_forbidden_fields_rejected():
    for f in ["hard_floor", "leverage", "risk_usd", "max_live_symbols", "G1", "daily_usd"]:
        with pytest.raises(ForbiddenFieldError):
            assert_editable(f)


def test_ct_web_2_editable_fields_pass():
    filter_editable({"entry_threshold": 0.2, "timeframe": "5m"})  # 不抛


def test_ct_web_2_mixed_payload_rejected():
    with pytest.raises(ForbiddenFieldError):
        filter_editable({"entry_threshold": 0.2, "hard_floor": 500})


# CT-WEB-3：控制经 Redis 中转，不直接交易
async def test_ct_web_3_control_writes_redis_only():
    r = FakeRedis()
    w = ControlWriter(r)
    await w.send(Command.FLAT)
    assert r.added and r.added[0][0] == "control:cmd"
    assert r.added[0][1]["cmd"] == "flat"


# CT-WEB-1：API 模块不导入/持有交易 Key（静态保证）
def test_ct_web_1_no_trading_key_in_control_module():
    import quant.webui.api.control as ctrl
    import quant.webui.api.app as appmod
    src = (ctrl.__file__, appmod.__file__)
    for f in src:
        text = open(f, encoding="utf-8").read()
        assert "BINANCE_KEY" not in text and "new_order" not in text


# CT-WEB-5：飞书仅出站，webui 是唯一入站控制通道
def test_ct_web_5_command_roundtrip():
    assert parse_command({"cmd": b"pause"}) is Command.PAUSE


# 禁改清单覆盖关键风控参数
def test_forbidden_covers_risk_params():
    assert {"hard_floor", "leverage", "max_live_symbols"}.issubset(FORBIDDEN_FIELDS)
