"""影子模式多策略对比引擎（宪法 VI：先验证后加码）。

同时跑多个策略变体，全部只记账、不真下单，但**扣真实手续费**统计净收益。
目的：在零风险下回答"哪个策略扣费后还赚钱"——绝大多数会被证伪，这正是价值。

结果写 data/shadow_state.json，看板读取展示。

运行：
    uv run python -m quant.research.shadow_engine
"""
from __future__ import annotations

import json
import math
import os
import time
from decimal import Decimal
from pathlib import Path

from quant.core.types import LLMSignal
from quant.markets.okx_swap.okx_client import OKXClient
from quant.markets.okx_swap.signals import cvd, mid_price, order_book_imbalance
from quant.markets.okx_swap.ws_feed import RestPoller, WSPoller
from quant.strategy.fusion import final_score

AGENT_STANCE = Path("data/agent_stance.json")
SWITCH = Path("data/strategy_switch.json")   # 策略开关（UI/规则可停用，disabled=只出不进）
OVERRIDES = Path("data/strategy_overrides.json")  # 策略管理模块的人工参数覆盖（热生效）

INST = os.environ.get("SHADOW_INST", "ETH-USDT-SWAP")  # 多标的：并行引擎各设此变量（迭代47）
POLL_SEC = 3
NOTIONAL = 100.0                 # 每笔虚拟名义（USD），统一口径便于对比
TAKER_FEE = 0.0005               # 欧易 taker 单边；往返 = 2×
ROUNDTRIP_FEE_PCT = TAKER_FEE * 2  # 0.10%
CVD_SCALE = 2000.0               # CVD 归一化尺度
OUT = Path(os.getenv("SHADOW_OUT", "data/shadow_state.json"))          # 看板读的展示快照
PERSIST = Path(os.getenv("SHADOW_PERSIST", "data/shadow_persist.json"))  # 全量状态（重启恢复）


