#!/usr/bin/env python3
"""
audit.py — Audit & traceability module for the AI Project Manager.

Provides detailed audit trail querying, reporting, and export capabilities
for all agent interactions, task changes, and pipeline events.
"""

from __future__ import annotations

import json
from typing import Optional

from models import (
    AuditEntry, AuditAction, AgentRole, ROLE_EMOJI, _utcnow,
)
from database import Database


class AuditTrail:
    """Manages audit trails and traceability for the project."""

    def __init__(self, db: Database, project_id: str):
        self.db = db
        self.project_id = project_id

    def log_event(
        self,
        action: str,
        details: str,
        task_id: Optional[int] = None,
        session_id: Optional[str] = None,
        agent_role: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> AuditEntry:
        """Log an audit event."""
        entry = AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            session_id=session_id,
            agent_role=agent_role,
            action=action,
            details=details,
            metadata_json=json.dumps(metadata or {}),
        )
        return self.db.create_audit_entry(entry)

    def get_task_trail(self, task_id: int, limit: int = 100) -> list[dict]:
        """Get the full audit trail for a specific task."""
        entries = self.db.list_audit_entries(
            self.project_id, task_id=task_id, limit=limit
        )
        return [e.to_dict() for e in entries]

    def get_session_trail(self, session_id: str, limit: int = 100) -> list[dict]:
        """Get the audit trail for a specific agent session."""
        entries = self.db.list_audit_entries(
            self.project_id, session_id=session_id, limit=limit
        )
        return [e.to_dict() for e in entries]

    def get_agent_trail(self, role: str, limit: int = 100) -> list[dict]:
        """Get the audit trail for all sessions of a specific role."""
        entries = self.db.list_audit_entries(self.project_id, limit=limit)
        return [e.to_dict() for e in entries if e.agent_role == role]

    def get_project_timeline(self, limit: int = 200) -> list[dict]:
        """Get the full project timeline."""
        entries = self.db.list_audit_entries(self.project_id, limit=limit)
        return [e.to_dict() for e in entries]

    def get_action_summary(self) -> dict:
        """Get a summary of actions by type."""
        entries = self.db.list_audit_entries(self.project_id, limit=10000)
        summary = {}
        for entry in entries:
            action = entry.action
            if action not in summary:
                summary[action] = {"count": 0, "last_at": None}
            summary[action]["count"] += 1
            summary[action]["last_at"] = entry.created_at
        return summary

    def get_agent_activity(self) -> dict:
        """Get activity breakdown by agent role."""
        entries = self.db.list_audit_entries(self.project_id, limit=10000)
        activity = {}
        for entry in entries:
            role = entry.agent_role or "system"
            if role not in activity:
                activity[role] = {
                    "total_actions": 0,
                    "actions": {},
                    "tasks_touched": set(),
                    "last_active": None,
                }
            activity[role]["total_actions"] += 1
            action = entry.action
            activity[role]["actions"][action] = activity[role]["actions"].get(action, 0) + 1
            if entry.task_id:
                activity[role]["tasks_touched"].add(entry.task_id)
            activity[role]["last_active"] = entry.created_at

        # Convert sets to lists for JSON serialization
        for role in activity:
            activity[role]["tasks_touched"] = sorted(activity[role]["tasks_touched"])

        return activity

    def export_audit_log(self, format: str = "json") -> str:
        """Export the full audit log in the specified format."""
        entries = self.db.list_audit_entries(self.project_id, limit=10000)
        data = [e.to_dict() for e in entries]

        if format == "json":
            return json.dumps(data, indent=2, ensure_ascii=False)
        elif format == "csv":
            if not data:
                return "timestamp,project_id,task_id,session_id,agent_role,action,details\n"
            lines = ["timestamp,project_id,task_id,session_id,agent_role,action,details"]
            for d in data:
                lines.append(
                    f"{d['created_at']},{d['project_id']},{d.get('task_id', '')},"
                    f"{d.get('session_id', '')},{d.get('agent_role', '')},"
                    f"{d['action']},\"{d['details']}\""
                )
            return "\n".join(lines)
        elif format == "markdown":
            return self._format_markdown(data)
        else:
            raise ValueError(f"Unknown format '{format}'. Use: json, csv, markdown")

    def format_task_trail_text(self, task_id: int) -> str:
        """Format a task's audit trail as human-readable Markdown."""
        trail = self.get_task_trail(task_id)
        if not trail:
            return f"No audit entries for task #{task_id}."

        task = self.db.get_task(task_id)
        title = task.title if task else f"Task #{task_id}"

        lines = [f"## 📜 Audit Trail — {title}\n"]
        lines.append("| Timestamp | Agent | Action | Details |")
        lines.append("|-----------|-------|--------|---------|")

        for entry in trail:
            role = entry.get("agent_role", "system")
            emoji = ""
            if role and role != "system":
                try:
                    emoji = ROLE_EMOJI.get(AgentRole(role), "🤖")
                except ValueError:
                    emoji = "🤖"
            else:
                emoji = "⚙️"

            lines.append(
                f"| {entry['created_at']} | {emoji} {role} | "
                f"{entry['action']} | {entry['details'][:60]} |"
            )

        return "\n".join(lines)

    def format_project_report(self) -> str:
        """Generate a comprehensive project report."""
        project = self.db.get_project(self.project_id)
        name = project.name if project else self.project_id

        activity = self.get_agent_activity()
        action_summary = self.get_action_summary()

        lines = [f"## 📊 Project Report: {name}\n"]

        # Agent activity
        lines.append("### 🤖 Agent Activity\n")
        lines.append("| Agent | Actions | Tasks | Last Active |")
        lines.append("|-------|---------|-------|-------------|")
        for role, data in sorted(activity.items()):
            emoji = ""
            try:
                emoji = ROLE_EMOJI.get(AgentRole(role), "🤖")
            except ValueError:
                emoji = "⚙️"
            lines.append(
                f"| {emoji} {role} | {data['total_actions']} | "
                f"{len(data['tasks_touched'])} | {data['last_active'] or '—'} |"
            )

        # Action breakdown
        lines.append("\n### 📋 Action Summary\n")
        lines.append("| Action | Count | Last Occurrence |")
        lines.append("|--------|-------|-----------------|")
        for action, data in sorted(action_summary.items()):
            lines.append(f"| {action} | {data['count']} | {data['last_at']} |")

        return "\n".join(lines)

    def _format_markdown(self, data: list[dict]) -> str:
        """Format audit data as Markdown table."""
        if not data:
            return "No audit entries found."

        lines = ["## 📜 Full Audit Log\n"]
        lines.append("| # | Timestamp | Agent | Action | Task | Details |")
        lines.append("|---|-----------|-------|--------|------|---------|")

        for i, entry in enumerate(data, 1):
            role = entry.get("agent_role", "system")
            emoji = ""
            try:
                emoji = ROLE_EMOJI.get(AgentRole(role), "⚙️") if role else "⚙️"
            except ValueError:
                emoji = "⚙️"
            task_ref = f"#{entry['task_id']}" if entry.get("task_id") else "—"
            lines.append(
                f"| {i} | {entry['created_at']} | {emoji} {role} | "
                f"{entry['action']} | {task_ref} | {entry['details'][:50]} |"
            )

        return "\n".join(lines)
