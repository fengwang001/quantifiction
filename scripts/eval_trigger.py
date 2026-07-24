"""评估触发检查（迭代111：定时评估→条件触发）。

只在"真正值得评估"时输出 TRIGGER 行（供 Monitor 唤醒 Claude 评估）：
  1. 新成交：自上次触发起累计 ≥ NEW_TRADES 笔新平仓
  2. 资金费：任一标的 |funding| ≥ carry 入场阈值(0.02%/8h) → carry 机会
  3. 波动放大：ETH 近1h 波幅 ≥ VOL_SPIKE% → 均值回归/趋势机会
无条件满足则静默（不输出），Monitor 不唤醒，避免静市空跑。
"""
import json
import glob
import os
import time

STATE = "data/eval_trigger_state.json"
NEW_TRADES = 8          # 累计新成交阈值
FUNDING_ABS = 0.0002    # carry 入场阈值 0.02%/8h
VOL_SPIKE = 1.5         # 近1h波幅%
MIN_GAP_SEC = 1800      # 两次触发最小间隔(防抖，30分钟)


def _load(p, default):
    try:
        return json.loads(open(p, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        return default


def total_trades():
    n = 0
    for f in ["data/shadow_persist.json", "data/shadow_persist_btc.json",
              "data/shadow_persist_sol.json"]:
        d = _load(f, {})
        for s in d.get("strategies", []):
            n += len(s.get("trades", []))
    return n


def max_funding():
    cs = _load("data/carry_state.json", {})
    fr = cs.get("fundings_pct", {})   # 存的是 fr*100
    if not fr:
        return 0.0
    return max(abs(v) / 100 for v in fr.values())   # 还原为 rate


def eth_vol_1h():
    now = time.time() * 1000
    fs = sorted([f for f in glob.glob("data/ticks/*.jsonl")
                 if os.path.basename(f)[0].isdigit()])
    if not fs:
        return 0.0
    mids = []
    for line in open(fs[-1], encoding="utf-8").read().strip().split("\n"):
        try:
            t = json.loads(line)
            if now - t["ts"] < 3600 * 1000:
                mids.append(t["mid"])
        except Exception:  # noqa: BLE001
            pass
    if len(mids) < 10:
        return 0.0
    return (max(mids) - min(mids)) / min(mids) * 100


def main():
    st = _load(STATE, {})
    last_trades = st.get("last_trades", 0)
    last_trig = st.get("last_trigger_ts", 0)
    now = time.time()

    cur_trades = total_trades()
    reasons = []
    if cur_trades - last_trades >= NEW_TRADES:
        reasons.append(f"{cur_trades - last_trades}笔新成交")
    if max_funding() >= FUNDING_ABS:
        reasons.append(f"资金费达carry阈值({max_funding()*100:.4f}%)")
    if eth_vol_1h() >= VOL_SPIKE:
        reasons.append(f"ETH波动放大({eth_vol_1h():.2f}%)")

    if reasons and (now - last_trig) >= MIN_GAP_SEC:
        print(f"TRIGGER: {' + '.join(reasons)}", flush=True)
        st["last_trades"] = cur_trades
        st["last_trigger_ts"] = now
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    else:
        # 静默：不输出（Monitor 不唤醒）。仅更新 last_trades 基线避免累积误判。
        st["last_trades"] = max(last_trades, cur_trades - NEW_TRADES + 1) if cur_trades < last_trades else last_trades
        # 不改 last_trigger


if __name__ == "__main__":
    main()