class Strategy:
    """配置驱动的策略变体。signal: obi|cvd；mode: mom(顺势)|rev(反转)。"""

    def __init__(self, name, signal, mode, entry_th, tp_pct, max_hold_sec, cooldown=15,
                 sl_pct=None, author="human", min_range=None,
                 trail_arm=None, trail_gap=None, trend_gate=None, trail_frac=None,
                 fee_pct=None):
        self.name = name
        self.signal = signal
        self.mode = mode
        self.entry_th = entry_th
        self.tp_pct = tp_pct
        self.max_hold = max_hold_sec
        self.cooldown = cooldown
        self.sl_pct = sl_pct       # 止损（None=无，292笔教训：纯超时出场收集漂移亏损）
        self.author = author       # provenance：agent 生成的策略标记 author="agent"
        self.min_range = min_range # 体制过滤：近1h波幅低于此值不入场（动量需要市场在动）
        self.trail_arm = trail_arm # 追踪止损：浮盈达此值(比例)后武装
        self.trail_gap = trail_gap # 武装后从峰值回撤此值即锁定离场
        self.trend_gate = trend_gate  # 顺势闸门：逆30m动量超此阈值不开仓（迭代39：OBI陷阱教训）
        self.trail_frac = trail_frac  # 比例追踪：回撤到峰值的(1-frac)即离场，随行情缩放（迭代46：固定gap在小行情全回吐）
        self.fee_pct = fee_pct if fee_pct is not None else ROUNDTRIP_FEE_PCT  # 往返费率：maker可低至0.04%（迭代58费用墙）
        # 状态
        self.pos = 0                 # 0 / +1 多 / -1 空
        self.entry_px = 0.0
        self.open_ts = 0.0
        self.prev_dir = 0
        self.last_close_ts = 0.0
        # 统计
        self.trades = []             # 每笔 {dir, entry, exit, gross_pct, net_pct, net_usd, hold, reason, ts}
        self.equity_curve = [0.0]    # 累计净收益 USD

    def on_tick(self, feat, now):
        raw = feat[self.signal]
        cur_dir = 1 if raw > self.entry_th else -1 if raw < -self.entry_th else 0
        mid = feat["mid"]

        if self.pos == 0:
            if not getattr(self, "enabled", True):
                self.prev_dir = cur_dir
                return   # 已停用：不开新仓（持仓中的会正常走完出场）
            confirmed = cur_dir != 0 and cur_dir == self.prev_dir
            cooled = (now - self.last_close_ts) > self.cooldown
            regime_ok = (self.min_range is None
                         or feat.get("range1h", 0.0) >= self.min_range)
            if confirmed and cooled and regime_ok:
                side = cur_dir if self.mode == "mom" else -cur_dir
                # 顺势闸门（迭代39）：逆30m动量不开仓——旗舰两笔亏损皆逆势开多(MFE仅+0.08)
                if self.trend_gate is not None:
                    m30 = feat.get("mom30m", 0.0)
                    if (side > 0 and m30 < -self.trend_gate) or \
                       (side < 0 and m30 > self.trend_gate):
                        self.prev_dir = cur_dir
                        return
                self.pos = side
                self.entry_px = mid
                self.open_ts = now
                self.mfe = 0.0; self.mae = 0.0
        else:
            pnl_pct = (mid - self.entry_px) / self.entry_px * self.pos
            self.mfe = max(getattr(self, 'mfe', 0.0), pnl_pct)
            self.mae = min(getattr(self, 'mae', 0.0), pnl_pct)
            held = now - self.open_ts
            reason = None
            if pnl_pct >= self.tp_pct:
                reason = "tp"
            elif (self.trail_frac is not None and self.trail_arm is not None
                  and self.mfe >= self.trail_arm
                  and pnl_pct <= self.mfe * (1 - self.trail_frac)):
                reason = "trail"   # 比例追踪：锁定峰值的(1-frac)，随MFE缩放（迭代46）
            elif (self.trail_arm is not None and self.trail_gap is not None
                  and self.mfe >= self.trail_arm
                  and pnl_pct <= self.mfe - self.trail_gap):
                reason = "trail"
            elif self.sl_pct is not None and pnl_pct <= -self.sl_pct:
                reason = "sl"
            elif held > self.max_hold:
                reason = "time"
            if reason:
                self._close(mid, pnl_pct, held, reason, now)

        self.prev_dir = cur_dir

    def _close(self, exit_px, gross_pct, held, reason, now):
        fee = getattr(self, "fee_pct", ROUNDTRIP_FEE_PCT)   # 可按策略配置(maker实验，迭代58)
        net_pct = gross_pct - fee
        net_usd = NOTIONAL * net_pct
        gross_usd = NOTIONAL * gross_pct
        fee_usd = NOTIONAL * fee
        # 买入价/卖出价：多头=先买后卖；空头=先卖后买
        if self.pos > 0:
            buy_px, sell_px = self.entry_px, exit_px
        else:
            sell_px, buy_px = self.entry_px, exit_px
        # 买入/卖出时间：多头=先买(开)后卖(平)；空头=先卖(开)后买(平)
        open_ms, close_ms = int(self.open_ts * 1000), int(now * 1000)
        if self.pos > 0:
            buy_ms, sell_ms = open_ms, close_ms
        else:
            sell_ms, buy_ms = open_ms, close_ms
        self.trades.append({
            "strategy_version_id": getattr(self, "version_id", ""),   # 版本留痕（宪法 V）
            "dir": "多" if self.pos > 0 else "空",
            "entry": round(self.entry_px, 2), "exit": round(exit_px, 2),
            "buy_px": round(buy_px, 2), "sell_px": round(sell_px, 2),
            "buy_ms": buy_ms, "sell_ms": sell_ms,
            "gross_pct": round(gross_pct * 100, 4), "net_pct": round(net_pct * 100, 4),
            "gross_usd": round(gross_usd, 4), "fee_usd": round(fee_usd, 4),
            "net_usd": round(net_usd, 4), "hold": int(held), "reason": reason,
            "mfe_pct": round(getattr(self, 'mfe', 0.0) * 100, 4),
            "mae_pct": round(getattr(self, 'mae', 0.0) * 100, 4),
            "open_ms": open_ms, "ts": close_ms,
        })
        self.equity_curve.append(round(self.equity_curve[-1] + net_usd, 4))
        self.pos = 0
        self.last_close_ts = now

    def to_dict(self):
        """全量序列化（重启恢复用）。"""
        return {
            "name": self.name, "signal": self.signal, "mode": self.mode,
            "entry_th": self.entry_th, "tp_pct": self.tp_pct, "max_hold": self.max_hold,
            "cooldown": self.cooldown, "pos": self.pos, "entry_px": self.entry_px,
            "open_ts": self.open_ts, "prev_dir": self.prev_dir,
            "last_close_ts": self.last_close_ts,
            "mfe": getattr(self, "mfe", 0.0), "mae": getattr(self, "mae", 0.0),
            "trades": self.trades, "equity_curve": self.equity_curve,
        }

    def load_dict(self, d):
        """按名恢复历史状态（保留代码里的当前参数，只恢复累积数据）。"""
        self.pos = d.get("pos", 0)
        self.entry_px = d.get("entry_px", 0.0)
        self.open_ts = d.get("open_ts", 0.0)
        self.prev_dir = d.get("prev_dir", 0)
        self.last_close_ts = d.get("last_close_ts", 0.0)
        self.mfe = d.get("mfe", 0.0); self.mae = d.get("mae", 0.0)
        self.trades = d.get("trades", [])
        self.equity_curve = d.get("equity_curve", [0.0])

    def stats(self):
        n = len(self.trades)
        fee = getattr(self, "fee_pct", ROUNDTRIP_FEE_PCT)
        nets = [t["net_usd"] for t in self.trades]
        grosss = [t["net_usd"] + t.get("fee_usd", NOTIONAL * fee) for t in self.trades]
        wins = sum(1 for x in nets if x > 0)
        net_sum = sum(nets)
        gross_sum = sum(grosss)
        fee_sum = sum(t.get("fee_usd", NOTIONAL * fee) for t in self.trades)
        # 简易夏普：每笔净收益率的均值/标准差
        rets = [t["net_pct"] for t in self.trades]
        sharpe = 0.0
        if len(rets) > 1:
            mu = sum(rets) / len(rets)
            sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
            sharpe = (mu / sd) if sd > 0 else 0.0
        # 最大回撤
        peak = self.equity_curve[0]; mdd = 0.0
        for v in self.equity_curve:
            peak = max(peak, v)
            mdd = min(mdd, v - peak)
        return {
            "name": self.name, "signal": self.signal, "mode": self.mode,
            "tp_pct": self.tp_pct * 100, "trades": n, "open": self.pos != 0,
            "enabled": getattr(self, "enabled", True),
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "gross_usd": round(gross_sum, 3), "fee_usd": round(fee_sum, 3),
            "net_usd": round(net_sum, 3), "sharpe": round(sharpe, 3),
            "max_dd": round(mdd, 3),
            "equity_curve": self.equity_curve,   # 全历史（与详情弹窗一致，不再截断60点）
            "recent": self.trades[-8:][::-1],
        }


