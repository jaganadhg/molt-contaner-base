#!/usr/bin/env python3
"""
kanban.py — Kanban board manager for the AI Project Manager.

Handles task lifecycle, column transitions, and board state queries.
"""

from __future__ import annotations

import json
from typing import Optional

from models import (
    Task, TaskStatus, TaskPriority, AuditEntry, AuditAction,
    AgentRole, ROLE_EMOJI, _utcnow,
)
from database import Database


# Valid state transitions for the Kanban board
VALID_TRANSITIONS = {
    TaskStatus.BACKLOG.value: [TaskStatus.IN_PROGRESS.value, TaskStatus.BLOCKED.value],
    TaskStatus.IN_PROGRESS.value: [
        TaskStatus.REVIEW.value, TaskStatus.BLOCKED.value, TaskStatus.BACKLOG.value,
    ],
    TaskStatus.REVIEW.value: [
        TaskStatus.DONE.value, TaskStatus.IN_PROGRESS.value, TaskStatus.BLOCKED.value,
    ],
    TaskStatus.BLOCKED.value: [
        TaskStatus.BACKLOG.value, TaskStatus.IN_PROGRESS.value,
    ],
    TaskStatus.DONE.value: [TaskStatus.BACKLOG.value],  # reopen
}

COLUMN_EMOJI = {
    TaskStatus.BACKLOG.value: "📥",
    TaskStatus.IN_PROGRESS.value: "🔄",
    TaskStatus.REVIEW.value: "👀",
    TaskStatus.DONE.value: "✅",
    TaskStatus.BLOCKED.value: "🚫",
}


