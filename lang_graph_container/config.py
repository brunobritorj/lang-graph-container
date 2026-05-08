from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseModel):
    name: str
    azure_deployment: str
    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    default_next_agent: str | None = None


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    postgres_url: str | None = None
    redis_url: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-02-01"
    mcp_transport: Literal["websocket", "unix"] = "websocket"
    mcp_websocket_url: str = "ws://localhost:8765/mcp"
    mcp_unix_socket_path: str = "/tmp/mcp.sock"
    langgraph_agent_config_json: str | None = None
    agent_configs: list[AgentConfig] = Field(default_factory=list)
    redis_stream_prefix: str = "langgraph:runs"

    @model_validator(mode="before")
    @classmethod
    def populate_agent_configs(cls, data: dict) -> dict:
        payload = data.get("langgraph_agent_config_json")
        if payload and not data.get("agent_configs"):
            data["agent_configs"] = json.loads(payload)
        if not data.get("agent_configs"):
            data["agent_configs"] = [
                {
                    "name": "planner",
                    "azure_deployment": "gpt-4o-mini",
                    "system_prompt": "Plan the job, decide whether shared MCP tools are needed, and keep the task breakdown concise.",
                    "allowed_tools": ["filesystem_list", "browser_fetch", "postgres_health"],
                    "default_next_agent": "researcher",
                },
                {
                    "name": "researcher",
                    "azure_deployment": "gpt-4o-mini",
                    "system_prompt": "Reason over prior tool results and working memory before handing the task to the executor.",
                    "allowed_tools": ["filesystem_list", "browser_fetch", "postgres_health"],
                    "default_next_agent": "executor",
                },
                {
                    "name": "executor",
                    "azure_deployment": "gpt-4o",
                    "system_prompt": "Produce the final answer, using tools only when more evidence is required.",
                    "allowed_tools": ["filesystem_list", "browser_fetch", "postgres_health"],
                },
            ]
        return data

    def get_mcp_endpoint(self) -> str:
        return self.mcp_websocket_url if self.mcp_transport == "websocket" else self.mcp_unix_socket_path

    def new_thread_id(self) -> str:
        return uuid4().hex
