#!/usr/bin/env python3
"""
database.py — SQLite database layer for the AI Project Manager.

Provides schema initialization and CRUD operations for all domain objects.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from models import (
    Project, Task, AgentSession, Message, AuditEntry,
    PipelineRun, Artifact, _utcnow,
)

DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "project_manager.db"


def get_db_path() -> Path:
    env_path = os.environ.get("AIPM_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(id),
    title               TEXT NOT NULL,
    description         TEXT DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'backlog',
    priority            TEXT NOT NULL DEFAULT 'medium',
    assigned_role       TEXT,
    assigned_session_id TEXT,
    parent_task_id      INTEGER REFERENCES tasks(id),
    depends_on          TEXT DEFAULT '[]',
    tags                TEXT DEFAULT '[]',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id),
    role              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active',
    current_task_id   INTEGER REFERENCES tasks(id),
    system_prompt     TEXT DEFAULT '',
    context_history   TEXT DEFAULT '[]',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    terminated_at     TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    from_role       TEXT NOT NULL,
    to_role         TEXT NOT NULL,
    from_session_id TEXT,
    to_session_id   TEXT,
    task_id         INTEGER REFERENCES tasks(id),
    content         TEXT NOT NULL,
    message_type    TEXT DEFAULT 'text',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id),
    task_id       INTEGER REFERENCES tasks(id),
    session_id    TEXT,
    agent_role    TEXT,
    action        TEXT NOT NULL,
    details       TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id),
    task_id       INTEGER REFERENCES tasks(id),
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    triggered_by  TEXT,
    logs          TEXT DEFAULT '',
    artifact_path TEXT,
    started_at    TEXT NOT NULL,
    completed_at  TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id),
    task_id       INTEGER REFERENCES tasks(id),
    session_id    TEXT,
    name          TEXT NOT NULL,
    artifact_type TEXT DEFAULT 'code',
    content       TEXT DEFAULT '',
    file_path     TEXT,
    size_bytes    INTEGER DEFAULT 0,
    checksum      TEXT,
    created_at    TEXT NOT NULL
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON agent_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_role ON agent_sessions(role);
CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_log(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_project ON pipeline_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id);
"""


