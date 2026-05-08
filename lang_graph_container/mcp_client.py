from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, create_model
from websockets import connect as websocket_connect

from langchain_core.tools import StructuredTool

from .config import AppSettings

JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class MCPToolSpec(BaseModel):
    name: str
    description: str
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class MCPClient:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        if self.settings.mcp_transport == "websocket":
            async with websocket_connect(self.settings.mcp_websocket_url) as websocket:
                await websocket.send(json.dumps(request))
                raw = await websocket.recv()
        else:
            reader, writer = await asyncio.open_unix_connection(self.settings.mcp_unix_socket_path)
            writer.write((json.dumps(request) + "\n").encode("utf-8"))
            await writer.drain()
            raw = await reader.readline()
            writer.close()
            await writer.wait_closed()
        response = json.loads(raw)
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    async def initialize(self) -> dict[str, Any]:
        return await self._request("initialize", {"client": "lang-graph-container"})

    async def list_tools(self) -> list[MCPToolSpec]:
        await self.initialize()
        result = await self._request("tools/list")
        return [MCPToolSpec.model_validate(tool) for tool in result.get("tools", [])]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        result = await self._request("tools/call", {"name": tool_name, "arguments": arguments})
        content = result.get("content", [])
        if not content:
            return ""
        return "\n".join(item.get("text", "") for item in content)


def _create_args_schema(tool: MCPToolSpec):
    properties = tool.inputSchema.get("properties", {})
    required = set(tool.inputSchema.get("required", []))
    fields = {}
    for name, schema in properties.items():
        annotation = JSON_TYPE_MAP.get(schema.get("type", "string"), str)
        default = ... if name in required else None
        fields[name] = (annotation, default)
    if not fields:
        fields["input"] = (str, None)
    normalized_name = "".join(character for character in tool.name.title() if character.isalnum())
    suffix = hashlib.sha256(tool.name.encode("utf-8")).hexdigest()[:8]
    model_name = f"{normalized_name or 'Tool'}Args{suffix}"
    return create_model(model_name, **fields)


async def load_mcp_tools(settings: AppSettings) -> list[StructuredTool]:
    client = MCPClient(settings)
    tool_specs = await client.list_tools()
    tools: list[StructuredTool] = []

    def make_tool_coroutine(tool_name: str):
        async def _arun(**kwargs: Any) -> str:
            return await client.call_tool(tool_name, kwargs)

        return _arun

    for spec in tool_specs:
        args_schema = _create_args_schema(spec)

        tools.append(
            StructuredTool.from_function(
                coroutine=make_tool_coroutine(spec.name),
                name=spec.name,
                description=spec.description,
                args_schema=args_schema,
            )
        )
    return tools
