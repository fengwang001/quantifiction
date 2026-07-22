"""T019/T019a/T020：币安永续执行网关（接缝2 实现）。

- 传输复用官方 UMFutures 客户端（注入，便于 mock 单测；research R2）
- 自研订单状态机 + 幂等 client_order_id（CT-EG-1）
- 启动强制 1x 锁定（CT-EG-6，宪法 III/IV 最终防线 F7）
- 成交后强制止损，挂失败即市价平仓（CT-EG-2，宪法 III）
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from quant.core.events import Severity, log_event
from quant.core.symbol import Symbol
from quant.core.types import (
    MarketCaps,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    ReconcileResult,
    Side,
)


class BinanceClient(Protocol):
    """官方 UMFutures 客户端所需方法的鸭子类型子集。"""

    def new_order(self, **params: Any) -> dict[str, Any]: ...
    def cancel_order(self, **params: Any) -> dict[str, Any]: ...
    def get_position_risk(self, **params: Any) -> list[dict[str, Any]]: ...
    def change_leverage(self, **params: Any) -> dict[str, Any]: ...
    def change_margin_type(self, **params: Any) -> dict[str, Any]: ...
    def change_position_mode(self, **params: Any) -> dict[str, Any]: ...


class LeverageLockError(RuntimeError):
    """1x 锁定校验失败 → 拒绝启动。"""


class BinanceGateway:
    def __init__(self, client: BinanceClient, caps: MarketCaps, symbols: list[Symbol]) -> None:
        self._c = client
        self._caps = caps
        self._symbols = symbols
        self._acks: dict[str, OrderAck] = {}  # 幂等：client_order_id → ack

    @property
    def caps(self) -> MarketCaps:
        return self._caps

    # --- T019a：启动锁定 1x（CT-EG-6）---
    async def ensure_leverage_locked(self) -> None:
        for sym in self._symbols:
            self._c.change_margin_type(symbol=sym.raw, marginType="CROSSED")
            resp = self._c.change_leverage(symbol=sym.raw, leverage=1)
            actual = int(resp.get("leverage", -1))
            if actual != 1:
                raise LeverageLockError(
                    f"{sym.raw} 杠杆锁定失败：交易所返回 {actual}，拒绝启动（宪法 III F7）"
                )
        # 单向持仓（忽略「已是该模式」类错误由调用方保证幂等）
        try:
            self._c.change_position_mode(dualSidePosition="false")
        except Exception as e:  # noqa: BLE001
            log_event(Severity.WARN, "gateway", "position_mode", detail=str(e))

    # --- T019：下单（幂等 + 状态机）---
    async def submit(self, order: OrderRequest) -> OrderAck:
        if order.client_order_id in self._acks:
            return self._acks[order.client_order_id]  # 幂等短路（CT-EG-1）

        params: dict[str, Any] = {
            "symbol": order.symbol.raw,
            "side": order.side.value,
            "type": order.type.value,
            "quantity": str(order.qty),
            "newClientOrderId": order.client_order_id,
        }
        if order.type is OrderType.LIMIT:
            params["price"] = str(order.price)
            params["timeInForce"] = "GTC"
        if order.reduce_only:
            params["reduceOnly"] = "true"
        if order.stop_price is not None:
            params["stopPrice"] = str(order.stop_price)

        resp = self._c.new_order(**params)
        ack = OrderAck(
            client_order_id=order.client_order_id,
            exchange_order_id=str(resp.get("orderId", "")),
            status=_map_status(resp.get("status", "NEW")),
        )
        self._acks[order.client_order_id] = ack
        return ack

    async def open_orders(self) -> list[dict[str, Any]]:
        """当前挂单（供带仓重启恢复检查既有止损，T026）。"""
        if hasattr(self._c, "get_orders"):
            return self._c.get_orders()  # type: ignore[attr-defined]
        return []

    async def has_protective_stop(self, symbol: Symbol) -> bool:
        for o in await self.open_orders():
            if o.get("symbol") == symbol.raw and o.get("type") == "STOP_MARKET":
                return True
        return False

    async def market_close(self, pos: Position) -> None:
        """市价平掉某仓（全平/兜底用）。"""
        close_side = Side.SELL if pos.side is Side.BUY else Side.BUY
        await self._force_market_close(pos, close_side)

    async def cancel(self, client_order_id: str) -> None:
        ack = self._acks.get(client_order_id)
        if ack is None:
            return
        self._c.cancel_order(origClientOrderId=client_order_id)

    async def positions(self) -> list[Position]:
        out: list[Position] = []
        for r in self._c.get_position_risk():
            amt = Decimal(str(r["positionAmt"]))
            if amt == 0:
                continue
            out.append(
                Position(
                    symbol=Symbol.parse(f"binance_ums:{r['symbol']}"),
                    side=Side.BUY if amt > 0 else Side.SELL,
                    qty=abs(amt),
                    entry_px=Decimal(str(r["entryPrice"])),
                    unrealized_pnl=Decimal(str(r.get("unRealizedProfit", "0"))),
                    leverage=int(r.get("leverage", 1)),
                )
            )
        return out

    async def reconcile(self) -> ReconcileResult:
        # 对账逻辑委托 reconcile.py；此处提供交易所侧真相
        positions = await self.positions()
        return ReconcileResult(consistent=True, detail=f"{len(positions)} open")

    # --- T020：强制止损，挂失败即市价平仓（CT-EG-2）---
    async def place_protective_stop(self, pos: Position, stop_px: Decimal) -> OrderAck:
        close_side = Side.SELL if pos.side is Side.BUY else Side.BUY
        try:
            resp = self._c.new_order(
                symbol=pos.symbol.raw,
                side=close_side.value,
                type=OrderType.STOP_MARKET.value,
                stopPrice=str(stop_px),
                closePosition="true",
            )
            return OrderAck(
                client_order_id=f"stop-{pos.symbol.raw}",
                exchange_order_id=str(resp.get("orderId", "")),
                status=OrderStatus.SUBMITTED,
            )
        except Exception as e:  # noqa: BLE001
            log_event(Severity.FATAL, "gateway", "stop_failed_force_close",
                      symbol=pos.symbol.uid, error=str(e))
            await self._force_market_close(pos, close_side)
            raise

    async def _force_market_close(self, pos: Position, close_side: Side) -> None:
        """止损挂失败的兜底：立即市价平仓，不允许裸持仓（宪法 III）。"""
        self._c.new_order(
            symbol=pos.symbol.raw,
            side=close_side.value,
            type=OrderType.MARKET.value,
            quantity=str(pos.qty),
            reduceOnly="true",
        )


def _map_status(raw: str) -> OrderStatus:
    mapping = {
        "NEW": OrderStatus.SUBMITTED,
        "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
        "FILLED": OrderStatus.FILLED,
        "REJECTED": OrderStatus.REJECTED,
        "CANCELED": OrderStatus.CANCELED,
        "EXPIRED": OrderStatus.CANCELED,
    }
    return mapping.get(raw, OrderStatus.SUBMITTED)
