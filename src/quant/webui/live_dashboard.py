"""影子模式多策略对比看板（宪法 VI：先验证后加码）。

读 shadow_engine 写的 data/shadow_state.json，展示各策略扣费后净收益/胜率/夏普/净值曲线。
★ 纯只读，无任何交易；数据来自影子引擎（零真金风险）。

运行：
    uv run uvicorn quant.webui.live_dashboard:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

STATE = Path(os.getenv("SHADOW_OUT", "data/shadow_state.json"))
PERSIST = Path(os.getenv("SHADOW_PERSIST", "data/shadow_persist.json"))

# 多标的：按 inst 参数解析对应数据文件（ETH 用默认名，BTC/SOL 加后缀）
_INSTS = {"ETH": "", "BTC": "_btc", "SOL": "_sol"}


def _state_file(inst: str) -> Path:
    sfx = _INSTS.get((inst or "ETH").upper(), "")
    return Path(f"data/shadow_state{sfx}.json")


def _persist_file(inst: str) -> Path:
    sfx = _INSTS.get((inst or "ETH").upper(), "")
    return Path(f"data/shadow_persist{sfx}.json")

app = FastAPI(title="Quantifiction 影子策略对比")


AGENT_CFG = Path("data/agent_config.json")


AGENT_TRIGGER = Path("data/agent_trigger.json")
SWITCH = Path("data/strategy_switch.json")


@app.post("/api/agent/interval")
def set_agent_interval(sec: int) -> JSONResponse:
    """页面设置 agent 辩论间隔（秒）。写覆盖文件，agent 每轮重读、无需重启。"""
    sec = max(120, min(7200, int(sec)))   # 夹在 2分钟~2小时
    AGENT_CFG.parent.mkdir(parents=True, exist_ok=True)
    AGENT_CFG.write_text(json.dumps({"interval_sec": sec}), encoding="utf-8")
    return JSONResponse({"ok": True, "interval_sec": sec})


@app.post("/api/agent/run-now")
def agent_run_now() -> JSONResponse:
    """页面「立即执行」：写触发信号，agent 在当前等待中会尽快提前辩论。"""
    import time as _t
    AGENT_TRIGGER.parent.mkdir(parents=True, exist_ok=True)
    AGENT_TRIGGER.write_text(json.dumps({"ts": int(_t.time() * 1000)}), encoding="utf-8")
    return JSONResponse({"ok": True})


def _switch_path(inst: str, glob: bool) -> Path:
    """glob=True→全局 strategy_switch.json；否则按标的 strategy_switch_<sym>.json。"""
    if glob:
        return SWITCH
    sym = _INSTS.get((inst or "ETH").upper(), "").lstrip("_") or "eth"
    return Path(f"data/strategy_switch_{sym}.json")


@app.post("/api/strategy/toggle")
def toggle_strategy(name: str, on: bool, inst: str = "ETH",
                    scope: str = "inst") -> JSONResponse:
    """策略开关：off=只出不进（持仓走完），数据全保留。引擎每tick热读。
    scope=inst→只停当前标的(面板按钮)；scope=global→所有标的(策略管理)。"""
    p = _switch_path(inst, scope == "global")
    sw = {}
    if p.exists():
        try:
            sw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            sw = {}
    sw[name] = bool(on)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sw, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True, "name": name, "enabled": bool(on),
                         "scope": scope, "inst": (inst or "ETH").upper()})


OVERRIDES = Path("data/strategy_overrides.json")

# 策略管理模块的参数校验规则（服务端权威）
_PARAM_RULES = {
    "entry_th":  {"type": float, "min": 0.05,   "max": 0.95,  "null": False, "label": "入场阈值"},
    "tp_pct":    {"type": float, "min": 0.001,  "max": 0.05,  "null": False, "label": "止盈"},
    "sl_pct":    {"type": float, "min": 0.001,  "max": 0.05,  "null": True,  "label": "止损"},
    "trail_arm": {"type": float, "min": 0.0005, "max": 0.03,  "null": True,  "label": "追踪武装"},
    "trail_gap": {"type": float, "min": 0.0003, "max": 0.02,  "null": True,  "label": "追踪回撤"},
    "max_hold":  {"type": int,   "min": 60,     "max": 86400, "null": False, "label": "最大持仓秒"},
    "cooldown":  {"type": int,   "min": 0,      "max": 3600,  "null": False, "label": "冷却秒"},
    "min_range": {"type": float, "min": 0.0005, "max": 0.05,  "null": True,  "label": "体制过滤"},
}


def _validate_params(params: dict) -> list[str]:
    errs = []
    for k, v in params.items():
        rule = _PARAM_RULES.get(k)
        if rule is None:
            errs.append(f"未知参数 {k}（不可修改）")
            continue
        if v is None:
            if not rule["null"]:
                errs.append(f"{rule['label']} 不允许为空")
            continue
        try:
            v = rule["type"](v)
        except (TypeError, ValueError):
            errs.append(f"{rule['label']} 类型错误（需{rule['type'].__name__}）")
            continue
        if not (rule["min"] <= v <= rule["max"]):
            errs.append(f"{rule['label']} 超范围（{rule['min']}~{rule['max']}，收到{v}）")
    ta, tg = params.get("trail_arm"), params.get("trail_gap")
    if (ta is None) != (tg is None):
        errs.append("追踪武装与追踪回撤须同时设置或同时留空")
    elif ta is not None and tg is not None and float(tg) >= float(ta):
        errs.append(f"追踪回撤({tg})必须小于武装线({ta})，否则武装即触发")
    sl, tp = params.get("sl_pct"), params.get("tp_pct")
    if sl is not None and tp is not None and float(sl) > float(tp) * 2:
        errs.append("止损大于止盈2倍：盈亏比严重不利，请复核")
    return errs


@app.post("/api/strategy/update")
def update_strategy(payload: dict) -> JSONResponse:
    """策略管理模块专用：人工修改策略参数。服务端校验 → 写覆盖文件 → 引擎3s内热生效并重新快照版本。"""
    name = payload.get("name")
    params = payload.get("params", {})
    if not name or not isinstance(params, dict) or not params:
        return JSONResponse({"ok": False, "errors": ["缺少 name 或 params"]})
    if PERSIST.exists():
        known = {x["name"] for x in json.loads(PERSIST.read_text(encoding="utf-8")).get("strategies", [])}
        if name not in known:
            return JSONResponse({"ok": False, "errors": [f"策略不存在：{name}"]})
    errs = _validate_params(params)
    if errs:
        return JSONResponse({"ok": False, "errors": errs})
    ov = {}
    if OVERRIDES.exists():
        try:
            ov = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        except Exception:
            ov = {}
    cleaned = {}
    for k, v in params.items():
        cleaned[k] = None if v is None else _PARAM_RULES[k]["type"](v)
    ov.setdefault(name, {}).update(cleaned)
    OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES.write_text(json.dumps(ov, ensure_ascii=False, indent=1), encoding="utf-8")
    return JSONResponse({"ok": True, "applied": cleaned,
                         "note": "已保存，引擎3秒内热生效并生成新版本号"})


@app.get("/api/strategy/detail")
def strategy_detail(name: str, inst: str = "ETH") -> JSONResponse:
    """单策略详情：全部成交（含买卖价/时间/MFE）+ 按平仓时间重建的净值时间线。"""
    pf = _persist_file(inst)
    if not pf.exists():
        return JSONResponse({"ok": False})
    data = json.loads(pf.read_text(encoding="utf-8"))
    st = next((x for x in data.get("strategies", []) if x["name"] == name), None)
    if st is None:
        return JSONResponse({"ok": False})
    trades = sorted(st.get("trades", []), key=lambda t: t.get("ts", 0))
    points, eq = [], 0.0
    for t in trades:
        eq = round(eq + t.get("net_usd", 0.0), 4)
        points.append({"ts": t.get("ts", 0), "eq": eq})
    wins = sum(1 for t in trades if t.get("net_usd", 0) > 0)
    # 策略定义与版本历史（strategy_registry.jsonl）
    versions = []
    reg = Path("data/strategy_registry.jsonl")
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r["definition"]["name"] == name:
                    versions.append({"version_id": r["version_id"], "ts": r["ts"],
                                     "author": r["author"], "immutable": r.get("immutable", False),
                                     "definition": r["definition"]})
            except Exception:
                continue
    versions.sort(key=lambda v: v["ts"])
    # 有效定义 = 注册表最新 + 当前覆盖（人工修改可能已回退到旧版本内容）
    eff = dict(versions[-1]["definition"]) if versions else None
    if eff is not None and OVERRIDES.exists():
        try:
            ovp = json.loads(OVERRIDES.read_text(encoding="utf-8")).get(name, {})
            for k in ("entry_th", "tp_pct", "sl_pct", "max_hold", "cooldown", "min_range"):
                if k in ovp:
                    if ovp[k] is None:
                        eff.pop(k, None)
                    else:
                        eff[k] = ovp[k]
            if "trail_arm" in ovp or "trail_gap" in ovp:
                ta = ovp.get("trail_arm", (eff.get("trail") or [None, None])[0])
                tg = ovp.get("trail_gap", (eff.get("trail") or [None, None])[1])
                if ta is None or tg is None:
                    eff.pop("trail", None)
                else:
                    eff["trail"] = [ta, tg]
        except Exception:
            pass
    cur_vid = next((v["version_id"] for v in versions if v["definition"] == eff), None)
    return JSONResponse({
        "ok": True, "name": name, "n": len(trades), "wins": wins,
        "definition": eff,
        "current_version": cur_vid,
        "author": versions[-1]["author"] if versions else None,
        "versions": versions,
        "net": round(sum(t.get("net_usd", 0) for t in trades), 3),
        "points": points,
        "trades": trades[::-1],   # 表格用倒序（最新在前）
    })


@app.get("/api/trades")
def trades_page(offset: int = 0, limit: int = 50, inst: str = "ETH") -> JSONResponse:
    """分页返回全部成交（下滑加载更多）。按 inst 标的读对应持久化，按时间倒序。"""
    pf = _persist_file(inst)
    if not pf.exists():
        return JSONResponse({"trades": [], "total": 0})
    data = json.loads(pf.read_text(encoding="utf-8"))
    allt = []
    for s in data.get("strategies", []):
        for t in s.get("trades", []):
            allt.append({**t, "strategy": s["name"]})
    allt.sort(key=lambda x: x.get("ts", 0), reverse=True)
    # 该标的全部成交的总体盈亏汇总
    net = sum(t.get("net_usd", 0.0) for t in allt)
    gross = sum(t.get("net_usd", 0.0) + t.get("fee_usd", 0.0) for t in allt)
    fee = sum(t.get("fee_usd", 0.0) for t in allt)
    wins = sum(1 for t in allt if t.get("net_usd", 0.0) > 0)
    n = len(allt)
    return JSONResponse({
        "trades": allt[offset:offset + limit], "total": n,
        "summary": {
            "net_usd": round(net, 2), "gross_usd": round(gross, 2),
            "fee_usd": round(fee, 2), "wins": wins,
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
        },
    })


def _total_portfolio() -> dict:
    """总盘资金：跨全部持久化文件(ETH/BTC/SOL)聚合所有策略成交，
    按时间累计成一条组合净值曲线。这是整个影子实验的总资金状况。"""
    import glob
    files = ["data/shadow_persist.json"] + glob.glob("data/shadow_persist_*.json")
    seen = set()
    allt = []
    strat_names = set()
    for fp in files:
        if fp in seen or not Path(fp).exists():
            continue
        seen.add(fp)
        try:
            d = json.loads(Path(fp).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for s in d.get("strategies", []):
            strat_names.add(s.get("name", ""))
            for t in s.get("trades", []):
                allt.append((int(t.get("ts", 0)), float(t.get("net_usd", 0.0))))
    allt.sort(key=lambda x: x[0])
    # 组合累计净值曲线（下采样到≤400点，避免过大）
    cum = 0.0
    curve = []
    for ts, net in allt:
        cum += net
        curve.append([ts, round(cum, 3)])
    step = max(1, len(curve) // 400)
    curve_ds = curve[::step]
    if curve and curve_ds[-1] != curve[-1]:
        curve_ds.append(curve[-1])
    wins = sum(1 for _, n in allt if n > 0)
    peak = 0.0
    mdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    realized = cum   # 已平仓累计净盈亏

    # 浮动盈亏：读各标的实时快照的持仓，按当前价 mark-to-market（net_if_close 含平仓费）
    state_files = ["data/shadow_state.json", "data/shadow_state_btc.json",
                   "data/shadow_state_sol.json"]
    unrealized = 0.0
    n_open = 0
    stale = False
    now_ms = time.time() * 1000
    for sf in state_files:
        if not Path(sf).exists():
            continue
        try:
            st = json.loads(Path(sf).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if now_ms - st.get("ts", 0) > 30000:   # 快照超30s视为陈旧
            stale = True
        for ot in st.get("open_trades", []):
            unrealized += float(ot.get("net_if_close", ot.get("gross_usd", 0.0)))
            n_open += 1

    total_pnl = realized + unrealized   # 总盈亏 = 已实现 + 浮动
    # 资金账户视角：每策略名义 $100 子账户，总盘起始 = 策略数 × 100
    notional = 100.0
    n_strat = len(strat_names)
    start_cap = n_strat * notional
    cur_cap = start_cap + total_pnl
    ret_pct = (total_pnl / start_cap * 100) if start_cap else 0.0
    mdd_pct = (mdd / start_cap * 100) if start_cap else 0.0
    return {
        "net_usd": round(total_pnl, 2),          # 总盈亏(含浮动)——曲线/资金以此为准
        "realized_usd": round(realized, 2),      # 已平仓
        "unrealized_usd": round(unrealized, 3),  # 浮动(实时随价格变)
        "open_positions": n_open,
        "stale": stale,
        "trades": len(allt),
        "win_rate": round(wins / len(allt) * 100, 1) if allt else 0.0,
        "max_dd": round(mdd, 2),
        "curve": curve_ds,
        "instruments": len(seen),
        "strat": n_strat,
        "start_capital": round(start_cap, 2),
        "current_capital": round(cur_cap, 2),
        "return_pct": round(ret_pct, 2),
        "max_dd_pct": round(mdd_pct, 2),
    }


@app.get("/api/shadow")
def shadow(inst: str = "ETH") -> JSONResponse:
    sf = _state_file(inst)
    if not sf.exists():
        return JSONResponse({"ready": False})
    data = json.loads(sf.read_text(encoding="utf-8"))
    data["ready"] = True
    data["inst_view"] = (inst or "ETH").upper()
    try:
        data["total"] = _total_portfolio()   # 总盘始终三标的汇总
    except Exception:  # noqa: BLE001
        data["total"] = None
    # 频率显示以覆盖文件为准（点完按钮立即反映，不等 agent 下一轮写盘）
    if data.get("agent") and AGENT_CFG.exists():
        try:
            data["agent"]["interval_sec"] = json.loads(
                AGENT_CFG.read_text(encoding="utf-8"))["interval_sec"]
        except Exception:
            pass
    return JSONResponse(data)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _HTML


_HTML = """<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Quantifiction 影子策略对比</title>
<style>
:root{
  --bg:#0f141b; --bg2:#0b0f15; --card:#171e27; --card2:#1e2732; --raise:#232d3a;
  --bd:#28323f; --bd2:#323e4d; --fg:#e9edf2; --mut:#8b96a5; --faint:#5b6675;
  --brass:#d4a54a; --brass-dim:#9a7c3a;
  --up:#3fb98a; --dn:#e0695a; --acc:#5b8ff0; --warn:#d8a838;
  --up-bg:rgba(63,185,138,.13); --dn-bg:rgba(224,105,90,.13);
  --mono:"SF Mono","JetBrains Mono",ui-monospace,"Cascadia Code",Menlo,Consolas,monospace;
}
*{box-sizing:border-box;margin:0}
body{background:
  radial-gradient(1200px 500px at 80% -10%,rgba(91,143,240,.06),transparent),
  var(--bg);color:var(--fg);
  font:14px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
.mono,td,th,.num{font-variant-numeric:tabular-nums}
.wrap{max-width:1280px;margin:0 auto;padding:0 22px 60px}

/* ---- 顶部应用栏 ---- */
.appbar{position:sticky;top:0;z-index:40;background:rgba(11,15,21,.82);
  backdrop-filter:saturate(140%) blur(10px);border-bottom:1px solid var(--bd);
  margin-bottom:22px}
.appbar-in{max-width:1280px;margin:0 auto;padding:12px 22px;display:flex;
  align-items:center;gap:16px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;letter-spacing:-.01em}
.brand .logo{width:26px;height:26px;border-radius:7px;display:grid;place-items:center;
  background:linear-gradient(135deg,var(--brass),var(--brass-dim));color:#12161d;font-size:15px;font-weight:800}
.brand small{color:var(--faint);font-weight:500;font-size:11px;letter-spacing:.03em}
.appbar .sub{color:var(--mut);font-size:12px;margin:0;display:flex;align-items:center;gap:7px}
.spacer{margin-left:auto}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--up);
  box-shadow:0 0 0 3px var(--up-bg);animation:pulse 2s infinite}
