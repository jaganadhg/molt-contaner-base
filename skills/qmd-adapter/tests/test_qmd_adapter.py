#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

# Add scripts dir to path (same pattern as other skill tests)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from qmd_adapter import health


class TestQmdAdapter(unittest.TestCase):
    def test_health_or_skip(self):
        """Skip when QMD MCP HTTP is not running on localhost:8181."""
        h = health()
        if h is None:
            self.skipTest("QMD MCP not reachable at http://127.0.0.1:8181")
        self.assertIsInstance(h, dict)


if __name__ == "__main__":
    unittest.main()
