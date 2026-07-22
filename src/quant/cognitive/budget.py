"""T050：认知层预算守卫（FR-012，CT-LLM-4）。

日 $1.20 / 月 $25 硬上限；超预算 → 降级纯量化（返回不可调用），非报错。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# 宪法政策上限（USD，不变量）。市场价格/汇率在 cognitive.yaml，不写进代码。
# 成本按 config 汇率折算为 USD 后与此比较。
DAILY_CAP = Decimal("1.20")
MONTHLY_CAP = Decimal("25")


@dataclass(slots=True)
class BudgetGuard:
    daily_cap: Decimal = DAILY_CAP
    monthly_cap: Decimal = MONTHLY_CAP
    daily_spent: Decimal = Decimal("0")
    monthly_spent: Decimal = Decimal("0")

    def can_call(self) -> bool:
        """预算是否还允许调用 LLM。False → 本轮降级纯量化。"""
        return self.daily_spent < self.daily_cap and self.monthly_spent < self.monthly_cap

    def charge(self, cost: Decimal) -> None:
        self.daily_spent += cost
        self.monthly_spent += cost

    def reset_daily(self) -> None:
        self.daily_spent = Decimal("0")

    def reset_monthly(self) -> None:
        self.monthly_spent = Decimal("0")
        self.daily_spent = Decimal("0")

    @property
    def daily_remaining(self) -> Decimal:
        return max(Decimal("0"), self.daily_cap - self.daily_spent)