class AgentStrategy(Strategy):
    """Agent 增强：LLM 出方向观点(stance/veto)，OBI 出时机，融合决策（宪法 II）。

    - LLM 观点由 agent_runner 独立进程每 15min 更新，经 data/agent_stance.json 读入
    - veto=true → 不开仓；stance 与 OBI 同向 → 加成；反向 → 削弱
    - LLM 观点缺失/过期 → 降级为纯 OBI（宪法 II 优雅降级）
    """

    def __init__(self, name, entry_th=0.45, tp_pct=0.01, max_hold=7200, cooldown=120,
                 sl_pct=0.006, trail_arm=None, trail_gap=None):
        # b 修复：agent 出的是"数小时"方向观点 → 只应指挥小时级波段（TP1% 持仓≤2h），
        # 不再指挥 3 分钟超短单（时间尺度错配是 0% 胜率的根因之一）
        super().__init__(name, "obi", "mom", entry_th, tp_pct, max_hold, cooldown,
                         sl_pct=sl_pct, trail_arm=trail_arm, trail_gap=trail_gap)
        self.llm_stance = 0.0
        self.llm_veto = False
        self.llm_age_sec = 1e9

    def set_agent(self, stance, veto, age_sec, half_life):
        # 观点超过半衰期 → 失效降级
        if age_sec > half_life > 0:
            self.llm_stance, self.llm_veto = 0.0, False
        else:
            self.llm_stance, self.llm_veto = stance, veto
        self.llm_age_sec = age_sec

    def on_tick(self, feat, now):
        obi = feat["obi"]
        llm = (LLMSignal("okx_swap:ETH-USDT-SWAP", self.llm_stance, 0.6, self.llm_veto, 3600)
               if (self.llm_stance != 0 or self.llm_veto) else None)
        fused = final_score(obi, llm)   # 宪法 II 融合
        cur_dir = 1 if fused > self.entry_th else -1 if fused < -self.entry_th else 0
        mid = feat["mid"]

        if self.pos == 0:
            if not getattr(self, "enabled", True):
                self.prev_dir = cur_dir
                return
            confirmed = cur_dir != 0 and cur_dir == self.prev_dir
            cooled = (now - self.last_close_ts) > self.cooldown
            if confirmed and cooled:
                self.pos = cur_dir; self.entry_px = mid; self.open_ts = now
                self.mfe = 0.0; self.mae = 0.0
        else:
            pnl_pct = (mid - self.entry_px) / self.entry_px * self.pos
            self.mfe = max(getattr(self, 'mfe', 0.0), pnl_pct)
            self.mae = min(getattr(self, 'mae', 0.0), pnl_pct)
            held = now - self.open_ts
            reason = ("tp" if pnl_pct >= self.tp_pct
                      else "trail" if (self.trail_arm is not None and self.mfe >= self.trail_arm
                                       and pnl_pct <= self.mfe - self.trail_gap)
                      else "sl" if (self.sl_pct is not None and pnl_pct <= -self.sl_pct)
                      else "time" if held > self.max_hold else None)
            if reason:
                self._close(mid, pnl_pct, held, reason, now)
        self.prev_dir = cur_dir


