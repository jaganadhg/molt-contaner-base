# QMD Adapter

Lightweight skill that integrates an external QMD MCP/HTTP daemon with the workspace.

Purpose
- Provide a minimal wrapper the OpenClaw workspace can use to query a running `qmd mcp --http` server.

Files
- `scripts/qmd_adapter.py` — tiny HTTP client for QMD `/health` + `/mcp` endpoints
- `scripts/cli.py` — CLI for manual smoke checks (`health`, `search`)
- `tests/test_qmd_adapter.py` — smoke test (skips if QMD not running)

Usage
1. Run a QMD MCP server: `qmd mcp --http --port 8181 --daemon` (or use the provided `podman-compose-ollama.yml` service `qmd`).
2. From the workspace run: `python3 skills/qmd-adapter/scripts/cli.py health` to check liveness.
3. Use the `qmd_adapter` functions from other skills to call QMD.

Notes
- This is intentionally small and non-invasive — it does not change OpenClaw core. Use as a skill/utility while developing a fuller adapter.
