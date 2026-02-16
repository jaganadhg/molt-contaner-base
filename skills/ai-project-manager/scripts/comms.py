#!/usr/bin/env python3
"""
comms.py — Inter-agent communication bus for the AI Project Manager.

Handles messaging between agents, @mentions, agent summoning,
dependency signaling, and message routing.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from models import (
    Message, AgentRole, AuditEntry, AuditAction,
    ROLE_EMOJI, _utcnow,
)
from database import Database


# Pattern to detect @mentions in message content
MENTION_PATTERN = re.compile(r"@(\w+)", re.IGNORECASE)

# Map common aliases to agent roles
ROLE_ALIASES = {
    "arch": "architect",
    "architect": "architect",
    "code": "coder",
    "coder": "coder",
    "dev": "coder",
    "developer": "coder",
    "test": "tester",
    "tester": "tester",
    "qa": "tester",
    "review": "reviewer",
    "reviewer": "reviewer",
    "sec": "security",
    "security": "security",
    "audit": "security",
    "auditor": "security",
    "ux": "ux_designer",
    "ui": "ux_designer",
    "design": "ux_designer",
    "designer": "ux_designer",
    "ux_designer": "ux_designer",
    "ops": "devops",
    "devops": "devops",
    "deploy": "devops",
    "plan": "planner",
    "planner": "planner",
    "pm": "planner",
}


class CommunicationBus:
    """Inter-agent communication bus for the project."""

    def __init__(self, db: Database, project_id: str):
        self.db = db
        self.project_id = project_id
        self._event_listeners: list = []

    def send_message(
        self,
        from_role: str,
        to_role: str,
        content: str,
        task_id: Optional[int] = None,
        message_type: str = "text",
        from_session_id: Optional[str] = None,
        to_session_id: Optional[str] = None,
    ) -> Message:
        """Send a message from one agent to another."""
        # Validate roles
        from_role = self._resolve_role(from_role)
        to_role = self._resolve_role(to_role)

        # Auto-detect mentions in content
        mentions = self._extract_mentions(content)
        if mentions and message_type == "text":
            message_type = "mention"

        # Resolve session IDs if not provided
        if not from_session_id:
            session = self.db.find_active_session_for_role(self.project_id, from_role)
            if session:
                from_session_id = session.id

        if not to_session_id:
            session = self.db.find_active_session_for_role(self.project_id, to_role)
            if session:
                to_session_id = session.id

        msg = Message(
            project_id=self.project_id,
            from_role=from_role,
            to_role=to_role,
            from_session_id=from_session_id,
            to_session_id=to_session_id,
            task_id=task_id,
            content=content,
            message_type=message_type,
        )
        msg = self.db.create_message(msg)

        # Audit
        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            session_id=from_session_id,
            agent_role=from_role,
            action=AuditAction.MESSAGE_SENT.value,
            details=f"{from_role} → {to_role}: {content[:100]}",
            metadata_json=json.dumps({
                "message_id": msg.id,
                "message_type": message_type,
                "mentions": mentions,
            }),
        ))

        # Notify listeners (for real-time updates)
        self._notify_listeners("message", msg.to_dict())

        # If it's a summon, inject context into target session
        if message_type == "summon" and to_session_id:
            from agent_manager import AgentManager
            am = AgentManager(self.db, self.project_id)
            emoji = ROLE_EMOJI.get(AgentRole(from_role), "🤖")
            am.append_to_context(
                to_session_id, "user",
                f"[{emoji} {from_role} summoned you]: {content}"
            )

        return msg

    def broadcast(
        self,
        from_role: str,
        content: str,
        task_id: Optional[int] = None,
        exclude_roles: Optional[list[str]] = None,
    ) -> list[Message]:
        """Broadcast a message to all active agents."""
        exclude = set(exclude_roles or [])
        exclude.add(from_role)

        active_sessions = self.db.list_sessions(
            self.project_id, status="active"
        )
        messages = []
        for session in active_sessions:
            if session.role not in exclude:
                msg = self.send_message(
                    from_role=from_role,
                    to_role=session.role,
                    content=content,
                    task_id=task_id,
                    message_type="broadcast",
                    to_session_id=session.id,
                )
                messages.append(msg)

        return messages

    def summon_agent(
        self,
        from_role: str,
        target_role: str,
        reason: str,
        task_id: Optional[int] = None,
    ) -> Message:
        """Summon another agent for collaboration."""
        target_role = self._resolve_role(target_role)
        return self.send_message(
            from_role=from_role,
            to_role=target_role,
            content=f"[SUMMON] {reason}",
            task_id=task_id,
            message_type="summon",
        )

    def signal_dependency(
        self,
        from_role: str,
        to_role: str,
        task_id: int,
        dependency_task_id: int,
        status: str = "completed",
    ) -> Message:
        """Signal a dependency status change to another agent."""
        content = (
            f"[DEPENDENCY] Task #{dependency_task_id} is now {status}. "
            f"Task #{task_id} may now proceed."
        )
        return self.send_message(
            from_role=from_role,
            to_role=to_role,
            content=content,
            task_id=task_id,
            message_type="dependency",
        )

    def get_inbox(
        self,
        role: str,
        task_id: Optional[int] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get unread messages for an agent role."""
        messages = self.db.list_messages(
            self.project_id, task_id=task_id, role=role, limit=limit
        )
        return [m.to_dict() for m in messages if m.to_role == role]

    def get_conversation(
        self,
        role1: str,
        role2: str,
        task_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get the conversation between two agents."""
        all_msgs = self.db.list_messages(
            self.project_id, task_id=task_id, limit=limit * 2
        )
        filtered = [
            m.to_dict() for m in all_msgs
            if (m.from_role == role1 and m.to_role == role2)
            or (m.from_role == role2 and m.to_role == role1)
        ]
        return filtered[:limit]

    def register_listener(self, callback) -> None:
        """Register an event listener for real-time updates."""
        self._event_listeners.append(callback)

    def _notify_listeners(self, event_type: str, data: dict) -> None:
        """Notify all registered listeners."""
        for listener in self._event_listeners:
            try:
                listener(event_type, data)
            except Exception:
                pass  # Don't let listener errors break messaging

    def _resolve_role(self, role_or_alias: str) -> str:
        """Resolve a role name or alias to a canonical role."""
        role = ROLE_ALIASES.get(role_or_alias.lower(), role_or_alias.lower())
        try:
            AgentRole(role)
        except ValueError:
            valid = list(ROLE_ALIASES.keys())
            raise ValueError(
                f"Unknown role '{role_or_alias}'. Valid roles/aliases: {valid}"
            )
        return role

    def _extract_mentions(self, content: str) -> list[str]:
        """Extract @mentions from message content."""
        mentions = []
        for match in MENTION_PATTERN.finditer(content):
            alias = match.group(1).lower()
            if alias in ROLE_ALIASES:
                mentions.append(ROLE_ALIASES[alias])
        return list(set(mentions))

    def format_messages_text(
        self, task_id: Optional[int] = None, limit: int = 10
    ) -> str:
        """Format recent messages as human-readable text."""
        messages = self.db.list_messages(
            self.project_id, task_id=task_id, limit=limit
        )
        if not messages:
            return "No messages yet."

        lines = ["### 📬 Recent Messages\n"]
        for m in messages:
            from_emoji = ROLE_EMOJI.get(AgentRole(m.from_role), "🤖") if m.from_role in [r.value for r in AgentRole] else "🤖"
            to_emoji = ROLE_EMOJI.get(AgentRole(m.to_role), "🤖") if m.to_role in [r.value for r in AgentRole] else "🤖"
            task_ref = f" (task #{m.task_id})" if m.task_id else ""
            lines.append(
                f"- {from_emoji} **{m.from_role}** → {to_emoji} **{m.to_role}**{task_ref}: "
                f"\"{m.content[:100]}\""
            )

        return "\n".join(lines)
