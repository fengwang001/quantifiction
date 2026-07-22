"""T053：加密数据源（§6 analysts 输入）。

统一 fetch() 接口，返回结构化 dict 供 analyst 节点消费。
外部 API 调用注入 http client；此处定义契约与骨架。
"""
from __future__ import annotations

from typing import Any, Protocol


class DataSource(Protocol):
    name: str

    async def fetch(self, symbol_uid: str) -> dict[str, Any]: ...


class NewsSource:
    name = "news"

    def __init__(self, http: Any | None = None) -> None:
        self._http = http

    async def fetch(self, symbol_uid: str) -> dict[str, Any]:
        # 落地：CoinDesk / TheBlock RSS 摘要（Haiku）。骨架返回空。
        return {"source": self.name, "items": []}


class SentimentSource:
    name = "sentiment"

    def __init__(self, http: Any | None = None) -> None:
        self._http = http

    async def fetch(self, symbol_uid: str) -> dict[str, Any]:
        # 恐惧贪婪指数 + X 情绪
        return {"source": self.name, "fear_greed": None}


class OnchainSource:
    name = "onchain"

    async def fetch(self, symbol_uid: str) -> dict[str, Any]:
        # Glassnode 免费档 / CryptoQuant
        return {"source": self.name, "metrics": {}}


class DerivativesSource:
    """币安持仓比 / 资金费率 / 爆仓统计（永续独有信号）。"""

    name = "derivatives"

    async def fetch(self, symbol_uid: str) -> dict[str, Any]:
        return {"source": self.name, "funding_rate": None, "long_short_ratio": None}


class MacroSource:
    name = "macro"

    async def fetch(self, symbol_uid: str) -> dict[str, Any]:
        # FOMC 日历 / DXY / 美股相关性
        return {"source": self.name, "fomc_within_h": None}


ALL_SOURCES = [NewsSource, SentimentSource, OnchainSource, DerivativesSource, MacroSource]
