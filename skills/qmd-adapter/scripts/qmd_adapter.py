"""Minimal QMD MCP/HTTP helper used by the `qmd-adapter` skill.

Provides:
- health(host) -> dict|None
- mcp_call(tool, args) -> dict (raw JSON response) -- best-effort wrapper
- search(query, n=5) -> dict (delegates to qmd MCP)

The functions use only the Python standard library so no extra deps are required.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

DEFAULT_HOST = "http://127.0.0.1:8181"


def health(host: str = DEFAULT_HOST, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """Return QMD /health JSON or None if unreachable."""
    url = host.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def mcp_call(tool: str, args: Optional[Dict[str, Any]] = None, host: str = DEFAULT_HOST, timeout: float = 10.0) -> Dict[str, Any]:
    """POST a best-effort MCP/HTTP JSON payload to QMD and return the parsed JSON response.

    Note: QMD exposes multiple MCP tools (qmd_search, qmd_vector_search, qmd_get, ...).
    This wrapper uses a permissive payload shape so it can be adapted quickly by callers.
    """
    payload = {"tool": tool, "args": args or {}}
    body = json.dumps(payload).encode("utf-8")
    url = host.rstrip("/") + "/mcp"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # Try to parse JSON; if QMD streams NDJSON, this will still capture the first object.
        text = resp.read().decode("utf-8", errors="ignore").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            # Fallback: return raw text when JSON decode fails
            return {"raw": text}


def search(query: str, n: int = 5, mode: str = "query", host: str = DEFAULT_HOST) -> Dict[str, Any]:
    """Convenience wrapper to run a QMD search via MCP.

    mode: one of 'search'|'vsearch'|'query' depending on QMD build.
    """
    tool_map = {
        "search": "qmd_search",
        "vsearch": "qmd_vector_search",
        "query": "qmd_deep_search",
    }
    tool = tool_map.get(mode, "qmd_deep_search")
    args = {"query": query, "n": n}
    return mcp_call(tool, args=args, host=host)


def get(path_or_docid: str, host: str = DEFAULT_HOST) -> Dict[str, Any]:
    """Fetch a document by path or docid via `qmd_get`."""
    return mcp_call("qmd_get", args={"id": path_or_docid}, host=host)
