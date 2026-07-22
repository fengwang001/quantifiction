"""欧易连通冒烟。需 OKX_API_KEY/SECRET/PASSPHRASE，否则跳过。

运行：uv run pytest tests/integration/test_okx_smoke.py -v -s
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.needs_okx

_READY = all(os.getenv(k) for k in ("OKX_API_KEY", "OKX_SECRET", "OKX_PASSPHRASE"))
skip_no_creds = pytest.mark.skipif(not _READY, reason="未设置 OKX 三要素凭据，跳过冒烟")


def _client():
    from quant.markets.okx_swap.okx_client import OKXClient, REST_BASE

    return OKXClient(
        os.environ["OKX_API_KEY"], os.environ["OKX_SECRET"], os.environ["OKX_PASSPHRASE"],
        base_url=os.getenv("OKX_BASE_URL", REST_BASE),   # .com 被限时用 .cab
        simulated=os.getenv("OKX_SIMULATED", "1") == "1",
    )


@skip_no_creds
def test_public_instruments_reachable():
    """公共接口可达 + 能取到 SWAP 合约面值（无需签名）。"""
    data = _client().instruments("SWAP")
    eth = next(i for i in data if i["instId"] == "ETH-USDT-SWAP")
    assert "ctVal" in eth


@skip_no_creds
def test_account_positions_signed():
    """签名私有接口可达（鉴权三要素正确）。需 IP 在白名单内。"""
    _client().positions("SWAP")  # 不抛即鉴权 + IP 通过
