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
    """Return QMD /health JSON or None if unreachable.

    Falls back to the local `qmd` CLI when the HTTP MCP is unavailable.
    """
    url = host.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        # HTTP unreachable — try CLI fallback
        try:
            import shutil, subprocess
            qmd_bin = shutil.which("qmd")
            if not qmd_bin:
                return None
            # Prefer `qmd status --json` if available, else `qmd --version` as a liveness check
            try:
                p = subprocess.run([qmd_bin, "status", "--json"], capture_output=True, text=True, timeout=timeout)
                if p.returncode == 0 and p.stdout:
                    try:
                        return json.loads(p.stdout)
                    except Exception:
                        return {"cli": True, "raw": p.stdout.strip()}
            except Exception:
                pass

            # Fallback to version output
            p = subprocess.run([qmd_bin, "--version"], capture_output=True, text=True, timeout=timeout)
            if p.returncode == 0:
                return {"cli": True, "version": p.stdout.strip()}
        except Exception:
            return None
        return None


def mcp_call(tool: str, args: Optional[Dict[str, Any]] = None, host: str = DEFAULT_HOST, timeout: float = 10.0) -> Dict[str, Any]:
    """POST a best-effort MCP/HTTP JSON payload to QMD and return the parsed JSON response.

    Behavior:
    1. Try HTTP MCP at `host`.
    2. If HTTP fails and a `qmd` CLI is available, run the equivalent `qmd` CLI command as a fallback.

    The CLI fallback supports common tools: `qmd_search`, `qmd_vector_search`,
    `qmd_deep_search`, and `qmd_get`.
    """
    payload = {"tool": tool, "args": args or {}}

    # 1) Try HTTP MCP first
    try:
        body = json.dumps(payload).encode("utf-8")
        url = host.rstrip("/") + "/mcp"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore").strip()
            if not text:
                return {}
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}
    except Exception:
        # Fall through to CLI fallback
        pass

    # 2) CLI fallback
    try:
        import shutil, subprocess
        qmd_bin = shutil.which("qmd")
        if not qmd_bin:
            return {"error": "qmd HTTP unreachable and qmd CLI not found"}

        # Map MCP tool -> CLI command + arg builder
        def _arg_list_for(tool_name: str, a: Dict[str, Any]):
            if tool_name in ("qmd_search",):
                return ["search", a.get("query", ""), "-n", str(a.get("n", 5)), "--json"]
            if tool_name in ("qmd_vector_search",):
                return ["vsearch", a.get("query", ""), "-n", str(a.get("n", 5)), "--json"]
            if tool_name in ("qmd_deep_search",):
                return ["query", a.get("query", ""), "-n", str(a.get("n", 5)), "--json"]
            if tool_name in ("qmd_get",):
                return ["get", a.get("id", a.get("path", "")), "--full", "--json"]
            return None

        cli_args = _arg_list_for(tool, args or {})
        if cli_args is None:
            return {"error": "no CLI fallback available for tool", "tool": tool}

        cmd = [qmd_bin] + cli_args
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            return {"error": "qmd CLI failed", "rc": p.returncode, "stderr": p.stderr.strip()}
        out = p.stdout.strip()
        if not out:
            return {}
        try:
            return json.loads(out)
        except Exception:
            return {"raw": out}

    except Exception as exc:
        return {"error": "fallback failed", "exc": str(exc)}


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
