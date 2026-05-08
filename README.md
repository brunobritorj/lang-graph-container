# lang-graph-container

A minimal local LangGraph scaffold for orchestrating multiple custom Azure OpenAI agents behind a shared MCP-backed tool layer.

## What is included

- A three-agent LangGraph state machine (`planner -> researcher -> executor`)
- Per-agent Azure OpenAI deployment names, prompts, and allowed tool lists
- A shared `ToolNode` fed by tools discovered from a single external MCP endpoint
- MCP connectivity over either WebSocket or Unix socket
- Redis-backed event publishing for streamed run updates
- Postgres-backed LangGraph checkpoint persistence
- Docker Compose services for the app, Redis, Postgres, and a sample MCP server
- Focused unit tests for settings parsing and graph construction

## Project layout

- `lang_graph_container/app.py` – FastAPI app with `/healthz` and `/runs`
- `lang_graph_container/config.py` – environment-driven app and agent settings
- `lang_graph_container/graph.py` – LangGraph state machine and shared `ToolNode`
- `lang_graph_container/mcp_client.py` – lightweight MCP tool discovery + invocation adapter
- `lang_graph_container/mcp_server.py` – sample external MCP server exposing filesystem, browser, and Postgres tools
- `lang_graph_container/runtime.py` – graph startup, Redis publishing, and Postgres checkpoint wiring
- `docker-compose.yml` – local stack wiring

## Configuration

Copy `.env.example` to `.env` and provide Azure credentials:

```bash
cp .env.example .env
```

Important variables:

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_VERSION`
- `POSTGRES_URL`
- `REDIS_URL`
- `MCP_TRANSPORT=websocket|unix`
- `MCP_WEBSOCKET_URL`
- `MCP_UNIX_SOCKET_PATH`
- `LANGGRAPH_AGENT_CONFIG_JSON` – JSON array describing each agent node

Example agent config payload:

```json
[
  {
    "name": "planner",
    "azure_deployment": "gpt-4o-mini",
    "system_prompt": "Plan the task and decide whether tools are needed.",
    "allowed_tools": ["filesystem_list", "browser_fetch", "postgres_health"],
    "default_next_agent": "researcher"
  },
  {
    "name": "researcher",
    "azure_deployment": "gpt-4o-mini",
    "system_prompt": "Reason over evidence and prepare execution-ready context.",
    "allowed_tools": ["filesystem_list", "browser_fetch", "postgres_health"],
    "default_next_agent": "executor"
  },
  {
    "name": "executor",
    "azure_deployment": "gpt-4o",
    "system_prompt": "Produce the final answer.",
    "allowed_tools": ["filesystem_list", "browser_fetch", "postgres_health"]
  }
]
```

## Run locally with Docker Compose

```bash
docker compose up --build
```

This starts:

- `app` on `http://localhost:8000`
- `postgres` on `localhost:5432`
- `redis` on `localhost:6379`
- `mcp-server` on `ws://localhost:8765/mcp` plus a shared Unix socket volume

## API usage

Check health:

```bash
curl http://localhost:8000/healthz
```

Run the graph:

```bash
curl -X POST http://localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"prompt":"Inspect the workspace and summarize the stack."}'
```

Each run publishes intermediate state snapshots to `Redis` using the channel pattern `langgraph:runs:<thread_id>`, while LangGraph checkpoints are stored in Postgres.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Notes

- The sample MCP server is intentionally small but demonstrates the shared provider pattern used by all agents.
- Switching `MCP_TRANSPORT` to `unix` makes the client connect through the shared socket instead of WebSocket.
- Agent behavior is isolated per node: prompts, model deployment, routing, memory accumulation, and allowed tool access are all configured independently.
