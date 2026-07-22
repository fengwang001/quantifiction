"""T025/T026：L2 决策主循环（US1 最小版：无策略、无 LLM）。

职责：接订单 → 过闸门链 → 下单 → 立即挂止损 → 写心跳。
HALT 类闸门结果触发系统 HALTED（全平 + 停机，宪法 III CT-RG-3）。
带仓重启恢复：启动检查既有仓位+止损，不重复挂单（T026）。

依赖以协议注入，便于单测（无需连交易所）。
"""
from __future__ import annotations

import time
from decimal import Decimal
from enum import Enum
from typing import Any, Awaitable, Callable

from quant.core.events import Severity, log_event
from quant.core.types import (
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
)
from quant.core.symbol import Market, Symbol
from quant.risk.gate import GateChain, RiskContext, Verdict
from quant.core.types import LLMSignal
from quant.cognitive.breaker import Breaker, CognitiveMode
from quant.strategy.fusion import final_score
from quant.strategy.shadow import ShadowFill, simulate_fill
from quant.strategy.sizing import size_order


class SystemState(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    HALTED = "HALTED"  # 需人工重启


class Engine:
    def __init__(
        self,
        gateway: Any,
        gate_chain: GateChain,
        stop_pct: Decimal = Decimal("0.015"),
        heartbeat_sink: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._gw = gateway
        self._chain = gate_chain
        self._stop_pct = stop_pct
        self._hb = heartbeat_sink
        self.state = SystemState.RUNNING

    async def heartbeat(self) -> int:
        ts = int(time.time() * 1000)
        if self._hb:
            await self._hb(ts)
        return ts

    async def submit_protected(self, order: OrderRequest, ctx: RiskContext) -> OrderAck | None:
        """US1 核心：闸门 → 下单 → 挂止损。返回 None 表示被拒/停机。"""
        if self.state is not SystemState.RUNNING:
            log_event(Severity.WARN, "engine", "rejected_not_running", state=self.state.value)
            return None

        result = self._chain.evaluate(ctx, order)
        if result.verdict is Verdict.HALT:
            log_event(Severity.FATAL, "engine", "gate_halt", gate=result.gate, reason=result.reason)
            await self._halt_and_flat(result.reason)
            return None
        if result.verdict is Verdict.REJECT:
            log_event(Severity.INFO, "engine", "gate_reject", gate=result.gate, reason=result.reason)
            return None

        ack = await self._gw.submit(order)
        if ack.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            await self._protect_new_fill(order)
        return ack

    async def _protect_new_fill(self, order: OrderRequest) -> None:
        """成交后立即挂止损（宪法 III）。止损价由入场价与 stop_pct 推。"""
        for pos in await self._gw.positions():
            if pos.symbol.uid != order.symbol.uid:
                continue
            stop_px = _stop_price(pos, self._stop_pct)
            await self._gw.place_protective_stop(pos, stop_px)

    async def recover(self) -> None:
        """T026：带仓重启恢复——补齐缺失止损，不重复挂单。"""
        for pos in await self._gw.positions():
            if await self._gw.has_protective_stop(pos.symbol):
                log_event(Severity.INFO, "engine", "recover_stop_exists", symbol=pos.symbol.uid)
                continue
            stop_px = _stop_price(pos, self._stop_pct)
            await self._gw.place_protective_stop(pos, stop_px)
            log_event(Severity.WARN, "engine", "recover_stop_replaced", symbol=pos.symbol.uid)

    async def _halt_and_flat(self, reason: str) -> None:
        self.state = SystemState.HALTED
        for pos in await self._gw.positions():
            await self._gw.market_close(pos)
        log_event(Severity.FATAL, "engine", "halted", reason=reason)

    async def route_by_tier(
        self,
        *,
        raw: str,
        tier: str,
        strategy: str,
        side: Side,
        price: Decimal,
        risk_usd: Decimal,
        stop_pct: Decimal,
        equity: Decimal,
        capital_weight: Decimal,
        min_notional: Decimal,
        ctx: RiskContext,
        market: Market = Market.OKX_SWAP,
        contract_val: Decimal = Decimal(1),
    ) -> OrderAck | ShadowFill | None:
        """T037：按 tier 路由。live→过闸门下单；shadow→假想记账；observe→跳过。

        market/contract_val 由调用方按当前交易所传入（禁硬编码，宪法 VII）。
        """
        if tier == "observe":
            return None

        sz = size_order(price, risk_usd, stop_pct, equity, capital_weight,
                        min_notional, contract_val)
        if not sz.ok:
            log_event(Severity.INFO, "engine", "sizing_reject", raw=raw, reason=sz.reason)
            return None

        order = OrderRequest(
            symbol=Symbol(market, raw),
            side=side,
            type=OrderType.MARKET,
            qty=sz.qty,
            client_order_id=f"{strategy}-{raw}-{ctx.orders_today}",
        )

        if tier == "shadow":
            return simulate_fill(order, strategy, price)  # 不触网关（FR-008）

        # live：更新 ctx 敞口后过完整闸门链再下单
        ctx.per_symbol_notional[order.symbol.uid] = sz.notional
        return await self.submit_protected(order, ctx)

    async def decide_and_route(
        self,
        *,
        raw: str,
        tier: str,
        strategy: str,
        quant_score: float,
        llm: LLMSignal | None,
        price: Decimal,
        risk_usd: Decimal,
        stop_pct: Decimal,
        equity: Decimal,
        capital_weight: Decimal,
        min_notional: Decimal,
        ctx: RiskContext,
        breaker: Breaker | None = None,
        market: Market = Market.OKX_SWAP,
        contract_val: Decimal = Decimal(1),
    ) -> OrderAck | ShadowFill | None:
        """T056：融合全链——LLM 经 breaker/fusion 约束后决定方向与强度，再路由。"""
        # 熔断降级：VETO_ONLY/OFF 时不让 LLM 加成（宪法 II §6.6）
        eff_llm = llm
        if breaker is not None and llm is not None:
            if breaker.mode in (CognitiveMode.VETO_ONLY, CognitiveMode.OFF):
                # 仅保留 veto 语义，剥离 stance 加成
                eff_llm = LLMSignal(llm.symbol_uid, 0.0, 0.0, llm.veto, llm.half_life_sec)

        score = final_score(quant_score, eff_llm)
        if score == 0.0:
            log_event(Severity.INFO, "engine", "fusion_zero", raw=raw)  # veto 或无信号
            return None

        side = Side.BUY if score > 0 else Side.SELL
        # LLM veto 也反映到闸门（G13）
        ctx.llm_veto = bool(eff_llm.veto) if eff_llm is not None else False
        return await self.route_by_tier(
            raw=raw, tier=tier, strategy=strategy, side=side, price=price,
            risk_usd=risk_usd, stop_pct=stop_pct, equity=equity,
            capital_weight=capital_weight, min_notional=min_notional, ctx=ctx,
            market=market, contract_val=contract_val,
        )

    def pause(self) -> None:
        if self.state is SystemState.RUNNING:
            self.state = SystemState.PAUSED

    def resume(self) -> None:
        if self.state is SystemState.PAUSED:
            self.state = SystemState.RUNNING

    async def handle_control(self, cmd: str) -> None:
        """T061：消费 webui 经 Redis 下发的控制指令（strategy 是唯一执行者）。"""
        if cmd == "pause":
            self.pause()
        elif cmd == "resume":
            self.resume()
        elif cmd == "flat":
            for pos in await self._gw.positions():
                await self._gw.market_close(pos)
            log_event(Severity.WARN, "engine", "manual_flat")


def _stop_price(pos: Position, stop_pct: Decimal) -> Decimal:
    """多头止损在下方，空头在上方。"""
    if pos.side is Side.BUY:
        return pos.entry_px * (Decimal(1) - stop_pct)
    return pos.entry_px * (Decimal(1) + stop_pct)
