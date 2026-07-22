"""第 9 类判断依据：宏观 / 美联储（免费源，无需 key）。

- DXY 美元指数、US10Y 美债收益率：Yahoo Finance（现值 + 5日变化）
  美元/收益率上行 = 流动性收紧 = 加密逆风；反之顺风
- FOMC 会议日历：官方公布的 2026 年议息日程（硬编码，距下次会议天数）
  会议临近 = 政策不确定性 = 波动风险窗口
- 宏观新闻标题：investing.com 经济频道 RSS（Fed/通胀/利率相关优先）
缓存 30 分钟；失败静默降级（宪法 II 精神）。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

CACHE = Path("data/macro_cache.json")
TTL_SEC = 1800

# 美联储官网公布的 2026 FOMC 议息会议日程（次日为决议日）
FOMC_2026 = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
]

_YH = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=7d&interval=1d"
_ECON_RSS = "https://www.investing.com/rss/news_14.rss"
_TITLE_RE = re.compile(r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
_FED_KW = re.compile(r"fed|fomc|rate|inflation|cpi|powell|treasury|yield|dollar", re.I)


def _yahoo_quote(client, sym: str) -> dict | None:
    try:
        r = client.get(_YH.format(sym=sym), timeout=12,
                       headers={"User-Agent": "Mozilla/5.0"})
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        last, first = closes[-1], closes[0]
        return {"last": round(last, 2), "chg_5d": round((last - first) / first * 100, 2)}
    except Exception:  # noqa: BLE001
        return None


def _fomc_countdown() -> dict:
    today = date.today()
    nxt = next((d for d in FOMC_2026 if d >= today), None)
    if nxt is None:
        return {"next": None, "days": None}
    return {"next": nxt.isoformat(), "days": (nxt - today).days}


def _macro_titles(client) -> list[str]:
    try:
        r = client.get(_ECON_RSS, timeout=12, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0"})
        titles = [t.strip() for t in _TITLE_RE.findall(r.text)]
        fed = [t for t in titles if _FED_KW.search(t)]
        rest = [t for t in titles if t not in fed]
        return (fed + rest)[:5]
    except Exception:  # noqa: BLE001
        return []


def get_macro() -> dict | None:
    if CACHE.exists():
        try:
            c = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - c.get("ts", 0) < TTL_SEC:
                return c
        except Exception:  # noqa: BLE001
            pass
    import httpx
    with httpx.Client() as client:
        out = {
            "ts": time.time(),
            "dxy": _yahoo_quote(client, "DX-Y.NYB"),
            "us10y": _yahoo_quote(client, "%5ETNX"),
            "fomc": _fomc_countdown(),
            "titles": _macro_titles(client),
        }
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return out