# 按标的波动率缩放价格类参数（迭代76：各市场单独配置，非通用）
# 实测近6h波幅 ETH0.92% / BTC0.80% / SOL1.21%。SOL波幅1.3x需更宽止损才不被打穿。
_INST_VOL_SCALE = {"ETH-USDT-SWAP": 1.0, "BTC-USDT-SWAP": 0.85, "SOL-USDT-SWAP": 1.3}


def make_strategies():
    strats = [
        Strategy("OBI动量", "obi", "mom", 0.35, 0.0025, 180),
        Strategy("OBI动量·宽止盈", "obi", "mom", 0.35, 0.006, 300),
        Strategy("OBI反转", "obi", "rev", 0.55, 0.0025, 120),
        Strategy("CVD动量", "cvd", "mom", 0.40, 0.0025, 180),
        Strategy("CVD反转", "cvd", "rev", 0.55, 0.003, 150),
        # 小时级波段对（b 修复）：同参数一有 LLM 一没有 → 干净归因 agent 价值
        Strategy("OBI波段(低频对照)", "obi", "mom", 0.45, 0.01, 7200, cooldown=120, sl_pct=0.006,
                 trail_arm=0.0035, trail_gap=0.002),
        AgentStrategy("Agent增强(LLM+OBI)", trail_arm=0.0035, trail_gap=0.002),
        # ---- 迭代1（2026-07-21，292笔教训）：换信号时间尺度 + 非对称止损 ----
        # 教训①止盈0次触发②分钟级信号毛利≈0纯抛硬币③净亏=手续费
        Strategy("趋势动量30m", "mom30m", "mom", 0.4, 0.012, 14400,
                 cooldown=300, sl_pct=0.006, author="agent",
                 trail_arm=0.0035, trail_gap=0.002),   # 时序动量（新信息源）
        Strategy("OBI极端反转波段", "obi", "rev", 0.7, 0.008, 7200,
                 cooldown=300, sl_pct=0.005, author="agent",
                 trail_arm=0.0035, trail_gap=0.002),   # 极端盘口衰竭反转
        Strategy("非对称波段3比1", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.005, author="agent"),   # 小亏大赚出场结构
        # ---- 迭代5（首批平仓教训）：动量2/2止损于窄震荡→动量需要"市场在动"前提 ----
        Strategy("趋势动量·活跃过滤", "mom30m", "mom", 0.4, 0.012, 14400,
                 cooldown=300, sl_pct=0.006, author="agent",
                 min_range=0.005, trail_arm=0.0035, trail_gap=0.002),   # 近1h波幅≥0.5%才入场（体制过滤）
        # ---- 迭代8（非对称首笔完整实证：MFE+0.37%回吐至SL-0.64$）----
        Strategy("非对称·追踪止损", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.005, author="agent",
                 trail_arm=0.0035, trail_gap=0.002),   # 浮盈0.35%武装，回撤0.2%锁定
        # ---- 迭代21（6例峰值0.14-0.29未武装即回落收负）：测试更灵敏的追踪参数 ----
        Strategy("追踪灵敏版", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.005, author="agent",
                 trail_arm=0.0025, trail_gap=0.0012),  # 武装0.25%/回撤0.12%(保本底线)
        # ---- 迭代13（六仓同向团灭教训）：入场信号族单一→引入异族均值回归 ----
        Strategy("均值回归1h", "meanrev1h", "mom", 0.5, 0.008, 7200,
                 cooldown=300, sl_pct=0.005, author="agent",
                 trail_arm=0.0035, trail_gap=0.002),   # 偏离1h均值>0.25%反向回归
        # ---- 迭代39（旗舰滑落教训：两笔逆势开多被止损，MFE仅+0.08/0.10；同期做空全胜）----
        # 根因：OBI陷阱——买单堆盘口但价格照跌。对策：叠加顺势闸门，逆30m动量不开仓。
        # 保留旧「追踪灵敏版」及数据不动，此为其顺势派生版，干净对照顺势过滤的增量价值。
        Strategy("追踪灵敏·顺势", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.005, author="agent",
                 trail_arm=0.0025, trail_gap=0.0012, trend_gate=0.15),  # 逆30m动量>0.06%不开仓
        # ---- 迭代42（OBI陷阱第3轮复现：非对称族多单MFE仅+0.04被SL；跨4策略5+笔确认）----
        # 教训已跨策略反复验证，推广顺势闸门到第二策略族(非对称，无追踪)。
        # 与上4策略凑成2×2因子设计：{追踪止损}×{顺势闸门}，分离各自贡献。保留旧「非对称波段3比1」及数据。
        Strategy("非对称·顺势", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.005, author="agent", trend_gate=0.15),  # 无追踪+顺势闸门
        # ---- 迭代44（盈亏比0.51病根：trail出场平均MFE+0.44%但仅落袋+0.14%，57%利润回吐）----
        # 根因：回撤容忍0.12%太窄，噪声一抖就在低峰值锁死。对策：放宽回撤到0.28%，让赢单跑更远。
        # 单变量对照追踪灵敏·顺势(仅trail_gap 0.0012→0.0028)，隔离"宽回撤"对盈亏比的贡献。
        Strategy("顺势·宽追踪", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.005, author="agent",
                 trail_arm=0.0025, trail_gap=0.0028, trend_gate=0.15),  # 武装0.25%/回撤放宽至0.28%
        # ---- 迭代46（宽追踪首笔证伪固定gap：MFE+0.29%但gap0.28%≈MFE→全回吐-0.11）----
        # 结构性缺陷：固定gap不随行情缩放，小行情等于无保护。正解：按峰值比例回撤。
        # 锁定峰值60%(回撤40%)：MFE+0.29%→出+0.174 / MFE+0.6%→出+0.36，自动缩放。保留旧策略。
        Strategy("顺势·比例追踪", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.005, author="agent",
                 trail_arm=0.0025, trail_frac=0.4, trend_gate=0.15),  # 武装0.25%/锁定峰值60%
        # ---- 迭代51（第一性问题：一笔-0.62SL抹掉4笔盈利；34止损单74%MFE<0.15%从没顺过）----
        # 洞察：这些单紧止损(0.3%)削亏损-0.62→-0.40且不牺牲利润(本就没盈利)，盈亏比0.51→0.71。
        # 合并两个赢家要素：比例追踪(最佳赢单捕获)+紧止损(削主要亏损)。保留顺势·比例追踪对照。
        Strategy("比例·紧止损", "obi", "mom", 0.45, 0.015, 14400,
                 cooldown=300, sl_pct=0.003, author="agent",
                 trail_arm=0.0025, trail_frac=0.4, trend_gate=0.15),  # 止损收紧0.5%→0.3%
        # ---- 迭代55（两独立赢家合成）：均值回归1h(最佳信号,团灭时反向盈利)登顶-0.08；----
        # 比例追踪+紧止损(最佳出场)确认。合成：最佳信号+最佳出场。不加闸门(会扼杀逆势edge)。
        # 保留旧「均值回归1h」(fixed gap/标准止损)作干净对照，隔离出场优化的增量。
        Strategy("均值回归·优化出场", "meanrev1h", "mom", 0.5, 0.008, 7200,
                 cooldown=300, sl_pct=0.003, author="agent",
                 trail_arm=0.0025, trail_frac=0.4),  # 比例追踪60%+紧止损0.3%，无闸门
        # ---- 迭代58（费用墙量化决定性证据）：顶部策略免费毛利全为正，taker费0.10%吃光edge ----
        # 均值回归天然被动成交(极值挂限价entry maker + TP挂限价exit maker)，两腿可拿maker费0.04%往返。
        # 此变体=均值回归·优化出场 仅fee_pct 0.10%→0.04%，直接检验"跨过费用墙能否翻正"。
        # 注：假设maker成交(未建模非成交/滑点)，SL腿实盘为taker，故0.04%偏乐观，作方向性验证。
        Strategy("均值回归·maker", "meanrev1h", "mom", 0.5, 0.008, 7200,
                 cooldown=300, sl_pct=0.003, author="agent",
                 trail_arm=0.0025, trail_frac=0.4, fee_pct=0.00032),  # maker往返0.032%(OKB抵扣后真实)
        # ---- 迭代68（用户指出盈亏不对称）：损失端收紧止损被否(会误杀26-50%赢单，均值回归买跌)。----
        # 转攻盈利端：trail仅落袋峰值30%(net)。提高捕获——锁定峰值75%(frac0.25)而非60%。
        # 单变量对照均值回归·maker(仅trail_frac 0.4→0.25)，检验高捕获能否改善不对称并推正净值。
        Strategy("均值回归·高捕获", "meanrev1h", "mom", 0.5, 0.008, 7200,
                 cooldown=300, sl_pct=0.003, author="agent",
                 trail_arm=0.0025, trail_frac=0.25, fee_pct=0.00032),  # 锁定峰值75%+maker(OKB抵扣0.032%)
    ]
    # 按当前标的波动率缩放"价格距离"类参数（止损/止盈/追踪武装/固定回撤），
    # 使同一策略在各市场都有波动率适配的空间。信号阈值/比例/费率不缩放。
    vs = _INST_VOL_SCALE.get(INST, 1.0)
    if vs != 1.0:
        for s in strats:
            for attr in ("sl_pct", "tp_pct", "trail_arm", "trail_gap"):
                v = getattr(s, attr)
                if v is not None:
                    setattr(s, attr, round(v * vs, 6))
    return strats


