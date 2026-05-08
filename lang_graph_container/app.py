from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from .config import AppSettings
from .runtime import LangGraphRuntime


settings = AppSettings()
runtime = LangGraphRuntime(settings)


class RunRequest(BaseModel):
    prompt: str
    thread_id: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="lang-graph-container", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "mcp_transport": settings.mcp_transport,
        "mcp_endpoint": settings.get_mcp_endpoint(),
        "agents": [agent.model_dump() for agent in settings.agent_configs],
        "shared_tools": runtime.tool_names,
    }


@app.post("/runs")
async def run_graph(request: RunRequest) -> dict[str, object]:
    return await runtime.invoke(request.prompt, request.thread_id)
