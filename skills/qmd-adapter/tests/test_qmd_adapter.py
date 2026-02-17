#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

# Add scripts dir to path (same pattern as other skill tests)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from qmd_adapter import health, mcp_call
from unittest import mock
import urllib.error


class TestQmdAdapter(unittest.TestCase):
    def test_health_or_skip(self):
        """Skip when QMD MCP HTTP is not running on localhost:8181."""
        h = health()
        if h is None:
            self.skipTest("QMD MCP not reachable at http://127.0.0.1:8181")
        self.assertIsInstance(h, dict)

    def test_health_cli_fallback(self):
        """When HTTP health fails, CLI `qmd --version` is used as fallback."""
        # Simulate HTTP failure and a CLI present that returns version
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no http")):
            with mock.patch("shutil.which", return_value="/usr/bin/qmd"):
                fake = mock.Mock()
                fake.returncode = 0
                fake.stdout = "qmd v0.9.0\n"
                with mock.patch("subprocess.run", return_value=fake):
                    h = health(host="http://127.0.0.1:9999")
                    self.assertIsInstance(h, dict)
                    self.assertTrue(h.get("cli") or "version" in h)

    def test_mcp_call_cli_fallback_search(self):
        """If HTTP MCP fails, mcp_call falls back to the `qmd` CLI equivalent."""
        # Cause HTTP to fail
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no http")):
            # Pretend qmd CLI exists
            with mock.patch("shutil.which", return_value="/usr/bin/qmd"):
                fake = mock.Mock()
                fake.returncode = 0
                fake.stdout = '{"matches": [{"path": "docs/x.md", "score": 0.9}]}'
                with mock.patch("subprocess.run", return_value=fake) as run_mock:
                    res = mcp_call("qmd_deep_search", args={"query": "deploy", "n": 3}, host="http://127.0.0.1:9999")
                    self.assertIsInstance(res, dict)
                    self.assertIn("matches", res)
                    # Ensure subprocess.run was called with the expected CLI command
                    called_cmd = run_mock.call_args[0][0]
                    self.assertTrue(any("query" in c for c in called_cmd))


if __name__ == "__main__":
    unittest.main()
