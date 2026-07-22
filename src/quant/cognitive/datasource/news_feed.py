"""第 7 类判断依据：新闻标题 + 恐惧贪婪指数（免费源，无需 key）。

- 恐惧贪婪指数：api.alternative.me/fng（当期+前期，看情绪方向）
- 新闻标题：Cointelegraph / Decrypt RSS（各取最新数条，标题即信息）
带文件缓存（TTL 10 分钟）：agent 每 30 分辩论一次，无需每次打源站。
失败静默降级（返回 None/空）——新闻缺失不阻塞辩论（宪法 II 降级精神）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

CACHE = Path("data/news_cache.json")
TTL_SEC = 600
RSS_SOURCES = [
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
]
FNG_URL = "https://api.alternative.me/fng/?limit=2"
MAX_TITLES = 8
_TITLE_RE = re.compile(r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)


def _fetch_fng(client) -> dict | None:
    try:
        r = client.get(FNG_URL, timeout=10)
        rows = r.json()["data"]
        cur, prev = rows[0], rows[1] if len(rows) > 1 else rows[0]
        return {"value": int(cur["value"]), "label": cur["value_classification"],
                "prev": int(prev["value"])}
    except Exception:  # noqa: BLE001
        return None


def _fetch_titles(client) -> list[str]:
    out: list[str] = []
    per = max(2, MAX_TITLES // len(RSS_SOURCES))
    for name, url in RSS_SOURCES:
        try:
            r = client.get(url, timeout=10, follow_redirects=True,
                           headers={"User-Agent": "Mozilla/5.0"})
            titles = _TITLE_RE.findall(r.text)[:per]
            out.extend(f"[{name}] {t.strip()}" for t in titles if t.strip())
        except Exception:  # noqa: BLE001
            continue
    return out[:MAX_TITLES]


def get_news_context() -> dict:
    """返回 {fng: {...}|None, titles: [...], ts}。带缓存。"""
    if CACHE.exists():
        try:
            c = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - c.get("ts", 0) < TTL_SEC:
                return c
        except Exception:  # noqa: BLE001
            pass
    import httpx
    with httpx.Client() as client:
        data = {"fng": _fetch_fng(client), "titles": _fetch_titles(client),
                "ts": time.time()}
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return data
