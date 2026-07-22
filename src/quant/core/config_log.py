"""T044：config_changes 留痕（宪法 V）。

每次 YAML 变更→git_sha + diff 落库，每笔交易关联当时 config_version。
否则无法区分收益变化源于策略还是参数改动。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigChange:
    actor: str
    file: str
    diff: str
    git_sha: str


def content_sha(text: str) -> str:
    """无 git 环境的回退指纹（内容哈希前 12 位）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


INSERT_SQL = """
INSERT INTO config_changes (actor, file, diff, git_sha)
VALUES (%(actor)s, %(file)s, %(diff)s, %(git_sha)s)
RETURNING config_version
"""


def record_change(conn, change: ConfigChange) -> int:
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, change.__dict__)
        version = cur.fetchone()[0]
    conn.commit()
    return int(version)
