#!/usr/bin/env python3
"""
models.py — Data models for the AI Project Manager.

Defines all domain objects: Projects, Tasks, AgentSessions, Messages, AuditEntries,
PipelineRuns, and Artifacts. Uses dataclasses with SQLite persistence.
"""

from __future__ import annotations

import enum
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# ── Enums ────────────────────────────────────────────────────────────────────


class TaskStatus(str, enum.Enum):
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"


class TaskPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AgentRole(str, enum.Enum):
    ARCHITECT = "architect"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    SECURITY = "security"
    UX_DESIGNER = "ux_designer"
    DEVOPS = "devops"
    PLANNER = "planner"


ROLE_EMOJI = {
    AgentRole.ARCHITECT: "🏗️",
    AgentRole.CODER: "💻",
    AgentRole.TESTER: "🧪",
    AgentRole.REVIEWER: "👀",
    AgentRole.SECURITY: "🔒",
    AgentRole.UX_DESIGNER: "🎨",
    AgentRole.DEVOPS: "🚀",
    AgentRole.PLANNER: "📋",
}

ROLE_SYSTEM_PROMPTS = {
    AgentRole.ARCHITECT: (
        "You are a Software Architect agent. Your responsibilities include:\n"
        "- Analyzing requirements and decomposing them into actionable tasks\n"
        "- Designing system architecture, data models, and API contracts\n"
        "- Making technology stack decisions\n"
        "- Creating architecture diagrams and documentation\n"
        "- Reviewing designs for scalability, maintainability, and correctness\n"
        "Always think in terms of components, interfaces, and data flows."
    ),
    AgentRole.CODER: (
        "You are a Software Developer agent. Your responsibilities include:\n"
        "- Writing clean, well-tested, production-quality code\n"
        "- Implementing features based on task specifications\n"
        "- Refactoring existing code for clarity and performance\n"
        "- Following coding standards and best practices\n"
        "- Producing code artifacts with clear documentation\n"
        "Always write idiomatic code with proper error handling."
    ),
    AgentRole.TESTER: (
        "You are a QA/Testing agent. Your responsibilities include:\n"
        "- Writing comprehensive unit, integration, and e2e tests\n"
        "- Identifying edge cases and failure modes\n"
        "- Running test suites and reporting results\n"
        "- Suggesting refactors to improve testability\n"
        "- Verifying bug fixes and regression testing\n"
        "Always aim for high coverage and meaningful assertions."
    ),
    AgentRole.REVIEWER: (
        "You are a Code Review agent. Your responsibilities include:\n"
        "- Reviewing code for correctness, readability, and best practices\n"
        "- Identifying potential bugs, code smells, and anti-patterns\n"
        "- Suggesting improvements and alternatives\n"
        "- Ensuring consistency with project coding standards\n"
        "- Approving or requesting changes with clear feedback\n"
        "Be constructive, specific, and actionable in your feedback."
    ),
    AgentRole.SECURITY: (
        "You are a Security Auditor agent. Your responsibilities include:\n"
        "- Performing security reviews of code and architecture\n"
        "- Identifying vulnerabilities (OWASP Top 10, CWE)\n"
        "- Checking for injection, auth, crypto, and config issues\n"
        "- Recommending security fixes with severity ratings\n"
        "- Reviewing dependency security (CVEs, outdated packages)\n"
        "Always classify findings by severity: Critical, High, Medium, Low."
    ),
    AgentRole.UX_DESIGNER: (
        "You are a UX Designer agent. Your responsibilities include:\n"
        "- Designing user interfaces and user experience flows\n"
        "- Creating wireframes and design specifications\n"
        "- Reviewing accessibility (WCAG compliance)\n"
        "- Suggesting usability improvements\n"
        "- Ensuring responsive and inclusive design\n"
        "Always consider user needs, accessibility, and consistency."
    ),
    AgentRole.DEVOPS: (
        "You are a DevOps/Infrastructure agent. Your responsibilities include:\n"
        "- Setting up CI/CD pipelines and deployment automation\n"
        "- Writing Dockerfiles, compose files, and IaC configs\n"
        "- Managing build, test, and deploy stages\n"
        "- Monitoring and logging infrastructure\n"
        "- Ensuring security and performance of deployments\n"
        "Always follow infrastructure-as-code and automation best practices."
    ),
    AgentRole.PLANNER: (
        "You are a Project Planner agent. Your responsibilities include:\n"
        "- Breaking down projects into epics, stories, and tasks\n"
        "- Prioritizing and scheduling work items\n"
        "- Tracking dependencies between tasks\n"
        "- Managing sprint goals and timelines\n"
        "- Coordinating between agents and resolving blockers\n"
        "Always think in terms of deliverables, milestones, and dependencies."
    ),
}


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    IDLE = "idle"
    TERMINATED = "terminated"


