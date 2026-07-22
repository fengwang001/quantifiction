"""策略快照与版本留痕（宪法 V：全量留存可回放）。

- 每个策略定义（信号/模式/阈值/TP/时长）→ 规范化 JSON → 内容哈希 = version_id
- 快照追加写入 data/strategy_registry.jsonl（不可变日志，同版本只记一次）
- provenance：author=human 的策略 immutable=true，agent 只能改/退役 author=agent 的
- 每笔成交关联 strategy_version_id，可追溯"哪个版本产生了哪笔交易"

这是 Agent 生成策略（P3 第一步）的前置：先有不可变人工基线 + 版本追溯，
才能安全地让 agent 动策略。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REGISTRY = Path("data/strategy_registry.jsonl")


class ProvenanceError(PermissionError):
    """违反 provenance 权限：试图修改非本人创建的策略。"""


def strategy_def(s) -> dict:
    """从 Strategy 实例提取规范化定义（决定版本哈希的全部字段）。"""
    return {
        "name": s.name,
        "signal": getattr(s, "signal", "obi"),
        "mode": getattr(s, "mode", "mom"),
        "entry_th": s.entry_th,
        "tp_pct": s.tp_pct,
        "max_hold": s.max_hold,
        "cooldown": s.cooldown,
        "class": type(s).__name__,
        **({"sl_pct": s.sl_pct} if getattr(s, "sl_pct", None) is not None else {}),
        **({"min_range": s.min_range} if getattr(s, "min_range", None) is not None else {}),
        **({"trail": [s.trail_arm, s.trail_gap]} if getattr(s, "trail_arm", None) is not None else {}),
    }


def version_id(defn: dict) -> str:
    """内容哈希（前 12 位）——定义变了版本号必变，未变则稳定。"""
    canon = json.dumps(defn, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def _load_known() -> dict[str, dict]:
    """version_id → 快照记录。"""
    out: dict[str, dict] = {}
    if REGISTRY.exists():
        for line in REGISTRY.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                out[rec["version_id"]] = rec
    return out


def snapshot(s, author: str = "human") -> str:
    """登记策略快照（幂等：同版本不重复写）。返回 version_id。"""
    defn = strategy_def(s)
    vid = version_id(defn)
    known = _load_known()
    if vid not in known:
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "version_id": vid,
            "ts": int(time.time() * 1000),
            "author": author,
            "immutable": author == "human",   # 人工策略不可被 agent 修改
            "definition": defn,
        }
        with REGISTRY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return vid


def assert_editable_by(vid: str, actor: str) -> None:
    """provenance 检查：actor 试图修改/退役 vid 策略是否被允许。

    规则：human 建的（immutable）只有 human 可动；agent 只能动 agent 自己建的。
    """
    known = _load_known()
    rec = known.get(vid)
    if rec is None:
        return  # 未登记的不拦（登记时会定 provenance）
    if actor == "agent" and rec["author"] != "agent":
        raise ProvenanceError(
            f"策略 {rec['definition']['name']}({vid}) 由 {rec['author']} 创建，agent 无权修改"
        )


def history(name: str | None = None) -> list[dict]:
    """查询快照历史（可按策略名过滤），按时间正序。"""
    recs = sorted(_load_known().values(), key=lambda r: r["ts"])
    if name:
        recs = [r for r in recs if r["definition"]["name"] == name]
    return recs