class Database:
    """SQLite database manager for the AI Project Manager."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    # ── Projects ─────────────────────────────────────────────────────────

    def create_project(self, project: Project) -> Project:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (project.id, project.name, project.description,
                 project.created_at, project.updated_at),
            )
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            return Project.from_dict(dict(row)) if row else None

    def get_active_project(self) -> Optional[Project]:
        """Get the most recently created project."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return Project.from_dict(dict(row)) if row else None

    def list_projects(self) -> list[Project]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
            return [Project.from_dict(dict(r)) for r in rows]

    # ── Tasks ────────────────────────────────────────────────────────────

    def create_task(self, task: Task) -> Task:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO tasks (project_id, title, description, status, priority, "
                "assigned_role, assigned_session_id, parent_task_id, depends_on, tags, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task.project_id, task.title, task.description, task.status,
                 task.priority, task.assigned_role, task.assigned_session_id,
                 task.parent_task_id, task.depends_on, task.tags,
                 task.created_at, task.updated_at),
            )
            task.id = cursor.lastrowid
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return Task.from_dict(dict(row)) if row else None

    def list_tasks(
        self,
        project_id: str,
        status: Optional[str] = None,
        assigned_role: Optional[str] = None,
    ) -> list[Task]:
        with self.connect() as conn:
            query = "SELECT * FROM tasks WHERE project_id = ?"
            params: list = [project_id]
            if status:
                query += " AND status = ?"
                params.append(status)
            if assigned_role:
                query += " AND assigned_role = ?"
                params.append(assigned_role)
            query += " ORDER BY priority, created_at"
            rows = conn.execute(query, params).fetchall()
            return [Task.from_dict(dict(r)) for r in rows]

    def update_task(self, task_id: int, **kwargs) -> Optional[Task]:
        if not kwargs:
            return self.get_task(task_id)
        kwargs["updated_at"] = _utcnow()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {set_clause} WHERE id = ?", values
            )
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount > 0

    # ── Agent Sessions ───────────────────────────────────────────────────

    def create_session(self, session: AgentSession) -> AgentSession:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO agent_sessions (id, project_id, role, status, "
                "current_task_id, system_prompt, context_history, created_at, "
                "updated_at, terminated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session.id, session.project_id, session.role, session.status,
                 session.current_task_id, session.system_prompt,
                 session.context_history, session.created_at,
                 session.updated_at, session.terminated_at),
            )
        return session

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return AgentSession.from_dict(dict(row)) if row else None

    def list_sessions(
        self,
        project_id: str,
        role: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[AgentSession]:
        with self.connect() as conn:
            query = "SELECT * FROM agent_sessions WHERE project_id = ?"
            params: list = [project_id]
            if role:
                query += " AND role = ?"
                params.append(role)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [AgentSession.from_dict(dict(r)) for r in rows]

    def update_session(self, session_id: str, **kwargs) -> Optional[AgentSession]:
        if not kwargs:
            return self.get_session(session_id)
        kwargs["updated_at"] = _utcnow()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [session_id]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE agent_sessions SET {set_clause} WHERE id = ?", values
            )
        return self.get_session(session_id)

    def find_active_session_for_role(
        self, project_id: str, role: str
    ) -> Optional[AgentSession]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE project_id = ? AND role = ? "
                "AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (project_id, role),
            ).fetchone()
            return AgentSession.from_dict(dict(row)) if row else None

    # ── Messages ─────────────────────────────────────────────────────────

    def create_message(self, message: Message) -> Message:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO messages (id, project_id, from_role, to_role, "
                "from_session_id, to_session_id, task_id, content, message_type, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (message.id, message.project_id, message.from_role, message.to_role,
                 message.from_session_id, message.to_session_id, message.task_id,
                 message.content, message.message_type, message.created_at),
            )
        return message

    def list_messages(
        self,
        project_id: str,
        task_id: Optional[int] = None,
        role: Optional[str] = None,
        limit: int = 50,
    ) -> list[Message]:
        with self.connect() as conn:
            query = "SELECT * FROM messages WHERE project_id = ?"
            params: list = [project_id]
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            if role:
                query += " AND (from_role = ? OR to_role = ?)"
                params.extend([role, role])
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [Message.from_dict(dict(r)) for r in rows]

    # ── Audit Log ────────────────────────────────────────────────────────

    def create_audit_entry(self, entry: AuditEntry) -> AuditEntry:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (id, project_id, task_id, session_id, "
                "agent_role, action, details, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.id, entry.project_id, entry.task_id, entry.session_id,
                 entry.agent_role, entry.action, entry.details,
                 entry.metadata_json, entry.created_at),
            )
        return entry

    def list_audit_entries(
        self,
        project_id: str,
        task_id: Optional[int] = None,
        session_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        with self.connect() as conn:
            query = "SELECT * FROM audit_log WHERE project_id = ?"
            params: list = [project_id]
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            if action:
                query += " AND action = ?"
                params.append(action)
            query += " ORDER BY created_at ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [AuditEntry.from_dict(dict(r)) for r in rows]

    # ── Pipeline Runs ────────────────────────────────────────────────────

    def create_pipeline_run(self, run: PipelineRun) -> PipelineRun:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (id, project_id, task_id, stage, status, "
                "triggered_by, logs, artifact_path, started_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.project_id, run.task_id, run.stage, run.status,
                 run.triggered_by, run.logs, run.artifact_path,
                 run.started_at, run.completed_at),
            )
        return run

    def update_pipeline_run(self, run_id: str, **kwargs) -> Optional[PipelineRun]:
        if not kwargs:
            return self.get_pipeline_run(run_id)
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [run_id]
        with self.connect() as conn:
            conn.execute(
                f"UPDATE pipeline_runs SET {set_clause} WHERE id = ?", values
            )
        return self.get_pipeline_run(run_id)

    def get_pipeline_run(self, run_id: str) -> Optional[PipelineRun]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
            ).fetchone()
            return PipelineRun.from_dict(dict(row)) if row else None

    def list_pipeline_runs(
        self, project_id: str, task_id: Optional[int] = None
    ) -> list[PipelineRun]:
        with self.connect() as conn:
            query = "SELECT * FROM pipeline_runs WHERE project_id = ?"
            params: list = [project_id]
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            query += " ORDER BY started_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [PipelineRun.from_dict(dict(r)) for r in rows]

    # ── Artifacts ────────────────────────────────────────────────────────

    def create_artifact(self, artifact: Artifact) -> Artifact:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO artifacts (id, project_id, task_id, session_id, name, "
                "artifact_type, content, file_path, size_bytes, checksum, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (artifact.id, artifact.project_id, artifact.task_id,
                 artifact.session_id, artifact.name, artifact.artifact_type,
                 artifact.content, artifact.file_path, artifact.size_bytes,
                 artifact.checksum, artifact.created_at),
            )
        return artifact

    def list_artifacts(
        self, project_id: str, task_id: Optional[int] = None
    ) -> list[Artifact]:
        with self.connect() as conn:
            query = "SELECT * FROM artifacts WHERE project_id = ?"
            params: list = [project_id]
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [Artifact.from_dict(dict(r)) for r in rows]

    # ── Statistics ───────────────────────────────────────────────────────

    def get_board_summary(self, project_id: str) -> dict:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM tasks "
                "WHERE project_id = ? GROUP BY status",
                (project_id,),
            ).fetchall()
            summary = {r["status"]: r["count"] for r in rows}

            active_agents = conn.execute(
                "SELECT COUNT(*) as count FROM agent_sessions "
                "WHERE project_id = ? AND status = 'active'",
                (project_id,),
            ).fetchone()

            total_messages = conn.execute(
                "SELECT COUNT(*) as count FROM messages WHERE project_id = ?",
                (project_id,),
            ).fetchone()

            return {
                "task_counts": summary,
                "active_agents": active_agents["count"],
                "total_messages": total_messages["count"],
            }
