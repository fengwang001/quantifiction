"""T033：配置加载 + 启动硬校验（FR-006，C3/C4）。

- universe.yaml：三层币种池 + constraints，校验 U1-U5
- strategies/*.yaml：引用信号/sizing
- cognitive.yaml：预算 ≤ 硬上限、max_per_day 存在（C4）
改配置需重启生效（C3）——不做运行期热加载。
校验失败即抛 ConfigError，拒绝启动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import yaml

# 认知层预算硬上限（USD，宪法政策不变量）。market 价格/汇率在 cognitive.yaml，不写死。
COGNITIVE_DAILY_CAP_USD = Decimal("1.20")
COGNITIVE_MONTHLY_CAP_USD = Decimal("25")


class ConfigError(ValueError):
    """启动配置校验失败。"""


@dataclass(frozen=True, slots=True)
class SymbolConfig:
    raw: str
    tier: str  # live | shadow | observe
    strategies: tuple[str, ...]
    capital_weight: float
    max_notional_usd: Decimal
    leverage: int = 1


@dataclass(frozen=True, slots=True)
class Universe:
    symbols: tuple[SymbolConfig, ...]
    max_live_symbols: int
    max_concurrent_positions: int

    @property
    def live(self) -> list[SymbolConfig]:
        return [s for s in self.symbols if s.tier == "live"]


def _parse_universe(data: dict[str, Any]) -> Universe:
    syms = []
    for raw, cfg in data.get("universe", {}).items():
        syms.append(SymbolConfig(
            raw=raw,
            tier=cfg["tier"],
            strategies=tuple(cfg.get("strategies", [])),
            capital_weight=float(cfg.get("capital_weight", 0.0)),
            max_notional_usd=Decimal(str(cfg.get("max_notional_usd", 0))),
            leverage=int(cfg.get("leverage", 1)),
        ))
    c = data.get("constraints", {})
    return Universe(
        symbols=tuple(syms),
        max_live_symbols=int(c.get("max_live_symbols", 2)),
        max_concurrent_positions=int(c.get("max_concurrent_positions", 2)),
    )


def validate_universe(
    u: Universe,
    known_strategies: set[str],
    min_notional: dict[str, Decimal],
) -> None:
    """U1-U5 硬校验（spec §8.5.1）。"""
    live = u.live
    # U1：live 数量 ≤ 上限
    if len(live) > u.max_live_symbols:
        raise ConfigError(f"U1：live 数量 {len(live)} > max_live_symbols {u.max_live_symbols}")
    # U2：live 权重和 == 1.0
    if live:
        total_w = round(sum(s.capital_weight for s in live), 6)
        if total_w != 1.0:
            raise ConfigError(f"U2：live capital_weight 之和 = {total_w}，须为 1.0")
    # U3：每个 max_notional ≥ min_notional×1.1
    for s in live:
        mn = min_notional.get(s.raw)
        if mn is not None and s.max_notional_usd < mn * Decimal("1.1"):
            raise ConfigError(
                f"U3：{s.raw} max_notional {s.max_notional_usd} < {mn}×1.1"
                f"（$100 阶段请改用 ETH/SOL）"
            )
    # U4：引用策略存在且 enabled
    for s in u.symbols:
        for st in s.strategies:
            if st not in known_strategies:
                raise ConfigError(f"U4：{s.raw} 引用未知策略 {st}")
    # U5：所有 tier 合法
    for s in u.symbols:
        if s.tier not in ("live", "shadow", "observe"):
            raise ConfigError(f"U5：{s.raw} 非法 tier {s.tier}")


def validate_cognitive(data: dict[str, Any]) -> None:
    """C4：预算 ≤ 硬上限（¥），max_per_day 存在。"""
    cog = data.get("cognitive", {})
    # 预算在 provider.budget_usd（USD，与宪法上限同单位）
    budget = cog.get("provider", {}).get("budget_usd") or cog.get("budget", {})
    daily = Decimal(str(budget.get("daily", "0")))
    monthly = Decimal(str(budget.get("monthly", "0")))
    if daily > COGNITIVE_DAILY_CAP_USD:
        raise ConfigError(f"cognitive 日预算 ${daily} > 硬上限 ${COGNITIVE_DAILY_CAP_USD}")
    if monthly > COGNITIVE_MONTHLY_CAP_USD:
        raise ConfigError(f"cognitive 月预算 ${monthly} > 硬上限 ${COGNITIVE_MONTHLY_CAP_USD}")
    delib = cog.get("deliberation", {})
    if "max_per_day" not in delib:
        raise ConfigError("cognitive.deliberation.max_per_day 缺失（防失控烧钱）")


def load_universe(text: str) -> Universe:
    return _parse_universe(yaml.safe_load(text))
