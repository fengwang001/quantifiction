"""Agent 认知层运行器（独立进程，PRD §6 架构）。

每 DELIB_INTERVAL 秒：读真实 OKX 衍生品/盘口数据 → gpt-5.4 多空研究员辩论
→ 交易员裁决出 stance/conviction/veto → 校验 → 写 data/agent_stance.json。
全量决策（含完整 prompt/辩论/输出）追加到 data/agent_decisions.jsonl（可回放，宪法 V）。

★ 输出仅方向观点，不产生订单；量化时机 + 融合 + 风控在下游（宪法 II）。

运行：
    uv run python -m quant.cognitive.agent_runner
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from pathlib import Path

from quant.cognitive.llm_client import GrsaiClient, HttpxTransport, ModelPricing, cost_rmb
from quant.cognitive.nodes import _extract_json
from quant.cognitive.validator import validate
from quant.markets.okx_swap.okx_client import OKXClient
from quant.markets.okx_swap.signals import mid_price, order_book_imbalance, spread_bps
from quant.markets.okx_swap.ws_feed import RestPoller

INST = "ETH-USDT-SWAP"
CCY = "ETH"
MODEL = os.getenv("GRSAI_MODEL", "gemini-3.1-pro")  # gpt-5.4 在此供应商失败率高，改用 gemini


OVERRIDE = Path("data/agent_config.json")   # 页面写入的运行时覆盖（最高优先）
TRIGGER = Path("data/agent_trigger.json")   # 页面"立即执行"信号
STANCE_OUT = Path("data/agent_stance.json")


def _trigger_ts() -> int:
    if TRIGGER.exists():
        try:
            return int(json.loads(TRIGGER.read_text(encoding="utf-8"))["ts"])
        except Exception:  # noqa: BLE001
            return 0
    return 0


def current_interval() -> int:
    """agent 辩论间隔（秒），每轮重读——页面改了无需重启 agent。
    优先级：页面覆盖 > 环境变量 AGENT_INTERVAL > config/cognitive.yaml > 默认900。
    """
    if OVERRIDE.exists():
        try:
            return max(120, int(json.loads(OVERRIDE.read_text(encoding="utf-8"))["interval_sec"]))
        except Exception:  # noqa: BLE001
            pass
    if os.getenv("AGENT_INTERVAL"):
        return int(os.environ["AGENT_INTERVAL"])
    try:
        import yaml
        cfg = yaml.safe_load(Path("config/cognitive.yaml").read_text(encoding="utf-8"))
        return int(cfg["cognitive"]["provider"]["agent_interval_sec"])
    except Exception:  # noqa: BLE001
        return 900
DECISIONS_LOG = Path("data/agent_decisions.jsonl")
BUDGET_FILE = Path("data/agent_budget.json")   # 日支出持久化（跨重启累计）


def _load_provider_cfg() -> tuple[ModelPricing, Decimal]:
    """价格/汇率从 config 读，不写死（R7b 决策）。返回 (当前模型定价, usd_rmb_rate)。"""
    import yaml
    cfg = yaml.safe_load(Path("config/cognitive.yaml").read_text(encoding="utf-8"))
    prov = cfg["cognitive"]["provider"]
    p = prov["pricing"][MODEL]
    return (ModelPricing(Decimal(str(p["input_per_m"])), Decimal(str(p["output_per_m"]))),
            Decimal(str(prov.get("usd_rmb_rate", 7.2))))


PRICING, USD_RMB = _load_provider_cfg()


def _budget_spent_today() -> Decimal:
    """今日已花（USD）。跨天自动清零。"""
    if BUDGET_FILE.exists():
        try:
            d = json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
            if d.get("date") == time.strftime("%Y-%m-%d"):
                return Decimal(str(d["spent_usd"]))
        except Exception:  # noqa: BLE001
            pass
    return Decimal("0")


def _budget_charge(cost_usd: Decimal) -> None:
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUDGET_FILE.write_text(json.dumps({
        "date": time.strftime("%Y-%m-%d"),
        "spent_usd": float(_budget_spent_today() + cost_usd),
    }), encoding="utf-8")


def gather_context(okx: OKXClient, poller: RestPoller) -> dict:
    """采集真实市场上下文供 agent 分析。"""
    ctx: dict = {}
    tk = okx.request("GET", "/api/v5/market/ticker", {"instId": INST})[0]
    ctx["last"] = float(tk["last"])
    o, h, l = float(tk["open24h"]), float(tk["high24h"]), float(tk["low24h"])
    ctx["chg24h_pct"] = round((ctx["last"] - o) / o * 100, 2)
    ctx["high24h"], ctx["low24h"] = h, l
    ctx["vol24h_usd"] = round(float(tk.get("volCcy24h", 0)) * ctx["last"] / 1e6, 1)  # 百万USD

    try:
        fr = okx.request("GET", "/api/v5/public/funding-rate", {"instId": INST})[0]
        ctx["funding_rate"] = round(float(fr["fundingRate"]) * 100, 5)
    except Exception:  # noqa: BLE001
        ctx["funding_rate"] = None
    try:
        oi = okx.request("GET", "/api/v5/public/open-interest", {"instId": INST})[0]
        ctx["open_interest"] = round(float(oi["oiCcy"]), 0)
    except Exception:  # noqa: BLE001
        ctx["open_interest"] = None
    try:
        ls = okx.request("GET", "/api/v5/rubik/stat/contracts/long-short-account-ratio",
                         {"ccy": CCY, "period": "5m"})
        ctx["long_short_ratio"] = round(float(ls[0][1]), 3) if ls else None
    except Exception:  # noqa: BLE001
        ctx["long_short_ratio"] = None

    book = poller.poll_book(depth=20)
    ctx["obi"] = round(order_book_imbalance(book), 3)
    ctx["spread_bps"] = round(spread_bps(book), 2)
    ctx["mid"] = float(mid_price(book))

    # ---- 时间序列（a 修复：不再只给一帧快照）----
    def _kline_summary(bar: str, n: int) -> str:
        rows = okx.request("GET", "/api/v5/market/candles",
                           {"instId": INST, "bar": bar, "limit": str(n)})
        closes = [float(r[4]) for r in reversed(rows)]   # 转时间正序
        highs = [float(r[2]) for r in rows]
        lows = [float(r[3]) for r in rows]
        chg = (closes[-1] - closes[0]) / closes[0] * 100
        # 近段动能：后1/3均值 vs 前1/3均值
        k = max(1, len(closes) // 3)
        mom = (sum(closes[-k:]) / k - sum(closes[:k]) / k) / closes[0] * 100
        return (f"{bar}x{len(closes)}: 区间{chg:+.2f}% 高{max(highs)} 低{min(lows)} "
                f"近段动能{mom:+.2f}% 末3收[{closes[-3]:.1f},{closes[-2]:.1f},{closes[-1]:.1f}]")

    for bar, n in (("5m", 24), ("1H", 24), ("4H", 18), ("1D", 30)):
        try:
            ctx[f"k_{bar}"] = _kline_summary(bar, n)
        except Exception:  # noqa: BLE001
            ctx[f"k_{bar}"] = None

    try:  # 资金费率近 8 期走向
        frs = okx.request("GET", "/api/v5/public/funding-rate-history",
                          {"instId": INST, "limit": "8"})
        vals = [round(float(r["fundingRate"]) * 100, 5) for r in reversed(frs)]
        ctx["funding_hist"] = vals
    except Exception:  # noqa: BLE001
        ctx["funding_hist"] = None

    try:  # 持仓量近 24×5m 变化
        ois = okx.request("GET", "/api/v5/rubik/stat/contracts/open-interest-volume",
                          {"ccy": CCY, "period": "5m"})
        if ois and len(ois) >= 2:
            newest, oldest = float(ois[0][1]), float(ois[min(23, len(ois) - 1)][1])
            ctx["oi_chg_2h_pct"] = round((newest - oldest) / oldest * 100, 2)
    except Exception:  # noqa: BLE001
        ctx["oi_chg_2h_pct"] = None

    # ---- 第7类：新闻标题 + 恐惧贪婪指数（缓存10分钟，失败静默降级）----
    try:
        from quant.cognitive.datasource.news_feed import get_news_context
        news = get_news_context()
        ctx["fng"] = news.get("fng")
        ctx["news_titles"] = news.get("titles", [])
    except Exception:  # noqa: BLE001
        ctx["fng"] = None
        ctx["news_titles"] = []

    # ---- 第8类：资金面（DefiLlama TVL/稳定币，缓存1h，失败降级）----
    try:
        from quant.cognitive.datasource.funding_flows import get_funding_flows
        ctx["flows"] = get_funding_flows()
    except Exception:  # noqa: BLE001
        ctx["flows"] = None

    # ---- 第9类：宏观/美联储（DXY、美债10Y、FOMC日历、宏观新闻，缓存30min）----
    try:
        from quant.cognitive.datasource.macro_fed import get_macro
        ctx["macro"] = get_macro()
    except Exception:  # noqa: BLE001
        ctx["macro"] = None
    return ctx


def _ctx_text(ctx: dict) -> str:
    return (
        f"标的 {INST}\n现价 {ctx['last']}（24h {ctx['chg24h_pct']:+}%，高{ctx['high24h']} 低{ctx['low24h']}）\n"
        f"24h成交额 {ctx['vol24h_usd']}百万USD\n"
        f"资金费率 {ctx['funding_rate']}%（正=多头付费/拥挤，负=空头拥挤）\n"
        f"持仓量 {ctx['open_interest']} {CCY}\n"
        f"多空账户比 {ctx['long_short_ratio']}（>1 多头账户多）\n"
        f"盘口失衡OBI {ctx['obi']}（+买压/-卖压）  点差 {ctx['spread_bps']}bp\n"
        f"K线 {ctx.get('k_5m')}\nK线 {ctx.get('k_1H')}\nK线 {ctx.get('k_4H')}\nK线 {ctx.get('k_1D')}\n"
        f"资金费率近8期(%) {ctx.get('funding_hist')}\n"
        f"持仓量2h变化 {ctx.get('oi_chg_2h_pct')}%（正=增仓）"
        + _news_text(ctx)
    )


def _news_text(ctx: dict) -> str:
    """第7类：恐惧贪婪指数 + 新闻标题（缺失时返回空串，不阻塞辩论）。"""
    parts = []
    fng = ctx.get("fng")
    if fng:
        arrow = "↑" if fng["value"] > fng["prev"] else "↓" if fng["value"] < fng["prev"] else "="
        parts.append(f"恐惧贪婪指数 {fng['value']}({fng['label']}) 前值{fng['prev']}{arrow}"
                     "（<25极恐/>75极贪，极端常为反指）")
    titles = ctx.get("news_titles") or []
    if titles:
        parts.append("近期新闻标题(英文，自行判断相关性与情绪)：\n  " + "\n  ".join(titles))
    fl = ctx.get("flows")
    if fl:
        parts.append(
            f"资金面：ETH链上TVL ${fl['eth_tvl_b']}B（1d {fl['tvl_chg_1d']:+}% / 7d {fl['tvl_chg_7d']:+}%）；"
            f"稳定币总市值 ${fl['stable_b']}B（1d {fl['stable_chg_1d']:+}% / 7d {fl['stable_chg_7d']:+}%，增发=场内弹药增加）"
        )
    m = ctx.get("macro")
    if m:
        seg = []
        if m.get("dxy"):
            seg.append(f"美元指数DXY {m['dxy']['last']}（5日{m['dxy']['chg_5d']:+}%，走强=加密流动性逆风）")
        if m.get("us10y"):
            seg.append(f"美债10Y收益率 {m['us10y']['last']}%（5日{m['us10y']['chg_5d']:+}%，上行=收紧）")
        if m.get("fomc", {}).get("days") is not None:
            seg.append(f"距下次FOMC议息 {m['fomc']['days']}天({m['fomc']['next']})——临近时政策不确定性放大波动")
        if seg:
            parts.append("宏观/美联储：" + "；".join(seg))
        if m.get("titles"):
            parts.append("宏观新闻标题：\n  " + "\n  ".join(m["titles"]))
    return ("\n" + "\n".join(parts)) if parts else ""


def _past_views_text(cur_price: float) -> str:
    """近6次判断记录+事后验证（自我校准）。判断对错=stance方向与其后价格实际走向是否一致。"""
    if not DECISIONS_LOG.exists():
        return ""
    try:
        lines = DECISIONS_LOG.read_text(encoding="utf-8").strip().split("\n")[-6:]
        rows = []
        for ln in lines:
            d = json.loads(ln)
            then_px = d.get("context", {}).get("last")
            if not then_px:
                continue
            move = (cur_price - then_px) / then_px * 100
            st = d.get("stance", 0)
            if abs(move) < 0.15:
                verdict = "中性(价未动)"
            elif (st > 0.05 and move > 0) or (st < -0.05 and move < 0):
                verdict = "√方向对"
            elif abs(st) <= 0.05:
                verdict = "当时中性"
            else:
                verdict = "×方向错"
            ago = int((time.time() * 1000 - d["ts"]) / 60000)
            rows.append(f"  {ago}分钟前 stance={st:+.2f} → 其后价格{move:+.2f}% {verdict}"
                        f"｜当时理由:{d.get('reasoning','')[:42]}")
        if not rows:
            return ""
        return ("\n你此前的判断记录（自我校准，勿只看当刻快照）：\n" + "\n".join(rows))
    except Exception:  # noqa: BLE001
        return ""


def _complete_retry(llm: GrsaiClient, messages, retries: int = 8):
    """带退避重试：grsai 并发限制低、gpt-5.4 慢，需耐心重试。"""
    delay = 15
    last = None
    for i in range(retries):
        try:
            return llm.complete(MODEL, messages)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  [retry {i+1}/{retries}] {str(e)[:55]}，{delay}s后重试", flush=True)
            time.sleep(delay)
            delay = min(int(delay * 1.6), 120)
    raise last  # type: ignore[misc]


def deliberate(llm: GrsaiClient, ctx: dict) -> dict:
    """单次调用完成多空权衡 + 裁决（grsai 并发限制低，合并为一次调用）。

    要求模型内部先分析多空双方，再给结论，bull/bear 摘要放进 reasoning。
    """
    ctxt = _ctx_text(ctx) + _past_views_text(ctx["last"])
    prompt = (
        "你是资深加密交易分析师。请先在心里分别站在多头和空头立场分析下列数据，"
        "再综合给出未来数小时的方向裁决。"
        "分析必须结合宏观面：美联储政策路径（FOMC临近度、利率预期）、美元指数与美债收益率"
        "对加密流动性的传导（美元/收益率走强通常压制加密），把宏观作为方向判断的顶层背景，"
        "微观盘口作为时机参考。判断总体趋势时必须综合全部周期（尤其日线大级别）与历史演变，"
        "不可只依据当刻快照。同时保持判断连贯性：参考下方你此前的判断记录，"
        "无实质新证据时不要频繁翻转方向；若连续判断方向错误，须显式反思并修正偏差。\n"
        '仅输出JSON：{"symbol_uid":"okx_swap:' + INST + '",'
        '"stance":-1到1的方向偏好(正=看多),"conviction":0到0.8的信心,'
        '"veto":是否建议此刻不宜交易(bool),"half_life_sec":观点有效期秒数(如3600),'
        '"bull":"多头关键理由一句","bear":"空头关键理由一句",'
        '"reasoning":"裁决简述","key_risks":["至少两条风险"]}。不要输出JSON以外内容。'
        f"\n\n数据：\n{ctxt}"
    )
    r = _complete_retry(llm, [{"role": "user", "content": prompt}])
    verdict = _extract_json(r.content)
    verdict.setdefault("symbol_uid", f"okx_swap:{INST}")
    return {
        "verdict": verdict,
        "bull": verdict.get("bull", ""), "bear": verdict.get("bear", ""),
        "trader_raw": r.content, "prompts": {"combined": prompt},
        "cost_rmb": float(cost_rmb(r, PRICING)), "tokens": r.total_tokens,
    }


def main() -> None:
    okx = OKXClient("x", "x", "x", base_url=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
                    simulated=False)  # 同上：行情走实盘公共源
    poller = RestPoller(okx, INST, f"okx_swap:{INST}")
    llm = GrsaiClient(os.environ["GRSAI_API_KEY"],
                      base_url=os.environ.get("GRSAI_BASE_URL", "https://grsaiapi.com"),
                      transport=HttpxTransport(timeout=180.0))  # gpt-5.4 推理慢，放宽超时
    STANCE_OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"Agent 运行器启动：{MODEL} 每{current_interval()}s 一次多空辩论（页面可调）", flush=True)

    from quant.cognitive.budget import DAILY_CAP   # 宪法 $1.20/天硬上限

    while True:
        interval = current_interval()   # 每轮重读，页面改了即刻生效
        # 预算硬闸（宪法）：超支则本轮跳过辩论 → 下游因观点超龄自然降级纯量化
        spent = _budget_spent_today()
        if spent >= DAILY_CAP:
            print(f"{time.strftime('%H:%M:%S')} 日预算已用 ${spent:.3f} ≥ ${DAILY_CAP}，"
                  f"跳过辩论（降级纯量化），{interval}s 后复查", flush=True)
            time.sleep(interval)
            continue
        try:
            ctx = gather_context(okx, poller)
            print(f"{time.strftime('%H:%M:%S')} 辩论中… OBI={ctx['obi']} 资金费率={ctx['funding_rate']}% "
                  f"24h={ctx['chg24h_pct']}%", flush=True)
            out = deliberate(llm, ctx)
            outcome = validate(out["verdict"])
            sig = outcome.signal
            now = int(time.time() * 1000)

            stance = {
                "ts": now, "model": MODEL, "context": ctx,
                "interval_sec": current_interval(),   # 写盘时实读（轮中改频率立即反映）
                "valid": sig is not None,
                "stance": sig.stance if sig else 0.0,
                "conviction": sig.conviction if sig else 0.0,
                "veto": sig.veto if sig else False,
                "half_life_sec": sig.half_life_sec if sig else 0,
                "reasoning": out["verdict"].get("reasoning", ""),
                "key_risks": out["verdict"].get("key_risks", []),
                "cost_rmb": out["cost_rmb"], "tokens": out["tokens"],
                "valid_detail": "" if sig else outcome.reason,
            }
            _budget_charge(Decimal(str(out["cost_rmb"])) / USD_RMB)   # 计入日预算（USD）
            STANCE_OUT.write_text(json.dumps(stance, ensure_ascii=False), encoding="utf-8")

            # 全量决策留档（可回放，宪法 V）
            with DECISIONS_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**stance, "bull": out["bull"], "bear": out["bear"],
                                    "trader_raw": out["trader_raw"]}, ensure_ascii=False) + "\n")
            v = stance
            print(f"  → stance={v['stance']:+.2f} conviction={v['conviction']:.2f} "
                  f"veto={v['veto']} 成本RMB{v['cost_rmb']:.3f} ({v['tokens']}tok) "
                  f"{'✓' if v['valid'] else '✗'+v['valid_detail']}", flush=True)
            # 可被打断的等待：①页面「立即执行」 ②价格急动≥1.5%（c 事件触发，压滞后）
            last_trig = _trigger_ts()
            base_px = ctx["last"]
            waited = 0
            while waited < current_interval():
                time.sleep(2)
                waited += 2
                if _trigger_ts() > last_trig:
                    print("  → 收到「立即执行」，提前辩论", flush=True)
                    break
                if waited % 30 == 0:
                    try:
                        px = float(okx.request("GET", "/api/v5/market/ticker",
                                               {"instId": INST})[0]["last"])
                        move = abs(px - base_px) / base_px
                        if move >= 0.015:
                            print(f"  → 价格急动 {move*100:+.2f}%（{base_px}→{px}），事件触发辩论",
                                  flush=True)
                            break
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 辩论失败: {type(e).__name__}: {str(e)[:70]}，120s后重试", flush=True)
            time.sleep(120)   # 失败后短间隔重试，不等满 DELIB_INTERVAL


if __name__ == "__main__":
    main()
