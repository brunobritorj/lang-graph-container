from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


def merge_agent_memory(
    left: dict[str, list[str]] | None, right: dict[str, list[str]] | None
) -> dict[str, list[str]]:
    merged = {key: list(value) for key, value in (left or {}).items()}
    for agent_name, entries in (right or {}).items():
        merged.setdefault(agent_name, [])
        merged[agent_name].extend(entries)
    return merged


class GraphState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    active_agent: str
    next_agent: str | None
    agent_memory: Annotated[dict[str, list[str]], merge_agent_memory]
