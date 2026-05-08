from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import AzureChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .config import AgentConfig, AppSettings
from .state import GraphState

AgentNodeFactory = Callable[[AgentConfig, list[BaseTool]], Callable[[GraphState], dict[str, Any]]]
MEMORY_WINDOW_SIZE = 5


def route_from_agent(profile: AgentConfig, state: GraphState) -> str:
    last_message = state.get("messages", [])[-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return profile.default_next_agent or END


def _memory_for_agent(state: GraphState, agent_name: str) -> str:
    memory = state.get("agent_memory", {}).get(agent_name, [])
    return "\n".join(f"- {item}" for item in memory[-MEMORY_WINDOW_SIZE:]) or "- No memory yet"


def default_agent_node_factory(settings: AppSettings) -> AgentNodeFactory:
    def factory(agent: AgentConfig, tools: list[BaseTool]) -> Callable[[GraphState], dict[str, Any]]:
        llm = AzureChatOpenAI(
            azure_deployment=agent.azure_deployment,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            temperature=0,
        )
        bound_llm = llm.bind_tools(tools)

        def invoke_agent(state: GraphState) -> dict[str, Any]:
            messages = state.get("messages", [])
            response = bound_llm.invoke(
                [
                    SystemMessage(
                        content=(
                            f"{agent.system_prompt}\n\n"
                            f"Agent name: {agent.name}\n"
                            f"Shared-memory snapshot:\n{_memory_for_agent(state, agent.name)}"
                        )
                    ),
                    *messages,
                ]
            )
            memory = dict(state.get("agent_memory", {}))
            memory.setdefault(agent.name, []).append(getattr(response, "content", ""))
            return {
                "messages": [response],
                "active_agent": agent.name,
                "next_agent": agent.default_next_agent,
                "agent_memory": memory,
            }

        return invoke_agent

    return factory


def build_multi_agent_graph(
    settings: AppSettings,
    shared_tools: list[BaseTool],
    agent_node_factory: AgentNodeFactory | None = None,
):
    graph = StateGraph(GraphState)
    tool_node = ToolNode(shared_tools)
    factory = agent_node_factory or default_agent_node_factory(settings)

    for agent in settings.agent_configs:
        allowed = [tool for tool in shared_tools if not agent.allowed_tools or tool.name in agent.allowed_tools]
        graph.add_node(agent.name, factory(agent, allowed))

    graph.add_node("tools", tool_node)
    graph.add_edge(START, settings.agent_configs[0].name)

    def route_after_tool(state: GraphState) -> str:
        return state.get("active_agent") or END

    for agent in settings.agent_configs:
        destinations = {"tools": "tools", END: END}
        if agent.default_next_agent:
            destinations[agent.default_next_agent] = agent.default_next_agent
        graph.add_conditional_edges(agent.name, partial(route_from_agent, agent), destinations)

    graph.add_conditional_edges(
        "tools",
        route_after_tool,
        {agent.name: agent.name for agent in settings.agent_configs},
    )
    return graph


def create_initial_state(prompt: str) -> GraphState:
    return {
        "messages": [HumanMessage(content=prompt)],
        "agent_memory": {},
        "next_agent": None,
    }