.stale .dot,.sub.stale .dot{background:var(--dn);box-shadow:0 0 0 3px var(--dn-bg)}
@keyframes pulse{50%{opacity:.55}}
@media (prefers-reduced-motion:reduce){.dot{animation:none}}

/* ---- 市场行情条 ---- */
.bar{display:flex;gap:20px;flex-wrap:wrap;color:var(--mut);font-size:12.5px;
  align-items:center;padding:2px 0}
.bar b{color:var(--fg);font-family:var(--mono);font-weight:600}

/* ---- 仪表盘：策略表全宽，Agent+持仓并排，长表内部滚 ---- */
.dash{display:grid;grid-template-columns:1fr 1.15fr;gap:18px;align-items:stretch;margin-top:6px}
@media (max-width:1000px){.dash{grid-template-columns:1fr}}
.dash>*{min-width:0}
.dash #agentbox .card{margin-bottom:0;height:100%}
.dash section{min-width:0;display:flex;flex-direction:column}
.dash section h2{margin:2px 0 9px}
/* 面板内滚动：表格封顶高度，内部滚，表头吸顶 */
.scrolly{max-height:400px;overflow:auto;border:1px solid var(--bd);border-radius:12px}
.scrolly table,#alltrades table{border:none;border-radius:0}
.scrolly thead th,#alltrades thead th{position:sticky;top:0;z-index:2}
#alltrades{max-height:340px;overflow:auto;border:1px solid var(--bd);border-radius:12px}
/* ★ 进行中交易大块：突出、加高、绿色左脉冲 */
.big-block{max-height:560px;overflow:auto;border:1px solid var(--bd2);border-radius:14px;
  box-shadow:0 0 0 1px rgba(63,185,138,.12),0 8px 30px rgba(0,0,0,.25)}
