#!/usr/bin/env python3
"""
config.py — Configuration for the AI Project Manager skill.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
DATA_DIR = SKILL_DIR / "data"
WORKSPACE_DIR = SKILL_DIR / "workspace"

# ── Database ─────────────────────────────────────────────────────────────────

DB_PATH = Path(os.environ.get("AIPM_DB_PATH", str(DATA_DIR / "project_manager.db")))

# ── Server ───────────────────────────────────────────────────────────────────

SERVER_HOST = os.environ.get("AIPM_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("AIPM_PORT", "8420"))

# ── Pipeline ─────────────────────────────────────────────────────────────────

# GitHub Actions webhook (optional)
GITHUB_WEBHOOK_URL = os.environ.get("AIPM_GITHUB_WEBHOOK")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# GitLab CI webhook (optional)
GITLAB_WEBHOOK_URL = os.environ.get("AIPM_GITLAB_WEBHOOK")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")

# Generic webhook
WEBHOOK_URL = os.environ.get("AIPM_WEBHOOK_URL")

# ── Agent Defaults ───────────────────────────────────────────────────────────

# Maximum context history entries per agent session
MAX_CONTEXT_HISTORY = int(os.environ.get("AIPM_MAX_CONTEXT", "60"))

# Maximum concurrent agent sessions
MAX_CONCURRENT_AGENTS = int(os.environ.get("AIPM_MAX_AGENTS", "10"))

# ── Audit ────────────────────────────────────────────────────────────────────

# Enable/disable audit logging
AUDIT_ENABLED = os.environ.get("AIPM_AUDIT_ENABLED", "true").lower() == "true"

# Maximum audit entries to keep
MAX_AUDIT_ENTRIES = int(os.environ.get("AIPM_MAX_AUDIT", "10000"))
