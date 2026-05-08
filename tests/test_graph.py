import unittest

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from lang_graph_container.config import AppSettings
from lang_graph_container.graph import build_multi_agent_graph, create_initial_state


def filesystem_list(path: str | None = None) -> str:
    return path or "."


def browser_fetch(url: str) -> str:
    return url


class GraphBuildTest(unittest.TestCase):
    def test_graph_compiles_with_shared_tool_node(self) -> None:
        settings = AppSettings()
        tools = [
            StructuredTool.from_function(filesystem_list, name="filesystem_list", description="List files."),
            StructuredTool.from_function(browser_fetch, name="browser_fetch", description="Fetch URL."),
        ]

        def fake_factory(agent, allowed_tools):
            def node(state):
                return {
                    "messages": [AIMessage(content=f"handled by {agent.name}")],
                    "active_agent": agent.name,
                    "next_agent": agent.default_next_agent,
                    "agent_memory": {agent.name: [tool.name for tool in allowed_tools]},
                }

            return node

        graph = build_multi_agent_graph(settings, tools, agent_node_factory=fake_factory).compile()
        result = graph.invoke(create_initial_state("Build the plan"))
        self.assertEqual(result["messages"][-1].content, "handled by executor")
        self.assertEqual(
            [message.content for message in result["messages"][1:]],
            ["handled by planner", "handled by researcher", "handled by executor"],
        )
        self.assertIn("filesystem_list", result["agent_memory"]["planner"])

    def test_tool_filtering_respects_agent_permissions(self) -> None:
        settings = AppSettings()
        settings.agent_configs[0].allowed_tools = ["filesystem_list"]
        tools = [
            StructuredTool.from_function(filesystem_list, name="filesystem_list", description="List files."),
            StructuredTool.from_function(browser_fetch, name="browser_fetch", description="Fetch URL."),
        ]
        seen = {}

        def fake_factory(agent, allowed_tools):
            seen[agent.name] = [tool.name for tool in allowed_tools]

            def node(state):
                return {
                    "messages": [AIMessage(content=agent.name)],
                    "active_agent": agent.name,
                    "next_agent": agent.default_next_agent,
                    "agent_memory": {},
                }

            return node

        build_multi_agent_graph(settings, tools, agent_node_factory=fake_factory)
        self.assertEqual(seen["planner"], ["filesystem_list"])
        self.assertEqual(seen["researcher"], ["filesystem_list", "browser_fetch"])
