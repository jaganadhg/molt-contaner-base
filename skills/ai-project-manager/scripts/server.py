#!/usr/bin/env python3
"""
server.py — HTTP server for the AI Project Manager Kanban Board UI.

Serves the Kanban board frontend and provides a REST API with
Server-Sent Events (SSE) for real-time updates.

Usage:
    python3 server.py --port 8420
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

# Ensure scripts directory is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import (
    AgentRole, TaskStatus, ROLE_EMOJI,
)
from database import Database
from kanban import KanbanBoard
from agent_manager import AgentManager
from comms import CommunicationBus
from audit import AuditTrail
from cicd import PipelineManager

# ── Globals ──────────────────────────────────────────────────────────────────

SCRIPTS_DIR = Path(__file__).resolve().parent
sse_clients: list[queue.Queue] = []
sse_lock = threading.Lock()


def broadcast_sse(event: str, data: dict):
    """Broadcast an SSE event to all connected clients."""
    message = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    with sse_lock:
        dead = []
        for q in sse_clients:
            try:
                q.put_nowait(message)
            except queue.Full:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)


# ── Request Handler ──────────────────────────────────────────────────────────


class APIHandler(BaseHTTPRequestHandler):
    db: Database = None
    project_id: str = None

    def log_message(self, format, *args):
        """Suppress default logging; use custom format."""
        sys.stderr.write(f"[AIPM] {args[0]} {args[1]} {args[2]}\n")

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _send_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        body = self.rfile.read(length)
        return json.loads(body)

    def _get_managers(self):
        pid = self.__class__.project_id
        db = self.__class__.db
        return {
            "db": db,
            "board": KanbanBoard(db, pid),
            "agents": AgentManager(db, pid),
            "comms": CommunicationBus(db, pid),
            "audit": AuditTrail(db, pid),
            "pipeline": PipelineManager(db, pid),
        }

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # ── Static assets ────────────────────────────────
        if path == "" or path == "/":
            board_html = (SCRIPTS_DIR / "board.html").read_text()
            return self._send_html(board_html)

        # ── SSE endpoint ─────────────────────────────────
        if path == "/api/events":
            return self._handle_sse()

        # ── API routes ───────────────────────────────────
        mgr = self._get_managers()

        if path == "/api/project":
            project = mgr["db"].get_project(self.__class__.project_id)
            return self._send_json(project.to_dict() if project else {})

        elif path == "/api/board":
            return self._send_json(mgr["board"].get_board_state())

        elif path == "/api/agents":
            agents = mgr["agents"].list_active_agents()
            return self._send_json({"agents": agents, "count": len(agents)})

        elif path == "/api/messages":
            task_id = int(params["task_id"][0]) if "task_id" in params else None
            limit = int(params.get("limit", [50])[0])
            messages = mgr["db"].list_messages(
                self.__class__.project_id, task_id=task_id, limit=limit
            )
            return self._send_json({
                "messages": [m.to_dict() for m in messages],
                "count": len(messages),
            })

        elif path == "/api/pipeline":
            task_id = int(params["task_id"][0]) if "task_id" in params else None
            return self._send_json(mgr["pipeline"].get_pipeline_status(task_id))

        elif path == "/api/audit":
            task_id = int(params["task_id"][0]) if "task_id" in params else None
            limit = int(params.get("limit", [100])[0])
            entries = mgr["db"].list_audit_entries(
                self.__class__.project_id, task_id=task_id, limit=limit
            )
            return self._send_json({
                "entries": [e.to_dict() for e in entries],
                "count": len(entries),
            })

        elif path.startswith("/api/task/"):
            try:
                task_id = int(path.split("/")[-1])
                details = mgr["board"].get_task_details(task_id)
                return self._send_json(details)
            except (ValueError, IndexError):
                return self._send_json({"error": "Invalid task ID"}, 400)

        elif path.startswith("/api/agent/"):
            session_id = path.split("/")[-1]
            try:
                context = mgr["agents"].get_session_context(session_id)
                return self._send_json(context)
            except ValueError as e:
                return self._send_json({"error": str(e)}, 404)

        else:
            return self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        mgr = self._get_managers()

        try:
            if path == "/api/task/create":
                task = mgr["board"].create_task(
                    title=body["title"],
                    description=body.get("description", ""),
                    priority=body.get("priority", "medium"),
                    assigned_role=body.get("assigned_role"),
                    depends_on=body.get("depends_on"),
                    tags=body.get("tags"),
                )
                self._broadcast_update(mgr)
                return self._send_json({"status": "success", "task": task.to_dict()})

            elif path == "/api/task/move":
                task = mgr["board"].move_task(body["id"], body["status"])
                self._broadcast_update(mgr)
                return self._send_json({"status": "success", "task": task.to_dict()})

            elif path == "/api/task/assign":
                task = mgr["board"].assign_task(
                    body["id"], body["role"], body.get("session_id")
                )
                self._broadcast_update(mgr)
                return self._send_json({"status": "success", "task": task.to_dict()})

            elif path == "/api/agent/spawn":
                session = mgr["agents"].spawn_agent(
                    role=body["role"],
                    task_id=body.get("task_id"),
                    custom_prompt=body.get("prompt"),
                )
                self._broadcast_update(mgr)
                return self._send_json({"status": "success", "session": session.to_dict()})

            elif path == "/api/agent/terminate":
                session = mgr["agents"].terminate_agent(
                    body["session_id"], reason=body.get("reason", "")
                )
                self._broadcast_update(mgr)
                return self._send_json({"status": "success", "session": session.to_dict()})

            elif path == "/api/message":
                msg = mgr["comms"].send_message(
                    from_role=body["from_role"],
                    to_role=body["to_role"],
                    content=body["content"],
                    task_id=body.get("task_id"),
                    message_type=body.get("message_type", "text"),
                )
                self._broadcast_update(mgr)
                return self._send_json({"status": "success", "message": msg.to_dict()})

            elif path == "/api/pipeline/run":
                run = mgr["pipeline"].trigger_stage(
                    stage=body.get("stage", "build"),
                    task_id=body.get("task_id"),
                    triggered_by=body.get("triggered_by"),
                    config=body.get("config", {}),
                )
                self._broadcast_update(mgr)
                return self._send_json({"status": "success", "run": run.to_dict()})

            else:
                return self._send_json({"error": "Not found"}, 404)

        except ValueError as e:
            return self._send_json({"error": str(e)}, 400)
        except KeyError as e:
            return self._send_json({"error": f"Missing field: {e}"}, 400)
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def _handle_sse(self):
        """Handle Server-Sent Events connection."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        client_queue = queue.Queue(maxsize=100)
        with sse_lock:
            sse_clients.append(client_queue)
            sys.stderr.write(f"[AIPM] SSE client connected (clients={len(sse_clients)})\n")

        try:
            # Send initial state
            mgr = self._get_managers()
            initial_board = mgr["board"].get_board_state()
            self.wfile.write(
                f"event: board_update\ndata: {json.dumps(initial_board)}\n\n".encode()
            )
            self.wfile.flush()

            # Keep connection alive
            while True:
                try:
                    message = client_queue.get(timeout=15)
                    self.wfile.write(message.encode())
                    self.wfile.flush()
                except queue.Empty:
                    # Send heartbeat
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with sse_lock:
                if client_queue in sse_clients:
                    sse_clients.remove(client_queue)
            sys.stderr.write(f"[AIPM] SSE client disconnected (clients={len(sse_clients)})\n")

    def _broadcast_update(self, mgr: dict):
        """Broadcast updates to all SSE clients."""
        try:
            board_state = mgr["board"].get_board_state()
            broadcast_sse("board_update", board_state)

            agents = mgr["agents"].list_active_agents()
            broadcast_sse("agent_update", agents)

            messages = mgr["db"].list_messages(
                self.__class__.project_id, limit=20
            )
            broadcast_sse("message_update", [m.to_dict() for m in messages])

            pipeline = mgr["pipeline"].get_pipeline_status()
            broadcast_sse("pipeline_update", pipeline)
        except Exception as e:
            sys.stderr.write(f"[AIPM] SSE broadcast error: {e}\n")


