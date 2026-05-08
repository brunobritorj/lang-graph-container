from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis import asyncio as redis_async

from .config import AppSettings
from .graph import build_multi_agent_graph, create_initial_state
from .mcp_client import load_mcp_tools


class RedisStreamPublisher:
    def __init__(self, redis_url: str | None, prefix: str):
        self.redis_url = redis_url
        self.prefix = prefix
        self.client = redis_async.from_url(redis_url) if redis_url else None

    async def publish(self, thread_id: str, payload: dict[str, Any]) -> None:
        if not self.client:
            return
        await self.client.publish(f"{self.prefix}:{thread_id}", json.dumps(payload, default=str))

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()


class LangGraphRuntime:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._stack = AsyncExitStack()
        self.publisher = RedisStreamPublisher(settings.redis_url, settings.redis_stream_prefix)
        self.app = None
        self.tool_names: list[str] = []

    async def start(self) -> None:
        tools = await load_mcp_tools(self.settings)
        self.tool_names = [tool.name for tool in tools]
        graph = build_multi_agent_graph(self.settings, tools)
        if self.settings.postgres_url:
            saver = await self._stack.enter_async_context(
                AsyncPostgresSaver.from_conn_string(self.settings.postgres_url)
            )
            await saver.setup()
            self.app = graph.compile(checkpointer=saver)
        else:
            self.app = graph.compile()

    async def stop(self) -> None:
        await self.publisher.close()
        await self._stack.aclose()

    async def invoke(self, prompt: str, thread_id: str | None = None) -> dict[str, Any]:
        if self.app is None:
            raise RuntimeError("Runtime has not been started.")
        resolved_thread_id = thread_id or self.settings.new_thread_id()
        config = {"configurable": {"thread_id": resolved_thread_id}}
        last_value = None
        try:
            async for value in self.app.astream(
                create_initial_state(prompt),
                config=config,
                stream_mode="values",
            ):
                last_value = value
                await self.publisher.publish(resolved_thread_id, value)
        except Exception as exc:
            await self.publisher.publish(
                resolved_thread_id,
                {"error": str(exc), "thread_id": resolved_thread_id},
            )
            raise
        final_message = ""
        messages = last_value.get("messages") if last_value else None
        if messages:
            final_message = getattr(messages[-1], "content", "")
        return {
            "thread_id": resolved_thread_id,
            "tool_names": self.tool_names,
            "final_message": final_message,
            "state": last_value,
        }