def _record_tick(book, feat, trades_summary: float) -> None:
    """行情tick实时落盘（data/ticks/日期.jsonl）：盘口前5档+全部衍生特征。
    这是可回放回测的原始资产（R11：交易所不提供历史L2，自录不可补拍）。"""
    try:
        day = time.strftime("%Y-%m-%d")
        # 多标的：ETH 保持原文件名不变(现有数据兼容)，其他标的加前缀避免碰撞（迭代47）
        prefix = "" if INST == "ETH-USDT-SWAP" else f"{INST}_"
        f = Path("data/ticks") / f"{prefix}{day}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": int(time.time() * 1000),
            "mid": feat["mid"], "obi": round(feat["obi"], 4),
            "cvd": round(trades_summary, 2),
            "mom30m": round(feat.get("mom30m", 0), 4),
            "range1h": round(feat.get("range1h", 0), 5),
            "bids": [[float(p_), float(q)] for p_, q in book.bids[:5]],
            "asks": [[float(p_), float(q)] for p_, q in book.asks[:5]],
        }
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _daily_archive() -> None:
    """每日归档（宪法 V）：把全量状态+策略注册表拷入 data/snapshots/{date}/，每天一次。"""
    day = time.strftime("%Y-%m-%d")
    dest = Path("data/snapshots") / day
    marker = dest / ".done"
    if marker.exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    import shutil
    for src in (PERSIST, Path("data/strategy_registry.jsonl"),
                Path("data/agent_decisions.jsonl")):
        if src.exists():
            shutil.copy2(src, dest / src.name)
    marker.write_text("", encoding="utf-8")


