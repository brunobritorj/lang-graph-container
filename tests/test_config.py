import json
import os
import unittest

from lang_graph_container.config import AppSettings


class AppSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "LANGGRAPH_AGENT_CONFIG_JSON",
                "MCP_TRANSPORT",
                "MCP_WEBSOCKET_URL",
                "MCP_UNIX_SOCKET_PATH",
            )
        }

    def tearDown(self) -> None:
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_defaults_include_multi_agent_pipeline(self) -> None:
        settings = AppSettings()
        self.assertEqual([agent.name for agent in settings.agent_configs], ["planner", "researcher", "executor"])
        self.assertEqual(settings.agent_configs[0].default_next_agent, "researcher")

    def test_json_agent_configuration_overrides_defaults(self) -> None:
        os.environ["LANGGRAPH_AGENT_CONFIG_JSON"] = json.dumps(
            [
                {
                    "name": "router",
                    "azure_deployment": "gpt-test",
                    "system_prompt": "route",
                    "allowed_tools": ["filesystem_list"],
                }
            ]
        )
        settings = AppSettings()
        self.assertEqual([agent.name for agent in settings.agent_configs], ["router"])

    def test_mcp_endpoint_switches_between_websocket_and_unix(self) -> None:
        os.environ["MCP_TRANSPORT"] = "unix"
        os.environ["MCP_UNIX_SOCKET_PATH"] = "/tmp/custom.sock"
        settings = AppSettings()
        self.assertEqual(settings.get_mcp_endpoint(), "/tmp/custom.sock")