.big-block table{border:none;border-radius:0}
.big-block thead th{position:sticky;top:0;z-index:2;background:var(--bg2);
  font-size:11.5px;padding:12px 12px}
.big-block td{padding:12px 12px;font-size:13.5px}
.big-block tbody tr:hover{background:var(--card2)}
/* 折叠总盘 */
.tcollapse{display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.tcollapse .cap{font-size:26px;font-weight:700;font-family:var(--mono);letter-spacing:-.01em}
.tmini{color:var(--mut);font-size:13px}
.tmini b{font-family:var(--mono)}
.texpand{margin-left:auto;background:var(--card2);border:1px solid var(--bd2);color:var(--mut);
  border-radius:8px;padding:6px 13px;cursor:pointer;font-size:12px;transition:all .12s}
.texpand:hover{border-color:var(--brass);color:var(--brass)}
.nowrap th,.nowrap td{white-space:nowrap}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:5px}
::-webkit-scrollbar-track{background:transparent}

/* ---- 卡片系统 ---- */
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;
  padding:18px 20px;margin-bottom:16px}
.card .row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.big{font-weight:700;font-family:var(--mono);letter-spacing:-.01em}
.up{color:var(--up)}.dn{color:var(--dn)}.mut{color:var(--mut)}.warnc{color:var(--warn)}

/* ---- 区块标题 ---- */
h1{font-size:18px}
.sub{color:var(--mut);font-size:12px}
h2{font-size:12px;color:var(--faint);margin:26px 0 11px;font-weight:700;
  text-transform:uppercase;letter-spacing:.12em;display:flex;align-items:center;gap:8px}
h2::before{content:"";width:3px;height:13px;background:var(--brass);border-radius:2px;display:inline-block}

/* ---- 表格 ---- */
table{width:100%;border-collapse:collapse;background:var(--card);
  border:1px solid var(--bd);border-radius:12px;overflow:hidden}
th,td{padding:9px 9px;text-align:right;font-size:12.5px;border-bottom:1px solid var(--bd)}
th{color:var(--mut);font-weight:600;background:var(--bg2);font-size:10.5px;
  text-transform:uppercase;letter-spacing:.02em}
td{font-family:var(--mono)}
#tbl td:first-child{font-size:12px;line-height:1.3}
td:first-child,th:first-child{text-align:left;font-family:inherit}
tbody tr{transition:background .12s}
tbody tr:hover{background:var(--card2)}
tr:last-child td{border-bottom:none}
.spark{height:28px;cursor:pointer}
.rank{color:var(--faint);font-size:11px;margin-right:7px;font-family:var(--mono)}
.win{color:var(--brass);font-weight:700}
.note{color:var(--mut);font-size:12px;margin-top:16px;line-height:1.75;
  background:var(--card);border:1px solid var(--bd);border-left:3px solid var(--brass);
  border-radius:8px;padding:14px 18px}
.trades{overflow-x:auto}
#alltrades{max-height:440px;overflow-y:auto;border:1px solid var(--bd);border-radius:12px}
#alltrades table{border:none;border-radius:0}
#alltrades th{position:sticky;top:0;z-index:2}
#alltrades::-webkit-scrollbar,#mtrades::-webkit-scrollbar{width:10px}
#alltrades::-webkit-scrollbar-thumb,#mtrades::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:5px}
.tag{padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600}
.tag.l{background:var(--up-bg);color:var(--up)}.tag.s{background:var(--dn-bg);color:var(--dn)}

/* ---- 按钮/频率 ---- */
.freq{background:var(--card2);color:var(--fg);border:1px solid var(--bd2);
  border-radius:7px;padding:5px 11px;margin-right:6px;cursor:pointer;font-size:12px;
  transition:all .12s;font-family:inherit}
