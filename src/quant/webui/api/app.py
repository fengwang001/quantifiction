"""T060：FastAPI 控制台应用（★ 不持有交易 Key，CT-WEB-1）。

只读端点 + 控制端点（写 Redis 中转）。控制指令经 ControlWriter → strategy 执行。
风控参数写入一律 403（guards）。部署经 Tailscale，不暴露公网。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from quant.core.events import Severity, log_event
from quant.webui.api.control import Command, ControlWriter
from quant.webui.api.guards import ForbiddenFieldError, filter_editable


def create_app(control: ControlWriter, readmodel: Any) -> FastAPI:
    """control：Redis 控制写入；readmodel：只读数据访问对象（注入）。"""
    app = FastAPI(title="Quantifiction Console", docs_url="/docs")

    @app.get("/status")
    async def status() -> dict:
        return await readmodel.status()

    @app.get("/symbols")
    async def symbols() -> dict:
        return await readmodel.symbols()

    @app.get("/strategies")
    async def strategies() -> dict:
        return await readmodel.strategies()

    @app.get("/trades")
    async def trades(limit: int = 100) -> dict:
        return await readmodel.trades(limit)

    @app.get("/trades/{trade_id}")
    async def trade_detail(trade_id: str) -> dict:
        # 展开：当时 LLM reasoning 全文 + 信号值 + config 版本（SC-005）
        return await readmodel.trade_detail(trade_id)

    @app.get("/cognitive")
    async def cognitive() -> dict:
        return await readmodel.cognitive()

    @app.get("/health")
    async def health() -> dict:
        return await readmodel.health()

    # --- 控制（写 Redis，非直接交易）---
    @app.post("/control/pause")
    async def pause() -> dict:
        return {"id": await control.send(Command.PAUSE)}

    @app.post("/control/resume")
    async def resume() -> dict:
        return {"id": await control.send(Command.RESUME)}

    @app.post("/control/flat")
    async def flat() -> dict:
        return {"id": await control.send(Command.FLAT)}

    # --- 配置（禁改风控参数 → 403）---
    @app.post("/config/strategy")
    async def update_strategy(payload: dict) -> dict:
        try:
            editable = filter_editable(payload)
        except ForbiddenFieldError as e:
            log_event(Severity.WARN, "webui", "forbidden_edit_attempt", fields=list(payload))
            raise HTTPException(status_code=403, detail=str(e)) from e
        return {"accepted": list(editable)}

    return app