# ── Server Setup ─────────────────────────────────────────────────────────────


def run_server(port: int = 8420, host: str = "0.0.0.0"):
    """Start the HTTP server."""
    db = Database()
    db.init_schema()

    project = db.get_active_project()
    if not project:
        print("⚠️  No project found. Creating default project...")
        from models import Project
        project = db.create_project(Project(name="Default Project"))

    # Set class-level attributes
    APIHandler.db = db
    APIHandler.project_id = project.id

    # Auto-spawn common team sessions if they don't already exist
    try:
        from agent_manager import AgentManager
        am = AgentManager(db, project.id)
        default_team = ["planner", "coder", "tester", "reviewer", "security"]
        spawned = []
        for role in default_team:
            if not db.find_active_session_for_role(project.id, role):
                try:
                    s = am.spawn_agent(role=role)
                    spawned.append(s.id)
                except Exception as e:
                    sys.stderr.write(f"[AIPM] Failed to spawn default role '{role}': {e}\n")
        if spawned:
            print(f"✅ Auto-spawned default team sessions: {', '.join(spawned)}")
    except Exception as e:
        sys.stderr.write(f"[AIPM] Auto-spawn skipped/error: {e}\n")

    server = HTTPServer((host, port), APIHandler)

    print(f"🧠 AI Project Manager — Kanban Board")
    print(f"   Project: {project.name}")
    print(f"   Server:  http://localhost:{port}")
    print(f"   API:     http://localhost:{port}/api")
    print(f"   SSE:     http://localhost:{port}/api/events")
    print(f"\n   Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description="AI Project Manager — Kanban Board Server"
    )
    parser.add_argument(
        "--port", type=int, default=8420,
        help="Port to listen on (default: 8420)"
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)


if __name__ == "__main__":
    main()
