from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
import urllib.request
from urllib.parse import urlparse
from typing import Any

import psycopg
from websockets.server import serve

TOOLS: dict[str, dict[str, Any]] = {}
WORKSPACE_ROOT = os.path.realpath(os.environ.get("MCP_SERVER_WORKSPACE", os.getcwd()))
MAX_PREVIEW_BYTES = 500


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects are not allowed.")


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
    requested_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, path))
    if os.path.commonpath([WORKSPACE_ROOT, requested_path]) != WORKSPACE_ROOT:
        raise ValueError("Path is outside the allowed workspace.")
    return json.dumps(sorted(os.listdir(requested_path)))


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
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed.")
    if not parsed.hostname:
        raise ValueError("A hostname is required.")
    if parsed.hostname in {"localhost"}:
        raise ValueError("Localhost is not allowed.")
    try:
        resolved_addresses = {
            info[4][0]
            for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except socket.gaierror as exc:
        raise ValueError(f"Unable to resolve host: {parsed.hostname}") from exc
    for address in resolved_addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Target host resolves to a private or otherwise blocked address.")
    opener = urllib.request.build_opener(NoRedirectHandler)
    with opener.open(url, timeout=10) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_PREVIEW_BYTES:
            raise ValueError("Response body is too large.")
        body = response.read(MAX_PREVIEW_BYTES + 1)
        if len(body) > MAX_PREVIEW_BYTES:
            raise ValueError("Response body is too large.")
        body = body.decode("utf-8", errors="replace")
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
        try:
            value = definition["callable"](**arguments)
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": str(exc),
            }
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
    host = os.environ.get("MCP_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_SERVER_PORT", "8765"))
    socket_path = os.environ.get("MCP_SERVER_SOCKET_PATH")
    if socket_path:
        directory = os.path.dirname(socket_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if os.path.exists(socket_path):
            os.remove(socket_path)
    shutdown = asyncio.Event()
    async with serve(websocket_handler, host, port):
        if socket_path:
            server = await asyncio.start_unix_server(unix_handler, path=socket_path)
            async with server:
                await shutdown.wait()
        else:
            await shutdown.wait()


if __name__ == "__main__":
    asyncio.run(main())
