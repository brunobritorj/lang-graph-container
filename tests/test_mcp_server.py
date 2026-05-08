import tempfile
import unittest
from pathlib import Path

from lang_graph_container import mcp_server


class MCPServerSecurityTest(unittest.TestCase):
    def test_filesystem_list_blocks_paths_outside_workspace(self) -> None:
        with self.assertRaises(ValueError):
            mcp_server.filesystem_list("../")

    def test_filesystem_list_allows_workspace_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_root = mcp_server.WORKSPACE_ROOT
            try:
                mcp_server.WORKSPACE_ROOT = temp_dir
                Path(temp_dir, "example.txt").write_text("ok", encoding="utf-8")
                listing = mcp_server.filesystem_list(".")
            finally:
                mcp_server.WORKSPACE_ROOT = original_root
        self.assertIn("example.txt", listing)

    def test_browser_fetch_rejects_non_http_schemes(self) -> None:
        with self.assertRaises(ValueError):
            mcp_server.browser_fetch("file:///etc/passwd")

    def test_browser_fetch_rejects_localhost(self) -> None:
        with self.assertRaises(ValueError):
            mcp_server.browser_fetch("http://localhost:8000")
