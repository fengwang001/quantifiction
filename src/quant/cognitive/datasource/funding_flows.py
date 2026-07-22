"""第 8 类判断依据：资金面（DefiLlama，免费无 key）。

- ETH DeFi TVL：链上锁仓资金及 1d/7d 变化（资金进出链的慢信号）
- 稳定币总市值：场内"弹药"及 1d/7d 变化（增发=潜在买力，缩量=离场）
日级慢变量 → 缓存 1 小时。失败静默降级返回 None（不阻塞辩论）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CACHE = Path("data/funding_flows_cache.json")
TTL_SEC = 3600
TVL_URL = "https://api.llama.fi/v2/historicalChainTvl/Ethereum"
STABLE_URL = "https://stablecoins.llama.fi/stablecoincharts/all"


def _chg(series: list[float], days: int) -> float | None:
    if len(series) <= days or series[-1 - days] == 0:
        return None
    return round((series[-1] - series[-1 - days]) / series[-1 - days] * 100, 2)


def get_funding_flows() -> dict | None:
    if CACHE.exists():
        try:
            c = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - c.get("ts", 0) < TTL_SEC:
                return c
        except Exception:  # noqa: BLE001
            pass
    import httpx
    out: dict = {"ts": time.time()}
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as cl:
            tvl_rows = cl.get(TVL_URL).json()
            tvl = [float(r["tvl"]) for r in tvl_rows[-10:]]
            out["eth_tvl_b"] = round(tvl[-1] / 1e9, 2)
            out["tvl_chg_1d"] = _chg(tvl, 1)
            out["tvl_chg_7d"] = _chg(tvl, 7)

            st_rows = cl.get(STABLE_URL).json()
            st = [float(r["totalCirculating"]["peggedUSD"]) for r in st_rows[-10:]]
            out["stable_b"] = round(st[-1] / 1e9, 1)
            out["stable_chg_1d"] = _chg(st, 1)
            out["stable_chg_7d"] = _chg(st, 7)
    except Exception:  # noqa: BLE001
        return None
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(out), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return out
