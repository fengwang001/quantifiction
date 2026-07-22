"""T012：结构化日志 + system_events 落库工具（data-model B 节）。

闸门拒单、熔断、地板触及、Watchdog 动作、WS 重连全部经此记录。
落库为可选（无 PG 时降级为结构化 stderr 日志），保证纯模块可测。
"""
from __future__ import annotations

import json
import logging
import sys
import time
from enum import Enum
from typing import Any

logger = logging.getLogger("quantifiction")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    FATAL = "fatal"


def make_event(severity: Severity, source: str, kind: str, **payload: Any) -> dict[str, Any]:
    return {
        "ts": int(time.time() * 1000),
        "severity": severity.value,
        "source": source,
        "kind": kind,
        "payload": payload,
    }


def log_event(severity: Severity, source: str, kind: str, **payload: Any) -> dict[str, Any]:
    """始终结构化打日志；调用方可另行将返回 dict 落 system_events 表。"""
    evt = make_event(severity, source, kind, **payload)
    level = {
        Severity.INFO: logging.INFO,
        Severity.WARN: logging.WARNING,
        Severity.FATAL: logging.CRITICAL,
    }[severity]
    logger.log(level, json.dumps(evt, ensure_ascii=False))
    return evt
