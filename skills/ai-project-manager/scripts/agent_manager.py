#!/usr/bin/env python3
"""
agent_manager.py — Agent session manager for the AI Project Manager.

Manages the lifecycle of agent sessions: spawning, context loading,
prompt construction, termination, and session state persistence.
"""

from __future__ import annotations

import json
from typing import Optional

from models import (
    AgentSession, AgentRole, SessionStatus, AuditEntry, AuditAction,
    ROLE_EMOJI, ROLE_SYSTEM_PROMPTS, _utcnow, _new_id,
)
from database import Database


class AgentManager:
    """Manages agent sessions for a project."""

    def __init__(self, db: Database, project_id: str):
        self.db = db
        self.project_id = project_id

    def spawn_agent(
        self,
        role: str,
        task_id: Optional[int] = None,
        custom_prompt: Optional[str] = None,
    ) -> AgentSession:
        """Spawn a new agent session for a specific role."""
        # Validate role
        try:
            agent_role = AgentRole(role)
        except ValueError:
            valid = [r.value for r in AgentRole]
            raise ValueError(f"Invalid role '{role}'. Valid roles: {valid}")

        # Build system prompt with context
        system_prompt = self._build_system_prompt(agent_role, task_id, custom_prompt)

        # Build initial context history
        context_history = []
        if task_id:
            task = self.db.get_task(task_id)
            if not task:
                raise ValueError(f"Task #{task_id} not found")
            context_history.append({
                "role": "system",
                "content": f"You are assigned to task #{task_id}: {task.title}\n\n"
                           f"Description: {task.description}\n"
                           f"Priority: {task.priority}\n"
                           f"Status: {task.status}",
            })

            # Load related messages for context
            messages = self.db.list_messages(self.project_id, task_id=task_id, limit=20)
            for msg in reversed(messages):
                emoji = ROLE_EMOJI.get(AgentRole(msg.from_role), "🤖") if msg.from_role in [r.value for r in AgentRole] else "🤖"
                context_history.append({
                    "role": "assistant" if msg.from_role == role else "user",
                    "content": f"[{emoji} {msg.from_role} → {msg.to_role}]: {msg.content}",
                })

            # Load related audit entries
            audits = self.db.list_audit_entries(self.project_id, task_id=task_id, limit=10)
            if audits:
                audit_summary = "\n".join(
                    f"- [{a.created_at}] {a.agent_role or 'system'}: {a.action} — {a.details}"
                    for a in audits
                )
                context_history.append({
                    "role": "system",
                    "content": f"Task history:\n{audit_summary}",
                })

        # Generate session ID
        role_short = role[:4]
        session_id = f"agent-{role_short}-{_new_id()[:6]}"

        session = AgentSession(
            id=session_id,
            project_id=self.project_id,
            role=role,
            current_task_id=task_id,
            system_prompt=system_prompt,
            context_history=json.dumps(context_history),
        )

        session = self.db.create_session(session)

        # Assign session to task if provided
        if task_id:
            self.db.update_task(task_id, assigned_session_id=session_id)

        # Audit
        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            session_id=session_id,
            agent_role=role,
            action=AuditAction.AGENT_SPAWNED.value,
            details=f"Spawned {role} agent session",
            metadata_json=json.dumps({
                "session_id": session_id,
                "task_id": task_id,
            }),
        ))

        return session

    def terminate_agent(self, session_id: str, reason: str = "") -> AgentSession:
        """Terminate an agent session."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found")

        if session.status == SessionStatus.TERMINATED.value:
            raise ValueError(f"Session '{session_id}' is already terminated")

        updated = self.db.update_session(
            session_id,
            status=SessionStatus.TERMINATED.value,
            terminated_at=_utcnow(),
        )

        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=session.current_task_id,
            session_id=session_id,
            agent_role=session.role,
            action=AuditAction.AGENT_TERMINATED.value,
            details=f"Terminated: {reason}" if reason else "Agent session terminated",
        ))

        return updated

    def get_session_context(self, session_id: str) -> dict:
        """Get the full context for an agent session (for prompt construction)."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found")

        context = {
            "session_id": session.id,
            "role": session.role,
            "role_emoji": ROLE_EMOJI.get(AgentRole(session.role), "🤖"),
            "status": session.status,
            "system_prompt": session.system_prompt,
            "context_history": json.loads(session.context_history),
            "created_at": session.created_at,
        }

        if session.current_task_id:
            task = self.db.get_task(session.current_task_id)
            if task:
                context["current_task"] = task.to_dict()

        # Get pending messages for this agent
        pending_messages = self.db.list_messages(
            self.project_id, role=session.role, limit=10
        )
        context["pending_messages"] = [m.to_dict() for m in pending_messages]

        return context

    def append_to_context(
        self, session_id: str, role: str, content: str
    ) -> None:
        """Append a message to the session's context history."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found")

        history = json.loads(session.context_history)
        history.append({"role": role, "content": content})

        # Trim history if too long (keep system + last 50 messages)
        if len(history) > 60:
            system_msgs = [m for m in history if m["role"] == "system"]
            other_msgs = [m for m in history if m["role"] != "system"]
            history = system_msgs + other_msgs[-50:]

        self.db.update_session(
            session_id, context_history=json.dumps(history)
        )

    def list_active_agents(self) -> list[dict]:
        """List all active agent sessions with summary info."""
        sessions = self.db.list_sessions(
            self.project_id, status=SessionStatus.ACTIVE.value
        )
        result = []
        for s in sessions:
            info = {
                "session_id": s.id,
                "role": s.role,
                "role_emoji": ROLE_EMOJI.get(AgentRole(s.role), "🤖"),
                "status": s.status,
                "current_task_id": s.current_task_id,
                "created_at": s.created_at,
            }
            if s.current_task_id:
                task = self.db.get_task(s.current_task_id)
                if task:
                    info["current_task_title"] = task.title
            result.append(info)
        return result

    def reassign_agent(self, session_id: str, new_task_id: int) -> AgentSession:
        """Reassign an active agent to a different task."""
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' not found")
        if session.status != SessionStatus.ACTIVE.value:
            raise ValueError(f"Session '{session_id}' is not active")

        task = self.db.get_task(new_task_id)
        if not task:
            raise ValueError(f"Task #{new_task_id} not found")

        # Add transition context
        self.append_to_context(
            session_id, "system",
            f"You have been reassigned to task #{new_task_id}: {task.title}\n"
            f"Description: {task.description}\n"
            f"Priority: {task.priority}"
        )

        updated = self.db.update_session(session_id, current_task_id=new_task_id)
        self.db.update_task(new_task_id, assigned_session_id=session_id)

        return updated

    def _build_system_prompt(
        self,
        role: AgentRole,
        task_id: Optional[int],
        custom_prompt: Optional[str],
    ) -> str:
        """Build the system prompt for an agent session."""
        parts = [ROLE_SYSTEM_PROMPTS[role]]

        # Add project context
        project = self.db.get_project(self.project_id)
        if project:
            parts.append(
                f"\n--- Project Context ---\n"
                f"Project: {project.name}\n"
                f"Description: {project.description}\n"
            )

        # Add task context
        if task_id:
            task = self.db.get_task(task_id)
            if task:
                parts.append(
                    f"\n--- Current Task ---\n"
                    f"Task #{task.id}: {task.title}\n"
                    f"Description: {task.description}\n"
                    f"Priority: {task.priority}\n"
                    f"Status: {task.status}\n"
                )

        # Add team awareness
        active_sessions = self.db.list_sessions(
            self.project_id, status=SessionStatus.ACTIVE.value
        )
        if active_sessions:
            team_info = "\n--- Active Team ---\n"
            for s in active_sessions:
                emoji = ROLE_EMOJI.get(AgentRole(s.role), "🤖")
                task_info = ""
                if s.current_task_id:
                    t = self.db.get_task(s.current_task_id)
                    task_info = f" (working on: #{s.current_task_id} {t.title})" if t else ""
                team_info += f"- {emoji} {s.role} [{s.id}]{task_info}\n"
            parts.append(team_info)

        # Add inter-agent communication instructions
        parts.append(
            "\n--- Communication ---\n"
            "You can communicate with other agents by mentioning their role.\n"
            "Use @mention to summon another agent when you need collaboration.\n"
            "Example: '@reviewer Please review the code I produced for task #3'\n"
            "Example: '@tester Please write tests for this implementation'\n"
        )

        if custom_prompt:
            parts.append(f"\n--- Additional Instructions ---\n{custom_prompt}")

        return "\n".join(parts)

    def format_agents_text(self) -> str:
        """Format active agents as human-readable text."""
        agents = self.list_active_agents()
        if not agents:
            return "No active agents."

        lines = ["### 🤖 Active Agents\n"]
        lines.append("| Agent | Role | Current Task | Session Age |")
        lines.append("|-------|------|-------------|-------------|")

        for a in agents:
            task_info = f"#{a['current_task_id']}" if a.get("current_task_id") else "—"
            if a.get("current_task_title"):
                task_info += f" ({a['current_task_title'][:30]})"
            lines.append(
                f"| {a['session_id']} | {a['role_emoji']} {a['role']} | "
                f"{task_info} | {a['created_at'][:16]} |"
            )

        return "\n".join(lines)
