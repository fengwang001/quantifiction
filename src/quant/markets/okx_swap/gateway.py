"""欧易 SWAP 执行网关（接缝2 实现）。

- 传输复用签名客户端 OKXClient（注入，便于 mock）
- 订单状态机 + 幂等 clOrdId（CT-EG-1）
- 启动强制 1x 锁定 + 全仓（CT-EG-6，宪法 III/IV）
- 成交后强制止损，挂失败即市价平仓（CT-EG-2，宪法 III）

下单量 sz 为合约张数。instId 形如 ETH-USDT-SWAP。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from quant.core.events import Severity, log_event
from quant.core.symbol import Market, Symbol
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


class LeverageLockError(RuntimeError):
    pass


class OKXStopError(RuntimeError):
    pass


_ORD_TYPE = {OrderType.MARKET: "market", OrderType.LIMIT: "limit"}


class OKXGateway:
    def __init__(self, client: Any, caps: MarketCaps, symbols: list[Symbol],
                 td_mode: str = "cross") -> None:
        self._c = client
        self._caps = caps
        self._symbols = symbols
        self._td = td_mode
        self._acks: dict[str, OrderAck] = {}

    @property
    def caps(self) -> MarketCaps:
        return self._caps

    async def ensure_leverage_locked(self) -> None:
        """CT-EG-6：预检账户模式 + 设杠杆=1 + 全仓；读回校验，不一致拒绝启动。"""
        # 预检：简单模式(acctLv=1)不能交易永续，启动即拒绝（避免运行时才 51010 失败）
        cfg = self._c.request("GET", "/api/v5/account/config")
        acct_lv = str(cfg[0].get("acctLv", "")) if cfg else ""
        if acct_lv == "1":
            raise LeverageLockError(
                "账户为简单交易模式(acctLv=1)，无法交易永续。"
                "请在 OKX 升级为『单币种保证金模式』(acctLv≥2) 后再启动。"
            )

        for sym in self._symbols:
            resp = self._c.set_leverage(instId=sym.raw, lever="1", mgnMode=self._td)
            row = resp[0] if resp else {}
            if str(row.get("lever", "")) not in ("1", "1.0"):
                raise LeverageLockError(
                    f"{sym.raw} 杠杆锁定失败：欧易返回 {row.get('lever')!r}，拒绝启动"
                )

    async def submit(self, order: OrderRequest) -> OrderAck:
        if order.client_order_id in self._acks:
            return self._acks[order.client_order_id]  # 幂等（CT-EG-1）

        params: dict[str, Any] = {
            "instId": order.symbol.raw,
            "tdMode": self._td,
            "side": order.side.value.lower(),        # buy / sell
            "ordType": _ORD_TYPE[order.type],
            "sz": str(order.qty),                    # 合约张数
            "clOrdId": _clid(order.client_order_id),
        }
        if order.type is OrderType.LIMIT:
            params["px"] = str(order.price)
        if order.reduce_only:
            params["reduceOnly"] = "true"

        resp = self._c.place_order(**params)
        row = resp[0] if resp else {}
        ack = OrderAck(
            client_order_id=order.client_order_id,
            exchange_order_id=str(row.get("ordId", "")),
            status=OrderStatus.SUBMITTED if str(row.get("sCode", "0")) == "0"
            else OrderStatus.REJECTED,
        )
        self._acks[order.client_order_id] = ack
        return ack

    async def cancel(self, client_order_id: str) -> None:
        if client_order_id not in self._acks:
            return
        sym = self._symbols[0].raw
        self._c.cancel_order(instId=sym, clOrdId=_clid(client_order_id))

    async def positions(self) -> list[Position]:
        out: list[Position] = []
        for r in self._c.positions():
            pos = Decimal(str(r.get("pos", "0")))
            if pos == 0:
                continue
            out.append(Position(
                symbol=Symbol(Market.OKX_SWAP, r["instId"]),
                side=Side.BUY if pos > 0 else Side.SELL,
                qty=abs(pos),
                entry_px=Decimal(str(r.get("avgPx", "0") or "0")),
                unrealized_pnl=Decimal(str(r.get("upl", "0") or "0")),
                leverage=int(float(r.get("lever", "1") or "1")),
            ))
        return out

    async def reconcile(self) -> ReconcileResult:
        return ReconcileResult(consistent=True, detail=f"{len(await self.positions())} open")

    async def place_protective_stop(self, pos: Position, stop_px: Decimal) -> OrderAck:
        """止损走 /trade/order-algo（条件单）。挂失败即市价平仓（CT-EG-2）。"""
        close_side = Side.SELL if pos.side is Side.BUY else Side.BUY
        try:
            resp = self._c.place_algo_order(
                instId=pos.symbol.raw,
                tdMode=self._td,
                side=close_side.value.lower(),
                ordType="conditional",          # 条件单（止损）
                sz=str(pos.qty),
                slTriggerPx=str(stop_px),
                slOrdPx="-1",                   # -1 = 市价止损
                reduceOnly="true",
            )
            row = resp[0] if resp else {}
            if str(row.get("sCode", "0")) not in ("0", ""):
                raise OKXStopError(f"algo sCode={row.get('sCode')} {row.get('sMsg')}")
            return OrderAck(f"stop-{pos.symbol.raw}", str(row.get("algoId", "")),
                            OrderStatus.SUBMITTED)
        except Exception as e:  # noqa: BLE001
            log_event(Severity.FATAL, "okx_gateway", "stop_failed_force_close",
                      symbol=pos.symbol.uid, error=str(e))
            await self.market_close(pos)
            raise

    async def market_close(self, pos: Position) -> None:
        close_side = Side.SELL if pos.side is Side.BUY else Side.BUY
        self._c.place_order(
            instId=pos.symbol.raw, tdMode=self._td, side=close_side.value.lower(),
            ordType="market", sz=str(pos.qty), reduceOnly="true",
        )


def _clid(cid: str) -> str:
    """欧易 clOrdId 仅允许字母数字，最长 32：去连字符并截断。"""
    return cid.replace("-", "").replace("_", "")[:32]
