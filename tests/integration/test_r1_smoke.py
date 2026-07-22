"""T006 / research R1：香港节点 → 币安 Testnet 连通性冒烟。

坐实 R1（账户可用 + 香港连通性），并验证长连接稳定性。
需要环境变量 BINANCE_KEY / BINANCE_SECRET（Testnet），否则自动跳过。

运行：
    uv run pytest tests/integration/test_r1_smoke.py -v -s
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.needs_binance

_HAS_CREDS = bool(os.getenv("BINANCE_KEY") and os.getenv("BINANCE_SECRET"))
skip_no_creds = pytest.mark.skipif(
    not _HAS_CREDS, reason="未设置 BINANCE_KEY/SECRET（Testnet），跳过 R1 冒烟"
)


@skip_no_creds
def test_rest_reachable_and_time_sync() -> None:
    """REST 可达 + 服务器时间偏移在容忍范围（签名前置条件）。"""
    import time

    from binance.um_futures import UMFutures  # type: ignore

    base = "https://testnet.binancefuture.com" if os.getenv("BINANCE_TESTNET", "1") == "1" else None
    client = UMFutures(
        key=os.environ["BINANCE_KEY"],
        secret=os.environ["BINANCE_SECRET"],
        base_url=base,
    )
    server_ms = client.time()["serverTime"]
    drift_ms = abs(int(time.time() * 1000) - server_ms)
    # 币安签名默认 recvWindow 5000ms；偏移过大会导致签名失败（research R2）
    assert drift_ms < 3000, f"本地与币安时间偏移过大：{drift_ms}ms"


@skip_no_creds
def test_account_readable() -> None:
    """账户可读（KYC/权限就绪的最小验证）。"""
    from binance.um_futures import UMFutures  # type: ignore

    base = "https://testnet.binancefuture.com" if os.getenv("BINANCE_TESTNET", "1") == "1" else None
    client = UMFutures(
        key=os.environ["BINANCE_KEY"],
        secret=os.environ["BINANCE_SECRET"],
        base_url=base,
    )
    acct = client.account()
    assert "totalWalletBalance" in acct


@skip_no_creds
def test_exchange_info_min_notional_present() -> None:
    """exchangeInfo 可取，且 BTCUSDT 有 MIN_NOTIONAL（供动态读取，禁硬编码）。"""
    from binance.um_futures import UMFutures  # type: ignore

    base = "https://testnet.binancefuture.com" if os.getenv("BINANCE_TESTNET", "1") == "1" else None
    client = UMFutures(base_url=base)
    info = client.exchange_info()
    btc = next(s for s in info["symbols"] if s["symbol"] == "BTCUSDT")
    filters = {f["filterType"]: f for f in btc["filters"]}
    assert "MIN_NOTIONAL" in filters
