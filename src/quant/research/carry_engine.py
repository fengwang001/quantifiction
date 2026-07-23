"""资金费 carry 影子引擎（迭代65 pivot：微观结构信号触效率墙后转结构性edge）。

与方向性策略根本不同：不赌价格方向，靠市场中性持仓收取永续每8h资金费。
- 中性建模：perp腿 + spot对冲腿，价格PnL相互抵消，只留资金费 − 费用。
- 收费方向：funding>0 时永续偏贵→持空收多头付的钱；funding<0→持多收空头的钱。
- 只在 |funding| 够高时入场（低费率期不值得付费用），费率转弱/反向即离场。
- 净值 = 累计资金费 − 两腿开平费。资金费按持仓时长 pro-rata 累计（8h 结算的期望）。

edge性质：结构性（持仓补偿），不被HFT竞争掉；但当前费率低(年化<5%)，
需费率走高或长持才明显跑赢费用。此引擎诚实检验：carry在当前行情能否扣费后盈利。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from quant.markets.okx_swap.okx_client import OKXClient

INSTRUMENTS = os.environ.get("CARRY_INSTS", "ETH-USDT-SWAP,BTC-USDT-SWAP,SOL-USDT-SWAP").split(",")
NOTIONAL = 100.0                 # 每个carry头寸名义（USD），与方向性策略同口径
POLL_SEC = 60                    # 资金费变化慢，1分钟轮询足够
FUNDING_INTERVAL_H = 8.0         # OKX 永续 8h 结算一次
# 中性 carry 两腿(perp+spot)开平总费用：maker 每腿往返~0.04%，两腿~0.08%
CARRY_ROUNDTRIP_FEE_PCT = 0.0008
# 入场门槛：单期资金费率绝对值≥此值才值得持仓（年化≈ 阈值×3×365）
# 0.005%/8h ≈ 年化5.5%，需持约10期(3.3天)才够覆盖0.08%费用
# 迭代92：首仓验证0.005%阈值太低——3.5h只收+0.0021却付费0.08，亏0.078。
# 提高到0.02%/8h：只在费率够高、持仓能收够钱覆盖两腿费(0.08%)时才开仓。
# 0.02%/8h 持约4期(32h)可收0.08%覆盖费用；实盘carry只在极端费率regime有利。
ENTER_ABS = float(os.environ.get("CARRY_ENTER", "0.0002"))    # 0.02%/8h（迭代92提高4倍）
EXIT_ABS = float(os.environ.get("CARRY_EXIT", "0.00005"))     # 费率弱于0.005%/8h离场（同步提高）
PERSIST = Path(os.environ.get("CARRY_PERSIST", "data/carry_persist.json"))
STATE = Path(os.environ.get("CARRY_STATE", "data/carry_state.json"))


class CarryPosition:
    """单标的中性 carry 头寸。price-neutral，只累计资金费。"""

    def __init__(self, inst: str) -> None:
        self.inst = inst
        self.side = 0             # 0平 / +1持多收(funding<0) / -1持空收(funding>0)
        self.open_ts = 0.0
        self.accrued = 0.0        # 已累计资金费(USD，正=收到)
        self.last_accrue_ts = 0.0
        self.entry_funding = 0.0
        self.trades: list[dict] = []

    def to_dict(self) -> dict:
        return {"inst": self.inst, "side": self.side, "open_ts": self.open_ts,
                "accrued": self.accrued, "last_accrue_ts": self.last_accrue_ts,
                "entry_funding": self.entry_funding, "trades": self.trades}

    def load(self, d: dict) -> None:
        self.side = d.get("side", 0)
        self.open_ts = d.get("open_ts", 0.0)
        self.accrued = d.get("accrued", 0.0)
        self.last_accrue_ts = d.get("last_accrue_ts", 0.0)
        self.entry_funding = d.get("entry_funding", 0.0)
        self.trades = d.get("trades", [])

    def on_funding(self, funding: float, now: float) -> None:
        """funding=当前资金费率(每8h)。驱动入场/累计/离场。"""
        if self.side == 0:
            # 入场：|funding| 够高才持仓，收被付方向
            if abs(funding) >= ENTER_ABS:
                self.side = -1 if funding > 0 else 1   # funding>0持空收，<0持多收
                self.open_ts = now
                self.last_accrue_ts = now
                self.accrued = 0.0
                self.entry_funding = funding
        else:
            # 累计：pro-rata 按持仓时长折算资金费（收被付方向恒为正收入）
            dt_h = (now - self.last_accrue_ts) / 3600.0
            self.accrued += abs(funding) * (dt_h / FUNDING_INTERVAL_H) * NOTIONAL \
                if (self.side == -1) == (funding > 0) else \
                -abs(funding) * (dt_h / FUNDING_INTERVAL_H) * NOTIONAL  # 若费率反向则倒付
            self.last_accrue_ts = now
            # 离场：费率转弱或方向反转（继续持会倒付）
            flipped = (self.side == -1 and funding < 0) or (self.side == 1 and funding > 0)
            if abs(funding) < EXIT_ABS or flipped:
                fee = NOTIONAL * CARRY_ROUNDTRIP_FEE_PCT
                net = self.accrued - fee
                self.trades.append({
                    "inst": self.inst, "side": "收空" if self.side == -1 else "收多",
                    "open_ms": int(self.open_ts * 1000), "ts": int(now * 1000),
                    "hold_h": round((now - self.open_ts) / 3600, 2),
                    "accrued_usd": round(self.accrued, 4), "fee_usd": round(fee, 4),
                    "net_usd": round(net, 4),
                    "entry_funding_pct": round(self.entry_funding * 100, 5),
                    "reason": "flip" if flipped else "weak",
                })
                self.side = 0
                self.accrued = 0.0


def _load(positions: dict[str, CarryPosition]) -> None:
    if PERSIST.exists():
        try:
            d = json.loads(PERSIST.read_text(encoding="utf-8"))
            for pd in d.get("positions", []):
                if pd["inst"] in positions:
                    positions[pd["inst"]].load(pd)
            print(f"[carry恢复] {sum(len(p.trades) for p in positions.values())}笔历史", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[carry恢复失败] {e}", flush=True)


def _save(positions: dict[str, CarryPosition]) -> None:
    PERSIST.parent.mkdir(parents=True, exist_ok=True)
    tmp = PERSIST.with_suffix(".tmp")
    tmp.write_text(json.dumps({"positions": [p.to_dict() for p in positions.values()]},
                              ensure_ascii=False), encoding="utf-8")
    tmp.replace(PERSIST)


def _write_state(positions: dict[str, CarryPosition], fundings: dict[str, float]) -> None:
    open_pos = []
    total_net = 0.0
    for p in positions.values():
        total_net += sum(t["net_usd"] for t in p.trades)
        if p.side != 0:
            total_net += p.accrued
            open_pos.append({
                "inst": p.inst, "side": "收空" if p.side == -1 else "收多",
                "hold_h": round((time.time() - p.open_ts) / 3600, 2),
                "accrued_usd": round(p.accrued, 4),
                "cur_funding_pct": round(fundings.get(p.inst, 0) * 100, 5),
            })
    STATE.write_text(json.dumps({
        "ts": int(time.time() * 1000), "total_net_usd": round(total_net, 4),
        "closed_trades": sum(len(p.trades) for p in positions.values()),
        "open_positions": open_pos,
        "fundings_pct": {k: round(v * 100, 5) for k, v in fundings.items()},
    }, ensure_ascii=False), encoding="utf-8")


def _funding(client: OKXClient, inst: str) -> float | None:
    try:
        d = client.request("GET", "/api/v5/public/funding-rate", {"instId": inst})[0]
        return float(d["fundingRate"])
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    c = OKXClient("x", "x", "x", base_url=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
                  simulated=False)
    positions = {inst: CarryPosition(inst) for inst in INSTRUMENTS}
    _load(positions)
    print(f"资金费carry引擎启动：{len(INSTRUMENTS)}标的 · 入场阈值{ENTER_ABS*100:.4f}%/8h "
          f"· 中性两腿费{CARRY_ROUNDTRIP_FEE_PCT*100:.2f}% · 每头寸${NOTIONAL}", flush=True)
    ticks = 0
    while True:
        try:
            fundings = {}
            now = time.time()
            for inst in INSTRUMENTS:
                fr = _funding(c, inst)
                if fr is None:
                    continue
                fundings[inst] = fr
                positions[inst].on_funding(fr, now)
            _write_state(positions, fundings)
            ticks += 1
            if ticks % 5 == 0:
                _save(positions)
            time.sleep(POLL_SEC)
        except KeyboardInterrupt:
            _save(positions)
            break
        except Exception as e:  # noqa: BLE001
            print(f"[carry错误] {e}", flush=True)
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
