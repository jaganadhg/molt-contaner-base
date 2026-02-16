#!/usr/bin/env python3
"""
orchestrator.py — Main CLI orchestrator for the AI Project Manager.

Entry point for all project management commands: init, task, agent,
message, status, audit, pipeline, and board operations.

Usage:
    python3 orchestrator.py init --name "My Project" --description "..."
    python3 orchestrator.py task create --title "..." --priority high
    python3 orchestrator.py task move --id 1 --status in_progress
    python3 orchestrator.py task list [--status backlog] [--role coder]
    python3 orchestrator.py agent spawn --role coder [--task-id 1]
    python3 orchestrator.py agent list
    python3 orchestrator.py agent terminate --session-id agent-code-abc123
    python3 orchestrator.py message --from coder --to reviewer --content "..."
    python3 orchestrator.py status
    python3 orchestrator.py audit [--task-id 1]
    python3 orchestrator.py pipeline run --stage test [--task-id 1]
    python3 orchestrator.py pipeline status
    python3 orchestrator.py board export [--format json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure scripts directory is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import (
    Project, Task, TaskStatus, TaskPriority, AgentRole, PipelineStage,
    AuditAction, ROLE_EMOJI, _utcnow,
)
from database import Database
from kanban import KanbanBoard
from agent_manager import AgentManager
from comms import CommunicationBus
from audit import AuditTrail
from cicd import PipelineManager


def get_db() -> Database:
    db = Database()
    db.init_schema()
    return db


def get_active_project(db: Database) -> Project:
    project = db.get_active_project()
    if not project:
        print(json.dumps({"error": "No project found. Run 'init' first."}))
        sys.exit(1)
    return project


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_init(args):
    """Initialize a new project."""
    db = get_db()
    project = Project(name=args.name, description=args.description or "")
    project = db.create_project(project)

    # Log project creation
    db.create_audit_entry(
        __import__("models").AuditEntry(
            project_id=project.id,
            action=AuditAction.PROJECT_CREATED.value,
            details=f"Project '{args.name}' initialized",
        )
    )

    result = {
        "status": "success",
        "message": f"Project '{args.name}' initialized",
        "project": project.to_dict(),
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"✅ Project '{args.name}' initialized successfully!")
        print(f"   ID: {project.id}")
        print(f"   Created: {project.created_at}")
        print(f"\nNext steps:")
        print(f"  1. Create tasks:  python3 orchestrator.py task create --title '...'")
        print(f"  2. Spawn agents:  python3 orchestrator.py agent spawn --role coder")
        print(f"  3. View board:    python3 orchestrator.py status")


def cmd_task_create(args):
    """Create a new task."""
    db = get_db()
    project = get_active_project(db)
    board = KanbanBoard(db, project.id)

    depends_on = None
    if args.depends_on:
        depends_on = [int(x.strip()) for x in args.depends_on.split(",")]

    tags = None
    if args.tags:
        tags = [t.strip() for t in args.tags.split(",")]

    try:
        task = board.create_task(
            title=args.title,
            description=args.description or "",
            priority=args.priority,
            assigned_role=args.assign,
            parent_task_id=args.parent,
            depends_on=depends_on,
            tags=tags,
        )
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    result = {
        "status": "success",
        "message": f"Task #{task.id} created",
        "task": task.to_dict(),
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        role_info = f" → {ROLE_EMOJI.get(AgentRole(args.assign), '🤖')} {args.assign}" if args.assign else ""
        print(f"✅ Task #{task.id}: {args.title}{role_info}")
        print(f"   Priority: {args.priority} | Status: backlog")


def cmd_task_move(args):
    """Move a task between Kanban columns."""
    db = get_db()
    project = get_active_project(db)
    board = KanbanBoard(db, project.id)

    try:
        task = board.move_task(args.id, args.status)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    result = {
        "status": "success",
        "message": f"Task #{args.id} moved to {args.status}",
        "task": task.to_dict(),
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        from kanban import COLUMN_EMOJI
        emoji = COLUMN_EMOJI.get(args.status, "📋")
        print(f"✅ Task #{args.id} moved to {emoji} {args.status}")


def cmd_task_list(args):
    """List tasks with optional filters."""
    db = get_db()
    project = get_active_project(db)

    tasks = db.list_tasks(
        project.id,
        status=args.status,
        assigned_role=args.role,
    )

    if args.format == "json":
        print(json.dumps({
            "project_id": project.id,
            "count": len(tasks),
            "tasks": [t.to_dict() for t in tasks],
        }, indent=2))
    else:
        board = KanbanBoard(db, project.id)
        print(board.format_board_text())


def cmd_task_details(args):
    """Get detailed info about a specific task."""
    db = get_db()
    project = get_active_project(db)
    board = KanbanBoard(db, project.id)

    try:
        details = board.get_task_details(args.id)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    if args.format == "json":
        print(json.dumps(details, indent=2))
    else:
        t = details["task"]
        role_emoji = ROLE_EMOJI.get(AgentRole(t["assigned_role"]), "🤖") if t.get("assigned_role") else "—"
        print(f"## Task #{t['id']}: {t['title']}")
        print(f"Status: {t['status']} | Priority: {t['priority']}")
        print(f"Assigned: {role_emoji} {t.get('assigned_role', 'unassigned')}")
        print(f"Description: {t.get('description', '—')}")
        print(f"\nAudit entries: {len(details['audit_trail'])}")
        print(f"Messages: {len(details['messages'])}")
        print(f"Artifacts: {len(details['artifacts'])}")


def cmd_agent_spawn(args):
    """Spawn a new agent session."""
    db = get_db()
    project = get_active_project(db)
    am = AgentManager(db, project.id)

    try:
        session = am.spawn_agent(
            role=args.role,
            task_id=args.task_id,
            custom_prompt=args.prompt,
        )
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    result = {
        "status": "success",
        "message": f"Agent session '{session.id}' spawned",
        "session": session.to_dict(),
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        emoji = ROLE_EMOJI.get(AgentRole(args.role), "🤖")
        print(f"✅ Spawned {emoji} {args.role} agent: {session.id}")
        if args.task_id:
            print(f"   Assigned to task #{args.task_id}")
        print(f"   System prompt: {len(session.system_prompt)} chars")
        print(f"   Context entries: {len(json.loads(session.context_history))}")


def cmd_agent_list(args):
    """List active agent sessions."""
    db = get_db()
    project = get_active_project(db)
    am = AgentManager(db, project.id)

    if args.format == "json":
        agents = am.list_active_agents()
        print(json.dumps({
            "project_id": project.id,
            "count": len(agents),
            "agents": agents,
        }, indent=2))
    else:
        print(am.format_agents_text())


def cmd_agent_terminate(args):
    """Terminate an agent session."""
    db = get_db()
    project = get_active_project(db)
    am = AgentManager(db, project.id)

    try:
        session = am.terminate_agent(args.session_id, reason=args.reason or "")
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    result = {
        "status": "success",
        "message": f"Agent session '{args.session_id}' terminated",
        "session": session.to_dict(),
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"✅ Agent session '{args.session_id}' terminated")


def cmd_agent_context(args):
    """Get the full context for an agent session."""
    db = get_db()
    project = get_active_project(db)
    am = AgentManager(db, project.id)

    try:
        context = am.get_session_context(args.session_id)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(context, indent=2))


def cmd_message(args):
    """Send an inter-agent message."""
    db = get_db()
    project = get_active_project(db)
    bus = CommunicationBus(db, project.id)

    try:
        msg = bus.send_message(
            from_role=args.sender,
            to_role=args.to,
            content=args.content,
            task_id=args.task_id,
            message_type=args.type or "text",
        )
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    result = {
        "status": "success",
        "message": msg.to_dict(),
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        from_emoji = ROLE_EMOJI.get(AgentRole(msg.from_role), "🤖")
        to_emoji = ROLE_EMOJI.get(AgentRole(msg.to_role), "🤖")
        print(f"📬 {from_emoji} {msg.from_role} → {to_emoji} {msg.to_role}: {msg.content}")


def cmd_status(args):
    """Full project status overview."""
    db = get_db()
    project = get_active_project(db)

    board = KanbanBoard(db, project.id)
    am = AgentManager(db, project.id)
    bus = CommunicationBus(db, project.id)
    pm = PipelineManager(db, project.id)

    if args.format == "json":
        result = {
            "project": project.to_dict(),
            "board": board.get_board_state(),
            "agents": am.list_active_agents(),
            "pipeline": pm.get_pipeline_status(),
        }
        print(json.dumps(result, indent=2))
    else:
        print(board.format_board_text())
        print()
        print(am.format_agents_text())
        print()
        print(bus.format_messages_text(limit=5))
        print()
        print(pm.format_pipeline_text())


def cmd_audit(args):
    """View audit trail."""
    db = get_db()
    project = get_active_project(db)
    trail = AuditTrail(db, project.id)

    if args.task_id:
        if args.format == "json":
            entries = trail.get_task_trail(args.task_id)
            print(json.dumps(entries, indent=2))
        else:
            print(trail.format_task_trail_text(args.task_id))
    elif args.session_id:
        entries = trail.get_session_trail(args.session_id)
        print(json.dumps(entries, indent=2))
    elif args.export:
        print(trail.export_audit_log(format=args.export))
    elif args.report:
        print(trail.format_project_report())
    else:
        if args.format == "json":
            entries = trail.get_project_timeline(limit=args.limit or 50)
            print(json.dumps(entries, indent=2))
        else:
            print(trail.format_project_report())


def cmd_pipeline_run(args):
    """Trigger a pipeline stage."""
    db = get_db()
    project = get_active_project(db)
    pm = PipelineManager(db, project.id)

    config = {}
    if args.command:
        config["command"] = args.command
    if args.webhook:
        config[f"{args.stage}_webhook"] = args.webhook

    if args.full:
        runs = pm.run_full_pipeline(
            task_id=args.task_id,
            triggered_by=args.triggered_by,
        )
        if args.format == "json":
            print(json.dumps([r.to_dict() for r in runs], indent=2))
        else:
            for r in runs:
                status_emoji = "✅" if r.status == "success" else "❌"
                print(f"{status_emoji} {r.stage}: {r.status}")
    else:
        try:
            run = pm.trigger_stage(
                stage=args.stage,
                task_id=args.task_id,
                triggered_by=args.triggered_by,
                config=config,
            )
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)

        if args.format == "json":
            print(json.dumps(run.to_dict(), indent=2))
        else:
            status_emoji = "✅" if run.status == "success" else "❌"
            print(f"{status_emoji} Pipeline stage '{args.stage}': {run.status}")
            if run.logs:
                print(f"\n{run.logs}")


def cmd_pipeline_status(args):
    """View pipeline status."""
    db = get_db()
    project = get_active_project(db)
    pm = PipelineManager(db, project.id)

    if args.format == "json":
        status = pm.get_pipeline_status(args.task_id)
        print(json.dumps(status, indent=2))
    else:
        print(pm.format_pipeline_text(args.task_id))


def cmd_board_export(args):
    """Export board state."""
    db = get_db()
    project = get_active_project(db)
    board = KanbanBoard(db, project.id)

    state = board.get_board_state()

    if args.format == "json" or not args.format:
        print(json.dumps(state, indent=2))
    else:
        print(board.format_board_text())


def cmd_artifact_store(args):
    """Store an artifact."""
    db = get_db()
    project = get_active_project(db)
    pm = PipelineManager(db, project.id)

    # Read content from file or stdin
    if args.file:
        content = Path(args.file).read_text()
    else:
        content = sys.stdin.read()

    artifact = pm.store_artifact(
        name=args.name,
        content=content,
        artifact_type=args.type or "code",
        task_id=args.task_id,
        session_id=args.session_id,
        file_path=args.path,
    )

    result = {
        "status": "success",
        "artifact": artifact.to_dict(),
    }

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"✅ Artifact '{args.name}' stored ({artifact.size_bytes} bytes)")


# ── CLI Parser ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI Project Manager — Multi-Session Agent Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--format", choices=["json", "text"], default="text",
        help="Output format (default: text)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── init ──
    p_init = subparsers.add_parser("init", help="Initialize a new project")
    p_init.add_argument("--name", required=True, help="Project name")
    p_init.add_argument("--description", help="Project description")
    p_init.set_defaults(func=cmd_init)

    # ── task ──
    p_task = subparsers.add_parser("task", help="Task management")
    task_sub = p_task.add_subparsers(dest="task_command")

    # task create
    p_tc = task_sub.add_parser("create", help="Create a new task")
    p_tc.add_argument("--title", required=True, help="Task title")
    p_tc.add_argument("--description", help="Task description")
    p_tc.add_argument(
        "--priority", default="medium",
        choices=["critical", "high", "medium", "low"],
    )
    p_tc.add_argument("--assign", help="Assign to agent role")
    p_tc.add_argument("--parent", type=int, help="Parent task ID")
    p_tc.add_argument("--depends-on", help="Comma-separated dependency task IDs")
    p_tc.add_argument("--tags", help="Comma-separated tags")
    p_tc.set_defaults(func=cmd_task_create)

    # task move
    p_tm = task_sub.add_parser("move", help="Move task between columns")
    p_tm.add_argument("--id", type=int, required=True, help="Task ID")
    p_tm.add_argument(
        "--status", required=True,
        choices=["backlog", "in_progress", "review", "done", "blocked"],
    )
    p_tm.set_defaults(func=cmd_task_move)

    # task list
    p_tl = task_sub.add_parser("list", help="List tasks")
    p_tl.add_argument("--status", help="Filter by status")
    p_tl.add_argument("--role", help="Filter by assigned role")
    p_tl.set_defaults(func=cmd_task_list)

    # task details
    p_td = task_sub.add_parser("details", help="Task details")
    p_td.add_argument("--id", type=int, required=True, help="Task ID")
    p_td.set_defaults(func=cmd_task_details)

    # ── agent ──
    p_agent = subparsers.add_parser("agent", help="Agent session management")
    agent_sub = p_agent.add_subparsers(dest="agent_command")

    # agent spawn
    p_as = agent_sub.add_parser("spawn", help="Spawn a new agent session")
    p_as.add_argument(
        "--role", required=True,
        choices=[r.value for r in AgentRole],
    )
    p_as.add_argument("--task-id", type=int, help="Assign to task")
    p_as.add_argument("--prompt", help="Custom additional prompt")
    p_as.set_defaults(func=cmd_agent_spawn)

    # agent list
    p_al = agent_sub.add_parser("list", help="List active agents")
    p_al.set_defaults(func=cmd_agent_list)

    # agent terminate
    p_at = agent_sub.add_parser("terminate", help="Terminate agent session")
    p_at.add_argument("--session-id", required=True, help="Session ID")
    p_at.add_argument("--reason", help="Termination reason")
    p_at.set_defaults(func=cmd_agent_terminate)

    # agent context
    p_ac = agent_sub.add_parser("context", help="Get agent session context")
    p_ac.add_argument("--session-id", required=True, help="Session ID")
    p_ac.set_defaults(func=cmd_agent_context)

    # ── message ──
    p_msg = subparsers.add_parser("message", help="Send inter-agent message")
    p_msg.add_argument("--from", dest="sender", required=True, help="Sender role")
    p_msg.add_argument("--to", required=True, help="Recipient role")
    p_msg.add_argument("--content", required=True, help="Message content")
    p_msg.add_argument("--task-id", type=int, help="Related task ID")
    p_msg.add_argument("--type", help="Message type (text, mention, summon)")
    p_msg.set_defaults(func=cmd_message)

    # ── status ──
    p_status = subparsers.add_parser("status", help="Full project status")
    p_status.set_defaults(func=cmd_status)

    # ── audit ──
    p_audit = subparsers.add_parser("audit", help="View audit trail")
    p_audit.add_argument("--task-id", type=int, help="Filter by task ID")
    p_audit.add_argument("--session-id", help="Filter by session ID")
    p_audit.add_argument("--export", choices=["json", "csv", "markdown"], help="Export format")
    p_audit.add_argument("--report", action="store_true", help="Generate report")
    p_audit.add_argument("--limit", type=int, help="Max entries")
    p_audit.set_defaults(func=cmd_audit)

    # ── pipeline ──
    p_pipe = subparsers.add_parser("pipeline", help="CI/CD pipeline")
    pipe_sub = p_pipe.add_subparsers(dest="pipeline_command")

    # pipeline run
    p_pr = pipe_sub.add_parser("run", help="Trigger pipeline stage")
    p_pr.add_argument(
        "--stage", default="build",
        choices=[s.value for s in PipelineStage],
    )
    p_pr.add_argument("--task-id", type=int, help="Related task ID")
    p_pr.add_argument("--triggered-by", help="Triggering agent role")
    p_pr.add_argument("--command", help="Custom command to run")
    p_pr.add_argument("--webhook", help="Webhook URL")
    p_pr.add_argument("--full", action="store_true", help="Run full pipeline")
    p_pr.set_defaults(func=cmd_pipeline_run)

    # pipeline status
    p_ps = pipe_sub.add_parser("status", help="View pipeline status")
    p_ps.add_argument("--task-id", type=int, help="Filter by task ID")
    p_ps.set_defaults(func=cmd_pipeline_status)

    # ── board ──
    p_board = subparsers.add_parser("board", help="Board operations")
    board_sub = p_board.add_subparsers(dest="board_command")

    # board export
    p_be = board_sub.add_parser("export", help="Export board state")
    p_be.set_defaults(func=cmd_board_export)

    # ── artifact ──
    p_art = subparsers.add_parser("artifact", help="Artifact management")
    art_sub = p_art.add_subparsers(dest="artifact_command")

    # artifact store
    p_ast = art_sub.add_parser("store", help="Store an artifact")
    p_ast.add_argument("--name", required=True, help="Artifact name")
    p_ast.add_argument("--type", default="code", help="Artifact type")
    p_ast.add_argument("--task-id", type=int, help="Related task ID")
    p_ast.add_argument("--session-id", help="Producing session ID")
    p_ast.add_argument("--file", help="Read content from file")
    p_ast.add_argument("--path", help="Store at workspace path")
    p_ast.set_defaults(func=cmd_artifact_store)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
