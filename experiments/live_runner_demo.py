"""⚠️ 实验代码 —— 禁止实盘（宪法 III 违规样本，仅存档）。

本文件直接调 gateway.submit()，未经 G1-G14 风控闸门链（违反 CT-RG-1「无旁路」），
仅曾用于模拟盘演示。任何正式下单路径必须走 strategy/engine.py 的 GateChain。
移出正式包 src/quant/，不参与打包与导入。分析报告 C1 处置记录：2026-07-21。
"""

from __future__ import annotations

import asyncio
import os
import time
from decimal import Decimal

from quant.core.symbol import Market, Symbol
from quant.core.types import OrderRequest, OrderType, Side
from quant.markets.okx_swap.caps import build_caps
from quant.markets.okx_swap.gateway import OKXGateway
from quant.markets.okx_swap.okx_client import OKXClient
from quant.markets.okx_swap.signals import cvd, mid_price, order_book_imbalance
from quant.markets.okx_swap.ws_feed import RestPoller

# --- 策略参数（模拟盘演示；日内波段量级）---
INST = "ETH-USDT-SWAP"
POLL_SEC = 3
SIZE = Decimal("0.1")          # 合约张数（≈$19 名义）
OBI_ENTRY = 0.35               # |OBI| 超此值且连续 2 次同向 → 开仓
TP_PCT = Decimal("0.0025")     # 止盈 +0.25%
SL_PCT = Decimal("0.005")      # 交易所侧止损 -0.5%
MAX_HOLD_SEC = 180             # 最长持仓
COOLDOWN_SEC = 20             # 平仓后冷却


def _log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


async def run() -> None:
    c = OKXClient(os.environ["OKX_API_KEY"], os.environ["OKX_SECRET"], os.environ["OKX_PASSPHRASE"],
                  base_url=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
                  simulated=os.environ.get("OKX_SIMULATED", "1") == "1")
    caps = build_caps(c.instruments("SWAP"), INST)
    sym = Symbol(Market.OKX_SWAP, INST)
    gw = OKXGateway(c, caps, [sym], td_mode="cross")
    poller = RestPoller(c, INST, sym.uid)

    await gw.ensure_leverage_locked()
    _log(f"策略启动：{INST} OBI动量 size={SIZE}张 TP={TP_PCT} SL={SL_PCT} 循环{POLL_SEC}s")

    prev_dir = 0            # 上一次 OBI 方向（连续确认用）
    entry_px = None
    open_ts = 0
    stop_algo_id = None
    last_close_ts = 0
    n = 0

    while True:
        try:
            book = poller.poll_book(depth=20)
            trades = poller.poll_trades(limit=50)
            obi = order_book_imbalance(book)
            mid = mid_price(book)
            cur_dir = 1 if obi > OBI_ENTRY else -1 if obi < -OBI_ENTRY else 0

            positions = await gw.positions()
            pos = positions[0] if positions else None

            if pos is None:
                # 若本地以为持仓但交易所已无（止损被触发）→ 清状态
                if entry_px is not None:
                    _log(f"仓位已不存在（可能止损成交）。清状态。")
                    entry_px = None; stop_algo_id = None

                # 入场：连续 2 次同向且信号显著 + 冷却结束
                if cur_dir != 0 and cur_dir == prev_dir and (time.time() - last_close_ts) > COOLDOWN_SEC:
                    side = Side.BUY if cur_dir > 0 else Side.SELL
                    ack = await gw.submit(OrderRequest(sym, side, OrderType.MARKET, SIZE,
                                                       f"obimom{n}"))
                    await asyncio.sleep(0.8)
                    ps = await gw.positions()
                    if ps:
                        p0 = ps[0]
                        entry_px = p0.entry_px; open_ts = time.time()
                        stop_px = (entry_px * (1 - SL_PCT) if side is Side.BUY
                                   else entry_px * (1 + SL_PCT)).quantize(Decimal("0.01"))
                        sack = await gw.place_protective_stop(p0, stop_px)
                        stop_algo_id = sack.exchange_order_id
                        _log(f"▶ 开{'多' if side is Side.BUY else '空'} {SIZE}张 @ {entry_px} "
                             f"OBI={obi:+.3f} 止损@{stop_px}")
                        n += 1
            else:
                # 持仓中：TP / 时间止盈（交易所侧止损兜底 SL）
                long = pos.side is Side.BUY
                pnl_pct = ((mid - pos.entry_px) / pos.entry_px) * (1 if long else -1)
                held = time.time() - open_ts
                reason = None
                if pnl_pct >= TP_PCT:
                    reason = f"止盈 +{float(pnl_pct)*100:.2f}%"
                elif held > MAX_HOLD_SEC:
                    reason = f"超时 {int(held)}s ({float(pnl_pct)*100:+.2f}%)"
                if reason:
                    if stop_algo_id:
                        try:
                            c.cancel_algos([{"algoId": stop_algo_id, "instId": INST}])
                        except Exception:  # noqa: BLE001
                            pass
                    await gw.market_close(pos)
                    _log(f"■ 平{'多' if long else '空'} @ ~{float(mid):.2f}  {reason}")
                    entry_px = None; stop_algo_id = None; last_close_ts = time.time()

            prev_dir = cur_dir
        except Exception as e:  # noqa: BLE001
            _log(f"[warn] 迭代异常（不中断）: {type(e).__name__}: {str(e)[:60]}")

        await asyncio.sleep(POLL_SEC)


if __name__ == "__main__":
    asyncio.run(run())
