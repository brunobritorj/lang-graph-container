from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Any

import psycopg
from websockets.server import serve

TOOLS: dict[str, dict[str, Any]] = {}


def tool(name: str, description: str, input_schema: dict[str, Any]):
    def decorator(func):
        TOOLS[name] = {
            "callable": func,
            "definition": {
                "name": name,
                "description": description,
                "inputSchema": input_schema,
            },
        }
        return func

    return decorator


@tool(
    name="filesystem_list",
    description="List files from a directory path available to the MCP service.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
    },
)
def filesystem_list(path: str = ".") -> str:
    return json.dumps(sorted(os.listdir(path)))


@tool(
    name="browser_fetch",
    description="Fetch a URL and return a short text preview.",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
)
def browser_fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read(500).decode("utf-8", errors="replace")
    return body


@tool(
    name="postgres_health",
    description="Run a lightweight Postgres health query.",
    input_schema={"type": "object", "properties": {}},
)
def postgres_health() -> str:
    dsn = os.environ.get("POSTGRES_URL")
    if not dsn:
        return json.dumps({"status": "unconfigured"})
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select 1")
            result = cursor.fetchone()
    return json.dumps({"status": "ok", "result": result[0] if result else None})


async def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        result = {"server": {"name": "sample-mcp", "version": "0.1.0"}, "capabilities": {"tools": True}}
    elif method == "tools/list":
        result = {"tools": [definition["definition"] for definition in TOOLS.values()]}
    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        definition = TOOLS[tool_name]
        value = definition["callable"](**arguments)
        result = {"content": [{"type": "text", "text": value}]}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": f"Unknown method: {method}"}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def websocket_handler(websocket):
    async for message in websocket:
        response = await handle_request(json.loads(message))
        await websocket.send(json.dumps(response))


async def unix_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    while not reader.at_eof():
        line = await reader.readline()
        if not line:
            break
        response = await handle_request(json.loads(line.decode("utf-8")))
        writer.write((json.dumps(response) + "\n").encode("utf-8"))
        await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main() -> None:
    host = os.environ.get("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_SERVER_PORT", "8765"))
    socket_path = os.environ.get("MCP_SERVER_SOCKET_PATH")
    if socket_path:
        os.makedirs(os.path.dirname(socket_path), exist_ok=True)
        if os.path.exists(socket_path):
            os.remove(socket_path)
    async with serve(websocket_handler, host, port):
        if socket_path:
            server = await asyncio.start_unix_server(unix_handler, path=socket_path)
            async with server:
                await asyncio.Future()
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
