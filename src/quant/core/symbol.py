"""T007 / 接缝1：带市场归属的标的标识（宪法 VII）。

全系统的信号、仓位、日志、Redis key 一律以 `Symbol.uid` 索引，
禁止裸字符串比较市场。A 股接入时只需新增 Market 成员，无需改动索引逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Market(str, Enum):
    OKX_SWAP = "okx_swap"        # 欧易 U 本位永续（当前主用）
    BINANCE_UMS = "binance_ums"  # 币安 U 本位永续（保留供以后扩展）
    ASHARE = "ashare"            # A 股（本期仅预留，不实现）


@dataclass(frozen=True, slots=True)
class Symbol:
    market: Market
    raw: str  # 交易所原生代码，如 "BTCUSDT" / "600519"

    @property
    def uid(self) -> str:
        return f"{self.market.value}:{self.raw}"

    def __str__(self) -> str:
        return self.uid

    @classmethod
    def parse(cls, uid: str) -> "Symbol":
        market_str, _, raw = uid.partition(":")
        if not raw:
            raise ValueError(f"非法 uid（缺少市场前缀）：{uid!r}")
        return cls(market=Market(market_str), raw=raw)