class PipelineStage(str, enum.Enum):
    BUILD = "build"
    TEST = "test"
    SECURITY_SCAN = "security_scan"
    STAGING = "staging"
    PRODUCTION = "production"


class PipelineStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AuditAction(str, enum.Enum):
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_MOVED = "task_moved"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMMENTED = "task_commented"
    AGENT_SPAWNED = "agent_spawned"
    AGENT_TERMINATED = "agent_terminated"
    MESSAGE_SENT = "message_sent"
    ARTIFACT_PRODUCED = "artifact_produced"
    PIPELINE_TRIGGERED = "pipeline_triggered"
    PIPELINE_COMPLETED = "pipeline_completed"
    PROJECT_CREATED = "project_created"


# ── Data classes ─────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Project:
    id: str = field(default_factory=_new_id)
    name: str = ""
    description: str = ""
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Task:
    id: int = 0
    project_id: str = ""
    title: str = ""
    description: str = ""
    status: str = TaskStatus.BACKLOG.value
    priority: str = TaskPriority.MEDIUM.value
    assigned_role: Optional[str] = None
    assigned_session_id: Optional[str] = None
    parent_task_id: Optional[int] = None
    depends_on: str = "[]"  # JSON array of task IDs
    tags: str = "[]"  # JSON array of strings
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["depends_on"] = json.loads(self.depends_on)
        d["tags"] = json.loads(self.tags)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        d = dict(d)
        if isinstance(d.get("depends_on"), list):
            d["depends_on"] = json.dumps(d["depends_on"])
        if isinstance(d.get("tags"), list):
            d["tags"] = json.dumps(d["tags"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AgentSession:
    id: str = field(default_factory=lambda: f"agent-{_new_id()}")
    project_id: str = ""
    role: str = AgentRole.CODER.value
    status: str = SessionStatus.ACTIVE.value
    current_task_id: Optional[int] = None
    system_prompt: str = ""
    context_history: str = "[]"  # JSON array of messages
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    terminated_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["context_history"] = json.loads(self.context_history)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AgentSession:
        d = dict(d)
        if isinstance(d.get("context_history"), list):
            d["context_history"] = json.dumps(d["context_history"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Message:
    id: str = field(default_factory=_new_id)
    project_id: str = ""
    from_role: str = ""
    to_role: str = ""
    from_session_id: Optional[str] = None
    to_session_id: Optional[str] = None
    task_id: Optional[int] = None
    content: str = ""
    message_type: str = "text"  # text, mention, summon, artifact
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AuditEntry:
    id: str = field(default_factory=_new_id)
    project_id: str = ""
    task_id: Optional[int] = None
    session_id: Optional[str] = None
    agent_role: Optional[str] = None
    action: str = ""
    details: str = ""
    metadata_json: str = "{}"
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metadata"] = json.loads(self.metadata_json)
        del d["metadata_json"]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AuditEntry:
        d = dict(d)
        if "metadata" in d and "metadata_json" not in d:
            d["metadata_json"] = json.dumps(d["metadata"])
            del d["metadata"]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PipelineRun:
    id: str = field(default_factory=_new_id)
    project_id: str = ""
    task_id: Optional[int] = None
    stage: str = PipelineStage.BUILD.value
    status: str = PipelineStatus.PENDING.value
    triggered_by: Optional[str] = None  # session_id or role
    logs: str = ""
    artifact_path: Optional[str] = None
    started_at: str = field(default_factory=_utcnow)
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PipelineRun:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Artifact:
    id: str = field(default_factory=_new_id)
    project_id: str = ""
    task_id: Optional[int] = None
    session_id: Optional[str] = None
    name: str = ""
    artifact_type: str = "code"  # code, test, config, doc, binary
    content: str = ""
    file_path: Optional[str] = None
    size_bytes: int = 0
    checksum: Optional[str] = None
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Artifact:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