_OVERRIDABLE = ("entry_th", "tp_pct", "sl_pct", "trail_arm", "trail_gap",
                "max_hold", "cooldown", "min_range")


def _apply_overrides(strategies) -> None:
    """人工参数覆盖热生效；变更即重新快照版本（author=human，宪法V留痕）。"""
    if not OVERRIDES.exists():
        return
    try:
        ov = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    from quant.research.strategy_registry import snapshot
    for s_ in strategies:
        params = ov.get(s_.name)
        if not params:
            continue
        changed = False
        for k, v in params.items():
            if k in _OVERRIDABLE and getattr(s_, k, None) != v:
                setattr(s_, k, v)
                changed = True
        if changed:
            s_.version_id = snapshot(s_, author="human")
            print(f"[策略管理] {s_.name} 参数已更新 → 版本 {s_.version_id}", flush=True)


def _read_switches() -> dict:
    """双层开关（迭代78）：全局 strategy_switch.json + 按标的 strategy_switch_<sym>.json，
    取"与"——任一为 False 即停。全局停=所有标的停；面板停=只停当前标的。"""
    def _load(p: Path) -> dict:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return {}
        return {}
    g = _load(SWITCH)
    sym = INST.split("-")[0].lower()
    pi = _load(Path(f"data/strategy_switch_{sym}.json"))
    names = set(g) | set(pi)
    return {n: (g.get(n, True) and pi.get(n, True)) for n in names}