class KanbanBoard:
    """Manages the Kanban board for a project."""

    def __init__(self, db: Database, project_id: str):
        self.db = db
        self.project_id = project_id

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = TaskPriority.MEDIUM.value,
        assigned_role: Optional[str] = None,
        parent_task_id: Optional[int] = None,
        depends_on: Optional[list[int]] = None,
        tags: Optional[list[str]] = None,
    ) -> Task:
        """Create a new task card on the Kanban board."""
        # Validate role if provided
        if assigned_role:
            try:
                AgentRole(assigned_role)
            except ValueError:
                valid = [r.value for r in AgentRole]
                raise ValueError(
                    f"Invalid role '{assigned_role}'. Valid roles: {valid}"
                )

        # Validate priority
        try:
            TaskPriority(priority)
        except ValueError:
            valid = [p.value for p in TaskPriority]
            raise ValueError(
                f"Invalid priority '{priority}'. Valid priorities: {valid}"
            )

        # Check parent task exists
        if parent_task_id:
            parent = self.db.get_task(parent_task_id)
            if not parent:
                raise ValueError(f"Parent task #{parent_task_id} not found")

        # Check dependencies exist
        if depends_on:
            for dep_id in depends_on:
                dep = self.db.get_task(dep_id)
                if not dep:
                    raise ValueError(f"Dependency task #{dep_id} not found")

        task = Task(
            project_id=self.project_id,
            title=title,
            description=description,
            priority=priority,
            assigned_role=assigned_role,
            parent_task_id=parent_task_id,
            depends_on=json.dumps(depends_on or []),
            tags=json.dumps(tags or []),
        )
        task = self.db.create_task(task)

        # Audit log
        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task.id,
            agent_role=assigned_role,
            action=AuditAction.TASK_CREATED.value,
            details=f"Created task: {title}",
            metadata_json=json.dumps({
                "priority": priority,
                "assigned_role": assigned_role,
            }),
        ))

        return task

    def move_task(self, task_id: int, new_status: str) -> Task:
        """Move a task to a new Kanban column."""
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task #{task_id} not found")

        # Validate status
        try:
            TaskStatus(new_status)
        except ValueError:
            valid = [s.value for s in TaskStatus]
            raise ValueError(
                f"Invalid status '{new_status}'. Valid statuses: {valid}"
            )

        # Check valid transition
        allowed = VALID_TRANSITIONS.get(task.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Cannot move from '{task.status}' to '{new_status}'. "
                f"Allowed: {allowed}"
            )

        # Check unresolved dependencies (can't move to in_progress if deps not done)
        if new_status == TaskStatus.IN_PROGRESS.value:
            deps = json.loads(task.depends_on)
            for dep_id in deps:
                dep = self.db.get_task(dep_id)
                if dep and dep.status != TaskStatus.DONE.value:
                    raise ValueError(
                        f"Cannot start: dependency #{dep_id} ('{dep.title}') "
                        f"is not done (status: {dep.status})"
                    )

        old_status = task.status
        updated = self.db.update_task(task_id, status=new_status)

        # Audit log
        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            action=AuditAction.TASK_MOVED.value,
            details=f"Moved from {old_status} to {new_status}",
            metadata_json=json.dumps({
                "from_status": old_status,
                "to_status": new_status,
            }),
        ))

        return updated

    def assign_task(self, task_id: int, role: str, session_id: Optional[str] = None) -> Task:
        """Assign a task to an agent role (and optionally a specific session)."""
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task #{task_id} not found")

        try:
            AgentRole(role)
        except ValueError:
            valid = [r.value for r in AgentRole]
            raise ValueError(f"Invalid role '{role}'. Valid roles: {valid}")

        updates = {"assigned_role": role}
        if session_id:
            session = self.db.get_session(session_id)
            if not session:
                raise ValueError(f"Session '{session_id}' not found")
            updates["assigned_session_id"] = session_id

        updated = self.db.update_task(task_id, **updates)

        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            agent_role=role,
            action=AuditAction.TASK_ASSIGNED.value,
            details=f"Assigned to {role}" + (f" (session: {session_id})" if session_id else ""),
            metadata_json=json.dumps(updates),
        ))

        return updated

    def add_comment(self, task_id: int, role: str, comment: str) -> None:
        """Add a comment to a task."""
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task #{task_id} not found")

        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            agent_role=role,
            action=AuditAction.TASK_COMMENTED.value,
            details=comment,
        ))

    def get_board_state(self) -> dict:
        """Get the full Kanban board state organized by columns."""
        columns = {}
        for status in TaskStatus:
            tasks = self.db.list_tasks(self.project_id, status=status.value)
            columns[status.value] = {
                "emoji": COLUMN_EMOJI[status.value],
                "label": status.value.replace("_", " ").title(),
                "count": len(tasks),
                "tasks": [t.to_dict() for t in tasks],
            }

        summary = self.db.get_board_summary(self.project_id)
        return {
            "project_id": self.project_id,
            "columns": columns,
            "summary": summary,
        }

    def get_task_details(self, task_id: int) -> dict:
        """Get full task details including audit trail and messages."""
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task #{task_id} not found")

        audit = self.db.list_audit_entries(self.project_id, task_id=task_id)
        messages = self.db.list_messages(self.project_id, task_id=task_id)
        artifacts = self.db.list_artifacts(self.project_id, task_id=task_id)

        return {
            "task": task.to_dict(),
            "audit_trail": [e.to_dict() for e in audit],
            "messages": [m.to_dict() for m in messages],
            "artifacts": [a.to_dict() for a in artifacts],
        }

    def format_board_text(self) -> str:
        """Format the board state as human-readable text."""
        state = self.get_board_state()
        project = self.db.get_project(self.project_id)
        lines = [f"## 🧠 Project: {project.name if project else self.project_id}\n"]
        lines.append("### 📊 Board Status\n")
        lines.append("| Column | Count | Tasks |")
        lines.append("|--------|-------|-------|")

        for status in TaskStatus:
            col = state["columns"][status.value]
            task_ids = ", ".join(
                f"#{t['id']} {t['title']}" for t in col["tasks"]
            )
            emoji = col["emoji"]
            label = col["label"]
            lines.append(f"| {emoji} {label} | {col['count']} | {task_ids or '—'} |")

        lines.append("")
        s = state["summary"]
        lines.append(f"**Active Agents:** {s['active_agents']} | "
                      f"**Messages:** {s['total_messages']}")

        return "\n".join(lines)