.freq:hover{border-color:var(--brass);color:var(--brass)}
.freqon{background:var(--brass);border-color:var(--brass);color:#12161d;font-weight:600}
.btn-mgmt{background:var(--card2);border:1px solid var(--bd2);color:var(--fg);
  border-radius:8px;padding:7px 14px;cursor:pointer;font-size:13px;font-weight:500;transition:all .12s}
.btn-mgmt:hover{border-color:var(--brass);color:var(--brass)}
/* 标的切换 */
.instsel{display:inline-flex;gap:0;background:var(--card2);border:1px solid var(--bd2);
  border-radius:9px;padding:3px;margin-left:6px}
.instsel .freq{margin:0;border:none;background:transparent;padding:5px 14px;border-radius:6px;font-weight:600}
.instsel .freq:hover{color:var(--brass);border:none}
.instsel .inston{background:var(--brass);color:#12161d}

/* ---- KPI 指标格(总盘) ---- */
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:1px;
  background:var(--bd);border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.kpi>div{background:var(--card2);padding:13px 15px}
.kpi .lab{color:var(--mut);font-size:11px;margin-bottom:3px}
.kpi .v{font-size:21px;font-weight:700;font-family:var(--mono);letter-spacing:-.01em;line-height:1.1}
.kpi .s{color:var(--faint);font-size:10px;margin-top:2px;font-family:var(--mono)}

/* ---- 弹窗 ---- */
#modal{display:none;position:fixed;inset:0;background:rgba(5,8,12,.72);z-index:50}
#modal.on{display:flex;align-items:center;justify-content:center}
#mbox{background:var(--card);border:1px solid var(--bd2);border-radius:14px;
  width:min(1060px,94vw);max-height:90vh;display:flex;flex-direction:column;padding:20px}
#mhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
#mhead b{font-size:16px}#mclose{background:none;border:none;color:var(--mut);font-size:24px;cursor:pointer}
#mchart{margin:6px 0 12px}#mtrades{overflow-y:auto;border:1px solid var(--bd);border-radius:10px}
#mtrades th{position:sticky;top:0}
</style></head><body>
<div class=appbar><div class=appbar-in>
  <div class=brand><span class=logo>Q</span><span>Quantifiction<br><small>影子多策略量化终端</small></span></div>
  <div class=sub id=stat><span class=dot></span>等待影子引擎…</div>
  <div class=instsel id=instsel>
    <button class="freq inston" data-i=ETH onclick=switchInst('ETH')>ETH</button>
    <button class=freq data-i=BTC onclick=switchInst('BTC')>BTC</button>
    <button class=freq data-i=SOL onclick=switchInst('SOL')>SOL</button>
  </div>
  <div class=spacer></div>
  <span class=mut style=font-size:12px>欧易模拟盘 · 零真金 · 扣真实手续费</span>
  <button class=btn-mgmt onclick=openMgmt()>⚙ 策略管理</button>
</div></div>

<div class=wrap>
<div class=bar id=meta></div>

<!-- ★ 进行中的交易：最想看的，置于最顶 -->
<!-- 总盘资金：概要，点击展开（最顶） -->
<div id=totalbox style=margin-top:14px></div>

<!-- Agent 认知层观点 -->
<div id=agentbox style=margin-top:16px></div>

<!-- ★ 进行中的交易：实时浮动盈亏，大块 -->
<h2 style=margin-top:20px>🔴 进行中的交易 · 实时浮动盈亏<span id=opencount class=mut style=text-transform:none;letter-spacing:0;font-weight:400></span></h2>
<div class="trades nowrap big-block" id=opentrades></div>

<!-- 策略排行榜：全宽，12列排得开不裁切 -->
<h2>各策略汇总 · <span id=leadinst class=warnc style=text-transform:none;letter-spacing:0>ETH</span> · 按扣费净利排序<span class=mut style=text-transform:none;letter-spacing:0;font-weight:400;margin-left:8px>（此处停用只停当前标的）</span></h2>
<div class="scrolly" id=leadwrap>
  <table id=tbl><thead><tr>
  <th>策略</th><th>信号/模式</th><th>止盈%</th><th>笔数</th><th>胜率</th>
  <th>毛利$</th><th>手续费$</th><th>净利$</th><th>夏普</th><th>回撤$</th><th>净值曲线</th><th>开关</th>
  </tr></thead><tbody id=rows><tr><td colspan=12 class=mut style=text-align:center;padding:24px>加载中…</td></tr></tbody></table>
</div>

<!-- 成交明细：全宽 -->
<h2 style="justify-content:space-between">
  <span style=display:flex;align-items:center;gap:8px>成交明细 · 买卖价 / 获利<span id=tradecount class=mut style=text-transform:none;letter-spacing:0;font-weight:400></span></span>
  <span id=tradesum style=text-transform:none;letter-spacing:0;font-weight:400></span>
</h2>
<div class="trades nowrap" id=alltrades></div>

<div class=note id=verdict></div>
</div><!-- /.wrap -->

<div id=mgmt onclick="if(event.target.id=='mgmt')closeMgmt()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:60">
 <div style="background:var(--card);border:1px solid var(--bd);border-radius:12px;width:min(880px,94vw);max-height:90vh;overflow-y:auto;padding:18px" onclick=event.stopPropagation()>
  <div style=display:flex;justify-content:space-between;align-items:center><b style=font-size:16px>⚙ 策略管理（唯一修改入口）</b><button onclick=closeMgmt() style="background:none;border:none;color:var(--mut);font-size:22px;cursor:pointer">×</button></div>
  <div class=mut style=font-size:12px;margin:4px_0_10px>修改经服务端格式校验后写入覆盖文件，引擎 3 秒内热生效并自动生成新版本号（旧版本与数据全保留）。百分比参数以 % 填写。</div>
  <div style=margin-bottom:10px><span class=mut style=font-size:12px>选择策略：</span><select id=mgsel onchange=loadMg() style="background:#0d1117;color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:5px 10px;min-width:240px"></select></div>
  <div id=mgform></div>
  <div id=mgmsg style=margin-top:10px;font-size:13px></div>
 </div>
</div>
<div id=modal onclick="if(event.target.id=='modal')closeDetail()">
 <div id=mbox>
  <div id=mhead><b id=mtitle>—</b><button id=mclose onclick=closeDetail()>×</button></div>
  <div id=mstats class=mut style=font-size:12px>—</div>
  <div id=mdef style=margin:8px_0></div>
  <div id=mchart></div>
  <div id=mtrades></div>
  <div class=mut style=font-size:11px;margin-top:8px;line-height:1.7>
   <b>最大浮盈 MFE%</b>：该笔持仓期间浮动盈利曾达到的最高点——若远高于最终净利，说明利润回吐（追踪止损针对的问题）。
   <b>最大浮亏 MAE%</b>：期间浮动亏损曾达到的最深点——若从未接近止损线却被止损说明止损过紧；若很深但最终盈利说明入场点位可改善。
  </div>
 </div>
</div>

<script>
const $=id=>document.getElementById(id);
async function setFreq(sec){
  try{const r=await(await fetch('/api/agent/interval?sec='+Math.round(sec),{method:'POST'})).json();
    $('freqmsg').textContent='已设为每'+Math.round(r.interval_sec/60)+'分钟（下轮生效）';}
  catch(e){$('freqmsg').textContent='设置失败';}
}
function closeDetail(){$('modal').classList.remove('on')}
function bigChart(pts){
  if(!pts||pts.length<2)return '<div class=mut style=padding:14px>成交不足，暂无曲线</div>';
  const w=1000,h=220,pl=46,pr=12,pt=10,pb=26;
  const t0=pts[0].ts,t1=pts[pts.length-1].ts,tr=(t1-t0)||1;
  const vs=pts.map(p=>p.eq);const mn=Math.min(0,...vs),mx=Math.max(0,...vs),rg=(mx-mn)||1;
  const X=ts=>pl+(ts-t0)/tr*(w-pl-pr);
  const Y=v=>pt+(mx-v)/rg*(h-pt-pb);
  const line=pts.map(p=>`${X(p.ts).toFixed(1)},${Y(p.eq).toFixed(1)}`).join(' ');
  const zy=Y(0).toFixed(1);
  const dots=pts.map((p,i)=>{const d=i?p.eq-pts[i-1].eq:p.eq;const c=d>=0?'#26a69a':'#ef5350';
    return `<circle cx="${X(p.ts).toFixed(1)}" cy="${Y(p.eq).toFixed(1)}" r="3" fill="${c}"><title>${hms(p.ts)}  净值 ${sg(p.eq,3)}  本笔 ${sg(d,3)}</title></circle>`}).join('');
  // x轴时间刻度（首/中/末）
  const ticks=[pts[0],pts[Math.floor(pts.length/2)],pts[pts.length-1]].map(p=>{
    const d=new Date(p.ts);return `<text x="${X(p.ts).toFixed(1)}" y="${h-6}" fill="#8b949e" font-size="11" text-anchor="middle">${p2(d.getMonth()+1)}-${p2(d.getDate())} ${hms(p.ts)}</text>`}).join('');
  const ylab=[mx,0,mn].filter((v,i,a)=>a.indexOf(v)===i).map(v=>`<text x="${pl-6}" y="${(Y(v)+4).toFixed(1)}" fill="#8b949e" font-size="11" text-anchor="end">${sg(v,2)}</text>`).join('');
  const col=vs[vs.length-1]>=0?'#26a69a':'#ef5350';
  return `<svg width="100%" viewBox="0 0 ${w} ${h}" style="background:#0d1117;border:1px solid var(--bd);border-radius:8px">
    <line x1="${pl}" y1="${zy}" x2="${w-pr}" y2="${zy}" stroke="#3d444d" stroke-dasharray="4,4"/>
    ${ylab}<polyline points="${line}" fill="none" stroke="${col}" stroke-width="1.8"/>${dots}${ticks}</svg>
  <div class=mut style=font-size:11px;margin-top:4px>每个圆点=一笔平仓（绿盈红亏），悬停看时间与盈亏；横轴=平仓时间线</div>`;
}
let MGDATA={};
function closeMgmt(){$('mgmt').style.display='none'}
async function openMgmt(){
  const d=await(await fetch('/api/shadow?inst='+curInst)).json();
  const sel=$('mgsel'); sel.innerHTML=(d.strategies||[]).map(x=>`<option>${x.name}</option>`).join('');
  $('mgmt').style.display='flex'; loadMg();
}
const MGFIELDS=[
 ['entry_th','入场阈值','',1],['tp_pct','止盈','%',100],['sl_pct','止损(可空)','%',100],
 ['trail_arm','追踪武装(可空)','%',100],['trail_gap','追踪回撤(可空)','%',100],
 ['max_hold','最大持仓','分钟',1/60],['cooldown','冷却','秒',1],['min_range','体制过滤(可空)','%',100]];
async function loadMg(){
  const name=$('mgsel').value;
  const d=await(await fetch('/api/strategy/detail?name='+encodeURIComponent(name)+'&inst='+curInst)).json();
  MGDATA=d; const df=d.definition||{}; const trail=df.trail||[null,null];
  const cur={entry_th:df.entry_th,tp_pct:df.tp_pct,sl_pct:df.sl_pct??null,
             trail_arm:trail[0],trail_gap:trail[1],max_hold:df.max_hold,
             cooldown:df.cooldown,min_range:df.min_range??null};
  $('mgform').innerHTML='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px 16px">'+
    MGFIELDS.map(([k,lab,unit,mult])=>{
      const v=cur[k]; const shown=(v==null)?'':(mult===1||mult===1/60?(mult===1?v:Math.round(v/60)):+(v*mult).toFixed(3));
      return `<label style=font-size:12px class=mut>${lab}<br><input id=mg_${k} value="${shown}" placeholder=${v==null?'空':''} style="width:100%;background:#0d1117;color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:5px 8px;margin-top:2px">${unit?'<span style=margin-left:4px>'+unit+'</span>':''}</label>`;
    }).join('')+'</div>'+
    `<div style=margin-top:12px><button class=freq style="background:#238636;border-color:#238636;color:#fff;padding:6px 16px" onclick=saveMg()>保存修改</button>
     <span class=mut style=font-size:11px;margin-left:10px>来源：${d.author==='agent'?'🤖 Agent生成':'👤 人工基线'} · 当前版本 <code>${(d.versions&&d.versions.length)?d.versions[d.versions.length-1].version_id:'—'}</code></span></div>`+
    `<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--bd)">
       <div class=mut style=font-size:12px;margin-bottom:6px>🌐 全局开关（对 <b>所有标的 ETH·BTC·SOL</b> 生效；面板里的按钮只停当前标的）</div>
       <button class=freq style="border-color:#7d3232" onclick="toggleGlobal('${name}',false)">全局停用</button>
       <button class=freq style="border-color:#238636" onclick="toggleGlobal('${name}',true)">全局启用</button>
       <span id=mgglob class=mut style=font-size:11px;margin-left:8px></span></div>`;
  $('mgmsg').textContent='';
}
async function saveMg(){
  const name=$('mgsel').value; const params={};
  for(const [k,,unit,mult] of MGFIELDS){
    const raw=$('mg_'+k).value.trim();
    if(raw===''){params[k]=null;continue}
    const num=parseFloat(raw); if(isNaN(num)){$('mgmsg').innerHTML='<span class=dn>'+k+' 不是数字</span>';return}
    params[k]= unit==='分钟'?Math.round(num*60) : (mult===1?num:num/mult);
  }
  const r=await(await fetch('/api/strategy/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,params})})).json();
  if(r.ok){$('mgmsg').innerHTML='<span class=up>✓ '+r.note+'</span>'; setTimeout(loadMg,3500);}
  else{$('mgmsg').innerHTML='<span class=dn>校验未通过：</span><br>'+r.errors.map(e=>'<span class=dn>· '+e+'</span>').join('<br>');}
}
const SIGCN={obi:'盘口失衡OBI',cvd:'主动买卖差CVD',mom30m:'30分时序动量',meanrev1h:'1h均值回归'};
const MODECN={mom:'顺势',rev:'反转'};
function defHtml(d){
  const df=d.definition; if(!df)return'';
  const rows=[];
  rows.push(['信号源',SIGCN[df.signal]||df.signal]);
  rows.push(['模式',MODECN[df.mode]||df.mode]);
  rows.push(['入场阈值',df.entry_th]);
  rows.push(['止盈',f(df.tp_pct*100,2)+'%']);
  if(df.sl_pct)rows.push(['止损',f(df.sl_pct*100,2)+'%']);
  if(df.trail)rows.push(['追踪止损','武装'+f(df.trail[0]*100,2)+'% / 回撤'+f(df.trail[1]*100,2)+'%锁定']);
  rows.push(['最大持仓',Math.round(df.max_hold/60)+'分钟']);
  rows.push(['冷却',df.cooldown+'秒']);
  if(df.min_range)rows.push(['体制过滤','近1h波幅≥'+f(df.min_range*100,2)+'%才入场']);
  if(df['class']==='AgentStrategy')rows.push(['LLM融合','是（agent观点 veto硬否决/±50%加成）']);
  rows.push(['来源',d.author==='agent'?'🤖 Agent生成':'👤 人工基线（agent不可改）']);
  const grid=rows.map(([k,v])=>`<div style="display:flex;gap:8px"><span class=mut style=min-width:70px>${k}</span><b>${v}</b></div>`).join('');
  let vh='';
  if((d.versions||[]).length){
    vh='<div class=mut style=font-size:11px;margin-top:8px>版本历史：'+
      d.versions.map(v=>{const dt=new Date(v.ts);return `<code>${v.version_id}</code>(${p2(dt.getMonth()+1)}-${p2(dt.getDate())} ${p2(dt.getHours())}:${p2(dt.getMinutes())})`}).join(' → ')+'</div>';
  }
  return `<div style="background:#0d1117;border:1px solid var(--bd);border-radius:8px;padding:12px;font-size:12px">
    <div class=mut style=margin-bottom:6px><b style=color:var(--fg)>策略定义</b>（当前版本 <code>${d.versions&&d.versions.length?d.versions[d.versions.length-1].version_id:'—'}</code>）</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:5px 18px">${grid}</div>${vh}</div>`;
}
async function openDetail(name){
  try{
    const d=await(await fetch('/api/strategy/detail?name='+encodeURIComponent(name)+'&inst='+curInst)).json();
    if(!d.ok)return;
    $('mtitle').textContent=d.name;
    $('mstats').textContent=`${d.n} 笔 · ${d.wins} 胜(${d.n?f(d.wins/d.n*100,0):0}%) · 累计净值 ${sg(d.net)} USDT`;
    $('mdef').innerHTML=defHtml(d);
    $('mchart').innerHTML=bigChart(d.points);
    $('mtrades').innerHTML=d.trades.length?'<table><thead><tr><th>方向</th><th>买入时间</th><th>买入价</th><th>卖出时间</th><th>卖出价</th><th>持仓时长</th><th>毛利USDT</th><th>手续费</th><th>净USDT</th><th title="最大浮盈：这笔单持仓期间浮动盈利的最高点（到手过的最好水平）">最大浮盈MFE%</th><th title="最大浮亏：持仓期间浮动亏损的最深点（中途最坏的时刻）">最大浮亏MAE%</th><th>出场</th></tr></thead><tbody>'+
      d.trades.map(t=>`<tr><td><span class="tag ${t.dir=='多'?'l':'s'}">${t.dir}</span></td><td>${hms(t.buy_ms)}</td><td>${f(t.buy_px)}</td><td>${hms(t.sell_ms)}</td><td>${f(t.sell_px)}</td><td>${dur(t.hold)}</td><td class=mut>${sg(t.gross_usd)}</td><td class=dn>-${f(t.fee_usd,3)}</td><td class="${cls(t.net_usd)}" style=font-weight:700>${sg(t.net_usd)}</td><td class=${cls(t.mfe_pct||0)}>${sg(t.mfe_pct||0,2)}</td><td class=dn>${f(t.mae_pct||0,2)}</td><td class=mut>${t.reason=='tp'?'止盈':t.reason=='sl'?'止损':t.reason=='trail'?'追踪':'超时'}</td></tr>`).join('')+'</tbody></table>':'<div class=mut style=padding:14px>暂无成交</div>';
    $('modal').classList.add('on');
  }catch(e){}
}
async function toggleStrat(name,on){
  // 面板按钮：只停当前标的(scope=inst)
  try{await fetch('/api/strategy/toggle?name='+encodeURIComponent(name)+'&on='+on+'&inst='+curInst+'&scope=inst',{method:'POST'});tick();}catch(e){}
}
async function toggleGlobal(name,on){
  // 策略管理：全局停(所有标的)
  try{await fetch('/api/strategy/toggle?name='+encodeURIComponent(name)+'&on='+on+'&scope=global',{method:'POST'});
    const e=$('mgglob');if(e)e.textContent=on?'✓ 已全局启用（所有标的）':'✓ 已全局停用（ETH·BTC·SOL 都停）';}catch(e){}
}
async function runNow(){
  try{await fetch('/api/agent/run-now',{method:'POST'});
    $('freqmsg').textContent='已请求立即执行，agent 将尽快辩论（若正在辩论则本轮结束后）';}
  catch(e){$('freqmsg').textContent='请求失败';}
}
const f=(n,d=2)=>Number(n).toLocaleString('en',{minimumFractionDigits:d,maximumFractionDigits:d});
const sg=(n,d=3)=>(n>=0?'+':'')+f(n,d);
const cls=n=>n>0?'up':n<0?'dn':'mut';
const p2=x=>String(x).padStart(2,'0');
function hms(ms){if(!ms)return'—';const d=new Date(ms);return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`}
function dur(s){if(s<60)return s+'s';const m=Math.floor(s/60);return m+'分'+(s%60)+'s'}
function spark(curve){
  if(!curve||curve.length<2)return'<span class=mut style=font-size:11px>待成交</span>';
  const w=150,h=30,pad=2,min=Math.min(...curve),max=Math.max(...curve),rng=(max-min)||1;
  const X=i=>(pad+i/(curve.length-1)*(w-2*pad)).toFixed(1);
  const Y=v=>(h-pad-(v-min)/rng*(h-2*pad)).toFixed(1);
  const pts=curve.map((v,i)=>`${X(i)},${Y(v)}`).join(' ');
  const last=curve[curve.length-1],col=last>=0?'#26a69a':'#ef5350';
  let zero='';
  if(max>=0&&min<=0){const zy=Y(0);
    zero=`<line x1="${pad}" y1="${zy}" x2="${w-pad}" y2="${zy}" stroke="#3d444d" stroke-width="1" stroke-dasharray="3,3" />`;}
  // 末端点 + 收盘于零轴上下的渐变面积
  const area=`<polygon points="${X(0)},${Y(curve[0])} ${pts} ${X(curve.length-1)},${h-pad} ${X(0)},${h-pad}" fill="${col}" opacity="0.10" />`;
  const dot=`<circle cx="${X(curve.length-1)}" cy="${Y(last)}" r="2.2" fill="${col}" />`;
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${area}${zero}<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5" />${dot}</svg>`;
}
// 总盘组合净值大曲线：curve = [[ts, cum], ...]
function bigCurve(curve){
  if(!curve||curve.length<2)return'<span class=mut style=font-size:12px>待成交积累</span>';
  const vals=curve.map(p=>p[1]),ts=curve.map(p=>p[0]);
  const w=1160,h=132,padL=8,padR=8,padT=10,padB=20;
  const min=Math.min(...vals,0),max=Math.max(...vals,0),rng=(max-min)||1;
  const X=i=>(padL+i/(curve.length-1)*(w-padL-padR)).toFixed(1);
  const Y=v=>(padT+(max-v)/rng*(h-padT-padB)).toFixed(1);
  const pts=vals.map((v,i)=>`${X(i)},${Y(v)}`).join(' ');
  const last=vals[vals.length-1],col=last>=0?'#26a69a':'#ef5350';
  const zy=Y(0);
  const zero=`<line x1="${padL}" y1="${zy}" x2="${w-padR}" y2="${zy}" stroke="#3d444d" stroke-width="1" stroke-dasharray="4,4" /><text x="${w-padR}" y="${zy-4}" fill="#8b949e" font-size="10" text-anchor="end">盈亏平衡</text>`;
  const area=`<polygon points="${X(0)},${zy} ${pts} ${X(curve.length-1)},${zy}" fill="${col}" opacity="0.12" />`;
  const dot=`<circle cx="${X(curve.length-1)}" cy="${Y(last)}" r="3.2" fill="${col}" /><text x="${X(curve.length-1)}" y="${Math.max(12,Y(last)-8)}" fill="${col}" font-size="12" font-weight="700" text-anchor="end">${last>=0?'+':''}${last.toFixed(2)}</text>`;
  const t0=new Date(ts[0]),t1=new Date(ts[ts.length-1]);
  const fmt=d=>`${(d.getMonth()+1)}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  const axis=`<text x="${padL}" y="${h-6}" fill="#8b949e" font-size="10">${fmt(t0)}</text><text x="${w-padR}" y="${h-6}" fill="#8b949e" font-size="10" text-anchor="end">${fmt(t1)}</text><text x="${padL}" y="14" fill="#8b949e" font-size="10">峰值 ${max.toFixed(1)}</text><text x="${padL}" y="${h-padB+2}" fill="#8b949e" font-size="10">谷值 ${min.toFixed(1)}</text>`;
  return `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="display:block">${area}${zero}<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2" />${dot}${axis}</svg>`;
}
// ---- 成交明细：分页 + 下滑加载更多 ----
let tradeOffset=0,tradeTotal=0,lastTotal=0,tradeBuilt=false,tradeLoading=false;
function tradeRow(t){return `<tr><td class=mut>${t.strategy||''}</td><td><span class="tag ${t.dir=='多'?'l':'s'}">${t.dir}</span></td><td>${hms(t.buy_ms)}</td><td>${hms(t.sell_ms)}</td><td>${dur(t.hold)}</td><td>${f(t.buy_px)}</td><td>${f(t.sell_px)}</td><td class=mut>${sg(t.gross_usd)}</td><td class=dn>-${f(t.fee_usd,3)}</td><td class="${cls(t.net_usd)}" style=font-weight:700>${sg(t.net_usd)}</td><td class=mut>${t.reason=='tp'?'止盈':t.reason=='sl'?'止损':t.reason=='trail'?'追踪':'超时'}</td></tr>`}
function buildTradeTable(){
  $('alltrades').innerHTML='<table><thead><tr><th>策略</th><th>方向</th><th>买入时间</th><th>卖出时间</th><th>持仓时长</th><th>买入价</th><th>卖出价</th><th>毛利USDT</th><th>手续费USDT</th><th>获利USDT(净)</th><th>出场</th></tr></thead><tbody id=tradebody></tbody></table><div id=tradeend class=mut style=text-align:center;padding:10px;font-size:12px></div>';
  tradeBuilt=true;
  $('alltrades').onscroll=()=>{const el=$('alltrades');if(el.scrollTop+el.clientHeight>=el.scrollHeight-60)loadMoreTrades();};
}
async function loadMoreTrades(){
  if(tradeLoading)return;if(tradeBuilt&&tradeOffset>0&&tradeOffset>=tradeTotal){$('tradeend').textContent='— 已全部加载 —';return;}
  tradeLoading=true;
  try{
    const r=await(await fetch(`/api/trades?offset=${tradeOffset}&limit=50&inst=${curInst}`)).json();
    const tb=$('tradebody');if(!tb){tradeLoading=false;return;}
    if(tradeOffset===0&&!r.trades.length){tb.innerHTML='<tr><td colspan=12 class=mut style=text-align:center;padding:20px>暂无成交（策略等待信号触发）</td></tr>';}
    else tb.insertAdjacentHTML('beforeend',r.trades.map(tradeRow).join(''));
    tradeOffset+=r.trades.length;tradeTotal=r.total;
    $('tradeend').textContent=tradeOffset>=tradeTotal?'— 已全部加载 '+tradeTotal+' 笔 —':'下滑加载更多…';
    // 该标的总体盈亏汇总（显示在标题右侧）
    if(r.summary){const s=r.summary;const el=$('tradesum');if(el){
      const c=s.net_usd>=0?'up':'dn';
      el.innerHTML=`<span class=${c} style=font-weight:700;font-size:15px>${s.net_usd>=0?'+':''}${f(s.net_usd,2)} USDT</span>`+
        ` <span class=mut style=font-size:12px>净利 · 毛利 ${s.gross_usd>=0?'+':''}${f(s.gross_usd,2)} · 手续费 -${f(s.fee_usd,2)} · 胜率 ${s.win_rate}% · ${r.total}笔</span>`;}}
  }catch(e){}
  tradeLoading=false;
}
function resetTrades(){tradeOffset=0;const tb=$('tradebody');if(tb)tb.innerHTML='';loadMoreTrades();}

let totalExp=false;
function toggleTotal(){totalExp=!totalExp;tick();}
let curInst='ETH';
function switchInst(i){curInst=i;
  document.querySelectorAll('#instsel .freq').forEach(b=>b.classList.toggle('inston',b.dataset.i===i));
  const li=$('leadinst');if(li)li.textContent=i;
  resetTrades();tick();}
async function tick(){
 try{
  const d=await(await fetch('/api/shadow?inst='+curInst)).json();
  if(!d.ready){$('stat').innerHTML='<span class=dot></span>影子引擎未就绪';return;}
  $('stat').innerHTML='<span class=dot></span>实时';document.querySelector('.sub').classList.remove('stale');
  {const ag=Math.round((Date.now()-d.ts)/1000);
   setTimeout(()=>{const e=$('pxage');if(e){e.textContent=' ('+ag+'s前)';e.style.color=ag>12?'var(--dn)':'var(--mut)';}},0);}
  $('meta').innerHTML=`标的 <b>${d.inst}</b> · 运行 <b>${Math.floor(d.runtime_sec/60)}分${d.runtime_sec%60}秒</b> · 采样 <b>${d.ticks}</b> 次 · 现价 <b>${f(d.mid)}</b><span id=pxage style=font-size:11px></span> · OBI <b>${sg(d.obi,3)}</b> · 每笔名义 <b>$${d.notional}</b> · 往返费 <b>${d.fee_roundtrip_pct}%</b>`;
  // Agent 观点面板
  const ag=d.agent;
  if(ag){
    const age=Math.floor((Date.now()-ag.ts)/1000);
    const sc=ag.veto?'dn':(ag.stance>0?'up':ag.stance<0?'dn':'mut');
    const dir=ag.veto?'否决交易':(ag.stance>0.05?'偏多':ag.stance<-0.05?'偏空':'中性');
    const ctx=ag.context||{};
    const intv=ag.interval_sec||900;const nextIn=Math.max(0,intv-age);
    $('agentbox').innerHTML=`<div class=card style="border-left:3px solid var(--brass)">
      <div class=row style=margin:0><span><b>🤖 Agent 认知层观点</b> <span class=mut>(${ag.model} · 每${Math.round(intv/60)}分钟辩论 · ${Math.floor(age/60)}分${age%60}秒前 · 下次约${Math.floor(nextIn/60)}分${nextIn%60}秒后 · 成本¥${f(ag.cost_rmb,3)})</span></span>
      <span class="big ${sc}" style=font-size:20px>${dir} ${ag.veto?'':(ag.stance>=0?'+':'')+f(ag.stance,2)}</span></div>
      <div class=row style=margin:6px_0><span class=mut>信心 ${f(ag.conviction,2)} · 数据：资金费率 ${ctx.funding_rate}% · 多空比 ${ctx.long_short_ratio} · 24h ${ctx.chg24h_pct}% · OBI ${ctx.obi}</span></div>
      <div style=color:var(--fg);font-size:13px;margin-top:4px>${ag.reasoning||''}</div>
      ${(ag.key_risks||[]).length?'<div class=mut style=font-size:12px;margin-top:6px>风险：'+ag.key_risks.join('；')+'</div>':''}
      ${ag.valid?'':'<div class=dn style=font-size:12px>⚠ 本次观点未通过校验('+(ag.valid_detail||'')+')，Agent策略降级为纯OBI</div>'}
      <div style=margin-top:10px;padding-top:8px;border-top:1px solid var(--bd);font-size:12px>
        <span class=mut>辩论频率：</span>
        <button class=freq data-s=300 onclick=setFreq(300)>5分</button>
        <button class=freq data-s=600 onclick=setFreq(600)>10分</button>
        <button class=freq data-s=900 onclick=setFreq(900)>15分</button>
        <button class=freq data-s=1800 onclick=setFreq(1800)>30分</button>
        <button class=freq data-s=3600 onclick=setFreq(3600)>60分</button>
        <input id=freqcustom type=number min=2 max=120 placeholder=自定义 style="width:70px;background:#0d1117;color:var(--fg);border:1px solid var(--bd);border-radius:5px;padding:2px 6px"> <span class=mut>分</span>
        <button class=freq onclick="setFreq(($('freqcustom').value||15)*60)">应用</button>
        <button class=freq style="background:#238636;border-color:#238636;color:#fff;margin-left:10px" onclick=runNow()>⚡ 立即执行</button>
        <span id=freqmsg class=mut style=margin-left:8px></span>
      </div>
    </div>`;
    document.querySelectorAll('.freq').forEach(b=>{if(+b.dataset.s===intv)b.classList.add('freqon')});
  }else $('agentbox').innerHTML='<div class=card style=color:var(--mut)>🤖 Agent 认知层：等待首次辩论（agent_runner 启动后约30秒出观点）…</div>';

  // 总盘资金 + 资金变化曲线（独立容错，不影响整页）
  try{
  const T=d.total;
  if(T){
    const cls=T.net_usd>=0?'up':'dn';
    const ucls=(T.unrealized_usd||0)>=0?'up':'dn';
    const rcls=(T.realized_usd||0)>=0?'up':'dn';
    const pnlLabel=T.net_usd>=0?'总盈利':'总亏损';
    const bd=T.net_usd>=0?'rgba(63,185,138,.4)':'rgba(224,105,90,.4)';
    if(!totalExp){
      // 折叠：只看总体
      $('totalbox').innerHTML=`<div class=card style="border-color:${bd}">
        <div class=tcollapse>
          <b style=font-size:15px>💰 总盘资金</b>
          <div><span class=tmini>当前资金</span> <span class="cap ${cls}">$${f(T.current_capital,2)}</span></div>
          <div class=tmini>${pnlLabel} <b class="${cls}">${T.net_usd>=0?'+':''}${f(T.net_usd,2)}</b> <span class="${cls}">(${T.return_pct>=0?'+':''}${f(T.return_pct,2)}%)</span></div>
          <div class=tmini>浮动 <b class="${ucls}">${(T.unrealized_usd||0)>=0?'+':''}${f(T.unrealized_usd,2)}</b> · ${T.open_positions}仓</div>
          <span class="${T.stale?'dn':'up'}" style=font-size:11px;font-weight:600>${T.stale?'⚠ >30s':'● 实时'}</span>
          <button class=texpand onclick=toggleTotal()>展开明细 ▾</button>
        </div>
      </div>`;
    }else{
      // 展开：完整明细
      $('totalbox').innerHTML=`<div class=card style="border-color:${bd}">
        <div class=row style="margin:0 0 14px;flex-wrap:wrap;gap:8px">
          <b style=font-size:15px>💰 总盘资金情况</b>
          <span class="${T.stale?'dn':'up'}" style=font-size:11px;font-weight:600>${T.stale?'⚠ 部分快照 >30s':'● 实时行情'}</span>
          <button class=texpand onclick=toggleTotal()>收起 ▴</button>
        </div>
        <div style=color:var(--mut);font-size:12px;margin:-6px 0 12px>全 ${T.instruments} 标的(ETH·BTC·SOL) · ${T.strat||'?'} 策略 · 每策略名义 $${d.notional} · 已实现 + 浮动(按现价实时) · 扣真实手续费</div>
        <div class=kpi>
          <div><div class=lab>起始资金</div><div class=v>$${f(T.start_capital,2)}</div></div>
          <div><div class=lab>当前资金 · 含浮动</div><div class="v ${cls}">$${f(T.current_capital,2)}</div></div>
          <div><div class=lab>${pnlLabel}</div><div class="v ${cls}">${T.net_usd>=0?'+':''}${f(T.net_usd,2)}</div><div class="s ${cls}">${T.return_pct>=0?'+':''}${f(T.return_pct,2)}%</div></div>
          <div><div class=lab>已实现盈亏</div><div class="v ${rcls}">${(T.realized_usd||0)>=0?'+':''}${f(T.realized_usd,2)}</div><div class=s>${T.trades} 笔平仓</div></div>
          <div><div class=lab>浮动盈亏 · 实时</div><div class="v ${ucls}">${(T.unrealized_usd||0)>=0?'+':''}${f(T.unrealized_usd,3)}</div><div class=s>${T.open_positions} 个持仓</div></div>
          <div><div class=lab>胜率 · 回撤</div><div class=v>${T.win_rate}%</div><div class="s dn">回撤 ${f(T.max_dd_pct,2)}%</div></div>
        </div>
        <div style=margin-top:16px;font-size:11px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em>资金变化曲线 · 已实现累计</div>
        <div style=margin-top:6px>${bigCurve(T.curve)}</div>
      </div>`;
    }
  }else{
    $('totalbox').innerHTML='<div class=card style=color:var(--mut)>💰 总盘资金：等待成交数据聚合…</div>';
  }
  }catch(e){ $('totalbox').innerHTML='<div class=card style=color:var(--mut)>💰 总盘资金：渲染中…</div>'; }

  // 进行中的交易（最上面）
  const OT=d.open_trades||[];
  {const oc=$('opencount');if(oc){const upnl=OT.reduce((a,t)=>a+(t.net_if_close||0),0);
    oc.innerHTML=OT.length?`　${OT.length} 个持仓 · 合计浮动 <b class="${upnl>=0?'up':'dn'}">${upnl>=0?'+':''}${upnl.toFixed(2)} USDT</b>`:'';}}
  if(OT.length){
    $('opentrades').innerHTML='<table><thead><tr><th>策略</th><th>方向</th><th>开仓时间</th><th>持仓时长</th><th>数量ETH</th><th title=每笔统一名义100USDT便于横向对比>投入USDT</th><th>现在价值USDT</th><th>开仓价</th><th>现价</th><th>浮动%</th><th>浮动毛利USDT</th><th>此刻平仓净USDT</th><th>止盈目标%</th></tr></thead><tbody>'+
    OT.map(t=>`<tr><td class=mut>${t.strategy}</td><td><span class="tag ${t.dir=='多'?'l':'s'}">${t.dir}</span></td><td>${hms(t.open_ms)}</td><td>${dur(t.hold)}</td><td>${t.qty??'—'}</td><td>${f(t.invested??100,0)}</td><td class="${cls((t.cur_value??100)-100)}" style=font-weight:700>${f(t.cur_value??100,3)}</td><td>${f(t.entry)}</td><td>${f(t.cur)}</td><td class=${cls(t.upnl_pct)}>${sg(t.upnl_pct,3)}%</td><td class=${cls(t.gross_usd)}>${sg(t.gross_usd)}</td><td class="${cls(t.net_if_close)}" style=font-weight:700>${sg(t.net_if_close)}</td><td class=mut>+${f(t.tp_target,2)}</td></tr>`).join('')+'</tbody></table>';
  }else $('opentrades').innerHTML='<div class=mut style=padding:14px;background:var(--card);border:1px solid var(--bd);border-radius:10px>当前无进行中的交易（策略均空仓，等待信号）</div>';

  const S=d.strategies;
  $('rows').innerHTML=S.map((s,i)=>`<tr style="${s.enabled===false?'opacity:.45':''}">
   <td style=cursor:pointer onclick="openDetail('${s.name}')" title=点击查看策略详情><span class=rank>#${i+1}</span><span style=text-decoration:underline;text-underline-offset:3px>${s.name}</span>${s.open?' <span class=mut>(持仓中)</span>':''}${s.enabled===false?' <span style=color:var(--dn);font-size:11px>[已停]</span>':''}</td>
   <td class=mut>${s.signal}/${s.mode=='mom'?'顺势':'反转'}</td>
   <td class=mut>${f(s.tp_pct,2)}</td>
   <td>${s.trades}</td>
   <td>${f(s.win_rate,0)}%</td>
   <td class=mut>${sg(s.gross_usd)}</td>
   <td class=dn>-${f(s.fee_usd,3)}</td>
   <td class="${cls(s.net_usd)}" style=font-weight:700>${sg(s.net_usd)}</td>
   <td class=${cls(s.sharpe)}>${sg(s.sharpe)}</td>
   <td class=dn>${f(s.max_dd,3)}</td>
   <td onclick="openDetail('${s.name}')" title=点击查看详情>${spark(s.equity_curve)}</td><td><button class=freq style="${s.enabled===false?'background:#238636;border-color:#238636;color:#fff':''}" onclick="toggleStrat('${s.name}',${s.enabled===false})">${s.enabled===false?'启用':'停用'}</button></td></tr>`).join('');
  // 成交明细走独立分页加载（见下方 loadMoreTrades），此处仅按需刷新最新
  tradeTotal=d.total_trades||0;
  $('tradecount').textContent=' · 共 '+tradeTotal+' 笔';
  if(!tradeBuilt){buildTradeTable();loadMoreTrades();}
  else if(tradeTotal>lastTotal && $('alltrades').scrollTop<12){resetTrades();}  // 在顶部且有新成交→刷新
  lastTotal=tradeTotal;
  // 结论
  const profitable=S.filter(s=>s.trades>=5&&s.net_usd>0);
  const total=S.reduce((a,s)=>a+s.trades,0);
  let v='<b>结论：</b>';
  if(total<10)v+='样本太少（需累计更多成交，建议 ≥50 笔/策略），暂不能下结论。';
  else if(!profitable.length)v+='<span class=dn>目前没有任何策略扣费后为正</span>——说明这些简单盘口信号的 edge 覆盖不了 0.10% 手续费。这是有价值的证伪：不要拿真金去跑它们。';
  else v+=`<span class=up>${profitable.map(s=>s.name).join('、')}</span> 扣费后为正（样本 ${profitable[0].trades} 笔）。需继续观察至 ≥50 笔确认非偶然，再考虑小资金实盘。`;
  v+='<br>提醒：影子模式假设成交在中间价、无滑点；真实实盘净利会更低。夏普为每笔收益率口径，仅供横向对比。';
  $('verdict').innerHTML=v;
 }catch(e){$('stat').innerHTML='<span class=dot></span>连接失败';document.querySelector('.sub').classList.add('stale');}
}
tick();setInterval(tick,3000);
</script></body></html>"""