def _read_agent_stance():
    if not AGENT_STANCE.exists():
        return None
    try:
        return json.loads(AGENT_STANCE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def save_persist(strategies, ticks_total, runtime_total):
    """原子写全量状态（临时文件 + rename，防写一半被杀导致损坏）。"""
    payload = {
        "ticks": ticks_total, "runtime_sec": runtime_total,
        "strategies": [s.to_dict() for s in strategies],
    }
    tmp = PERSIST.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PERSIST)


def load_persist(strategies):
    """启动时恢复。返回 (历史ticks, 历史runtime秒)。"""
    if not PERSIST.exists():
        return 0, 0
    try:
        data = json.loads(PERSIST.read_text(encoding="utf-8"))
        by_name = {s["name"]: s for s in data.get("strategies", [])}
        restored = 0
        for s in strategies:
            if s.name in by_name:
                s.load_dict(by_name[s.name]); restored += len(s.trades)
        print(f"[恢复] 从持久化载入 {restored} 笔历史成交，累计 {data.get('ticks',0)} ticks", flush=True)
        return int(data.get("ticks", 0)), int(data.get("runtime_sec", 0))
    except Exception as e:  # noqa: BLE001
        print(f"[恢复失败] {e}，从零开始", flush=True)
        return 0, 0


def main():
    c = OKXClient("x", "x", "x", base_url=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
                  simulated=False)   # 行情用实盘公共源：更准且不受模拟盘限流(50013事故 2026-07-22)
    # 行情源：有透明代理隧道(如 Clash 混合端口 WS_PROXY)则 WS 毫秒级实时，否则 REST 轮询回退。
    # WS_PROXY=http://127.0.0.1:7890 时经 CONNECT 隧道连 wss://ws.okx.com:8443(TLS 透传)。
    ws_proxy = os.environ.get("WS_PROXY")
    if ws_proxy or os.environ.get("OKX_WS_DIRECT"):
        poller = WSPoller(c, INST, f"okx_swap:{INST}", proxy=ws_proxy)
        print(f"[行情] WS 实时模式 (proxy={ws_proxy or '直连'})，冷启动/断线自动 REST 回退", flush=True)
    else:
        poller = RestPoller(c, INST, f"okx_swap:{INST}")
        print("[行情] REST 轮询模式 (未设 WS_PROXY)", flush=True)
    strategies = make_strategies()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    px_hist: list[tuple[float, float]] = []   # (ts, mid) 近1h价格史，供时序动量特征
    ticks_base, runtime_base = load_persist(strategies)   # ★ 恢复历史

    # 策略快照登记（宪法 V）：内容哈希=版本号，人工策略 immutable，成交将关联版本
    from quant.research.strategy_registry import snapshot
    for s in strategies:
        s.version_id = snapshot(s, author=getattr(s, "author", "human"))
    print("策略快照: " + ", ".join(f"{s.name}={s.version_id}" for s in strategies), flush=True)

    started = time.time()
    session_ticks = 0

    print(f"影子对比启动：{len(strategies)}个策略 · 扣费{ROUNDTRIP_FEE_PCT*100:.2f}%往返 · "
          f"每笔名义${NOTIONAL} · 循环{POLL_SEC}s · 持久化={PERSIST}", flush=True)

    while True:
        try:
            book = poller.poll_book(depth=20)
            trades = poller.poll_trades(limit=50)
            mid_now = float(mid_price(book))
            px_hist.append((time.time(), mid_now))
            while px_hist and px_hist[0][0] < time.time() - 3700:
                px_hist.pop(0)

            def _mom(sec: float, scale: float) -> float:
                """时序动量：sec 秒前至今的涨跌幅，按 scale 归一到 [-1,1]。"""
                cutoff = time.time() - sec
                past = next((p for t0, p in px_hist if t0 >= cutoff), None)
                if past is None or past <= 0:
                    return 0.0
                return max(-1.0, min(1.0, (mid_now - past) / past / scale))

            hi = max((p for _, p in px_hist), default=mid_now)
            lo = min((p for _, p in px_hist), default=mid_now)
            avg1h = (sum(p for _, p in px_hist) / len(px_hist)) if px_hist else mid_now
            feat = {
                "range1h": (hi - lo) / mid_now if mid_now else 0.0,
                "meanrev1h": max(-1.0, min(1.0, (avg1h - mid_now) / mid_now / 0.005)),
                "obi": order_book_imbalance(book),
                "cvd": max(-1.0, min(1.0, float(cvd(trades)) / CVD_SCALE)),
                "mom30m": _mom(1800, 0.004),   # 30分钟涨0.4%→满格（292笔教训：换时间尺度）
                "mid": mid_now,
            }
            _record_tick(book, feat, float(cvd(trades)))
            now = time.time()
            switches = _read_switches()
            drain = bool(os.environ.get("SHADOW_DRAIN"))  # 排空模式：持仓走完，不开新仓（迭代74，聚焦ETH）
            for s_ in strategies:
                s_.enabled = False if drain else switches.get(s_.name, True)
            _apply_overrides(strategies)
            # 读 agent 观点，喂给 AgentStrategy（宪法 II：认知层独立进程经文件传递）
            agent_view = _read_agent_stance()
            if agent_view:
                for s in strategies:
                    if isinstance(s, AgentStrategy):
                        age = now - agent_view["ts"] / 1000
                        s.set_agent(agent_view["stance"], agent_view["veto"], age,
                                    agent_view.get("half_life_sec", 3600))

            trades_before = sum(len(s.trades) for s in strategies)
            for s in strategies:
                s.on_tick(feat, now)
            trades_after = sum(len(s.trades) for s in strategies)
            session_ticks += 1
            ticks = ticks_base + session_ticks
            runtime = runtime_base + int(now - started)

            # 持久化：有新成交立即存，否则每 10 ticks 存一次
            if trades_after > trades_before or session_ticks % 10 == 0:
                save_persist(strategies, ticks, runtime)
                _daily_archive()

            # 跨策略成交流（所有策略全部平仓合并，按时间倒序）
            recent_all = []
            for s in strategies:
                for t in s.trades:
                    recent_all.append({**t, "strategy": s.name})
            recent_all.sort(key=lambda x: x["ts"], reverse=True)
            total_trades = len(recent_all)

            # 进行中的交易（未平仓，实时浮动盈亏）
            mid = feat["mid"]
            open_trades = []
            for s in strategies:
                if s.pos == 0:
                    continue
                upnl_pct = (mid - s.entry_px) / s.entry_px * s.pos
                # 若此刻平仓的净盈亏（要扣往返费）
                net_if_close = NOTIONAL * (upnl_pct - ROUNDTRIP_FEE_PCT)
                gross_now = NOTIONAL * upnl_pct
                if s.pos > 0:
                    buy_px, sell_px = round(s.entry_px, 2), round(mid, 2)
                else:
                    sell_px, buy_px = round(s.entry_px, 2), round(mid, 2)
                open_trades.append({
                    "strategy": s.name, "dir": "多" if s.pos > 0 else "空",
                    "qty": round(NOTIONAL / s.entry_px, 5),        # 买了多少(ETH)
                    "invested": NOTIONAL,                           # 投入资金(USDT)
                    "cur_value": round(NOTIONAL * (1 + upnl_pct), 3),  # 现在价值(USDT,含方向)
                    "entry": round(s.entry_px, 2), "cur": round(mid, 2),
                    "buy_px": buy_px, "sell_px": sell_px,
                    "open_ms": int(s.open_ts * 1000),
                    "hold": int(now - s.open_ts),
                    "upnl_pct": round(upnl_pct * 100, 4),
                    "gross_usd": round(gross_now, 4),
                    "net_if_close": round(net_if_close, 4),
                    "tp_target": round(s.tp_pct * 100, 3),
                })
            open_trades.sort(key=lambda x: x["net_if_close"], reverse=True)

            snapshot = {
                "inst": INST, "ts": int(now * 1000), "ticks": ticks,
                "runtime_sec": runtime,
                "fee_roundtrip_pct": ROUNDTRIP_FEE_PCT * 100, "notional": NOTIONAL,
                "mid": feat["mid"], "obi": round(feat["obi"], 3), "cvd_norm": round(feat["cvd"], 3),
                "strategies": sorted([s.stats() for s in strategies],
                                     key=lambda x: x["net_usd"], reverse=True),
                "total_trades": total_trades,   # 全部成交经 /api/trades 分页取，快照只带总数
                "open_trades": open_trades,
                "agent": _read_agent_stance(),
            }
            OUT.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {type(e).__name__}: {str(e)[:60]}", flush=True)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
