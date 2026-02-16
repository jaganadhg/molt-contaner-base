#!/usr/bin/env python3
"""
tests/test_project_manager.py — Tests for the AI Project Manager skill.

Tests cover: models, database, kanban, agent_manager, comms, audit, cicd.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from models import (
    Project, Task, AgentSession, Message, AuditEntry, PipelineRun, Artifact,
    TaskStatus, TaskPriority, AgentRole, SessionStatus, PipelineStage,
    PipelineStatus, AuditAction, ROLE_EMOJI, ROLE_SYSTEM_PROMPTS,
)
from database import Database
from kanban import KanbanBoard
from agent_manager import AgentManager
from comms import CommunicationBus
from audit import AuditTrail
from cicd import PipelineManager


class TestBase(unittest.TestCase):
    """Base test class that provides a fresh in-memory-like database."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.environ["AIPM_DB_PATH"] = self.tmp.name
        self.db = Database(db_path=Path(self.tmp.name))
        self.db.init_schema()

        # Create a test project
        self.project = self.db.create_project(
            Project(name="Test Project", description="A test project")
        )
        self.project_id = self.project.id

    def tearDown(self):
        os.unlink(self.tmp.name)
        if "AIPM_DB_PATH" in os.environ:
            del os.environ["AIPM_DB_PATH"]


class TestModels(TestBase):
    """Test data model serialization."""

    def test_project_to_dict(self):
        d = self.project.to_dict()
        self.assertEqual(d["name"], "Test Project")
        self.assertIn("id", d)
        self.assertIn("created_at", d)

    def test_task_to_dict_with_json_fields(self):
        task = Task(
            project_id=self.project_id,
            title="Test Task",
            depends_on="[1, 2]",
            tags='["api", "backend"]',
        )
        d = task.to_dict()
        self.assertEqual(d["depends_on"], [1, 2])
        self.assertEqual(d["tags"], ["api", "backend"])

    def test_task_from_dict_with_lists(self):
        task = Task.from_dict({
            "project_id": self.project_id,
            "title": "From Dict",
            "depends_on": [3, 4],
            "tags": ["frontend"],
        })
        self.assertEqual(json.loads(task.depends_on), [3, 4])

    def test_role_emoji_coverage(self):
        for role in AgentRole:
            self.assertIn(role, ROLE_EMOJI)

    def test_role_system_prompts_coverage(self):
        for role in AgentRole:
            self.assertIn(role, ROLE_SYSTEM_PROMPTS)
            self.assertTrue(len(ROLE_SYSTEM_PROMPTS[role]) > 50)


class TestDatabase(TestBase):
    """Test database CRUD operations."""

    def test_create_and_get_project(self):
        project = self.db.get_project(self.project_id)
        self.assertIsNotNone(project)
        self.assertEqual(project.name, "Test Project")

    def test_list_projects(self):
        projects = self.db.list_projects()
        self.assertEqual(len(projects), 1)

    def test_create_and_get_task(self):
        task = self.db.create_task(Task(
            project_id=self.project_id,
            title="Build API",
            priority=TaskPriority.HIGH.value,
        ))
        self.assertGreater(task.id, 0)

        fetched = self.db.get_task(task.id)
        self.assertEqual(fetched.title, "Build API")
        self.assertEqual(fetched.priority, "high")

    def test_list_tasks_with_filters(self):
        self.db.create_task(Task(
            project_id=self.project_id, title="Task A",
            status=TaskStatus.BACKLOG.value,
        ))
        self.db.create_task(Task(
            project_id=self.project_id, title="Task B",
            status=TaskStatus.IN_PROGRESS.value,
            assigned_role=AgentRole.CODER.value,
        ))

        all_tasks = self.db.list_tasks(self.project_id)
        self.assertEqual(len(all_tasks), 2)

        backlog = self.db.list_tasks(self.project_id, status="backlog")
        self.assertEqual(len(backlog), 1)

        coder_tasks = self.db.list_tasks(
            self.project_id, assigned_role="coder"
        )
        self.assertEqual(len(coder_tasks), 1)

    def test_update_task(self):
        task = self.db.create_task(Task(
            project_id=self.project_id, title="Update Me",
        ))
        updated = self.db.update_task(task.id, status="in_progress")
        self.assertEqual(updated.status, "in_progress")

    def test_delete_task(self):
        task = self.db.create_task(Task(
            project_id=self.project_id, title="Delete Me",
        ))
        self.assertTrue(self.db.delete_task(task.id))
        self.assertIsNone(self.db.get_task(task.id))

    def test_board_summary(self):
        self.db.create_task(Task(
            project_id=self.project_id, title="T1",
            status=TaskStatus.BACKLOG.value,
        ))
        self.db.create_task(Task(
            project_id=self.project_id, title="T2",
            status=TaskStatus.DONE.value,
        ))
        summary = self.db.get_board_summary(self.project_id)
        self.assertIn("task_counts", summary)
        self.assertEqual(summary["task_counts"].get("backlog", 0), 1)
        self.assertEqual(summary["task_counts"].get("done", 0), 1)


class TestKanban(TestBase):
    """Test Kanban board operations."""

    def setUp(self):
        super().setUp()
        self.board = KanbanBoard(self.db, self.project_id)

    def test_create_task(self):
        task = self.board.create_task(
            title="Design API",
            priority="high",
            assigned_role="architect",
        )
        self.assertEqual(task.title, "Design API")
        self.assertEqual(task.status, "backlog")

    def test_create_task_invalid_role(self):
        with self.assertRaises(ValueError):
            self.board.create_task(title="Bad", assigned_role="invalid_role")

    def test_move_task_valid(self):
        task = self.board.create_task(title="Move Me")
        moved = self.board.move_task(task.id, "in_progress")
        self.assertEqual(moved.status, "in_progress")

    def test_move_task_invalid_transition(self):
        task = self.board.create_task(title="Stay Put")
        with self.assertRaises(ValueError):
            self.board.move_task(task.id, "done")  # Can't go backlog → done

    def test_move_task_dependency_block(self):
        dep = self.board.create_task(title="Dependency")
        task = self.board.create_task(
            title="Blocked", depends_on=[dep.id]
        )
        # Dependency is still in backlog, can't start
        with self.assertRaises(ValueError):
            self.board.move_task(task.id, "in_progress")

    def test_move_task_dependency_resolved(self):
        dep = self.board.create_task(title="Dependency")
        self.board.move_task(dep.id, "in_progress")
        self.board.move_task(dep.id, "review")
        self.board.move_task(dep.id, "done")

        task = self.board.create_task(
            title="Unblocked", depends_on=[dep.id]
        )
        moved = self.board.move_task(task.id, "in_progress")
        self.assertEqual(moved.status, "in_progress")

    def test_board_state(self):
        self.board.create_task(title="T1")
        self.board.create_task(title="T2")
        state = self.board.get_board_state()
        self.assertIn("columns", state)
        self.assertEqual(state["columns"]["backlog"]["count"], 2)

    def test_assign_task(self):
        task = self.board.create_task(title="Assign Me")
        assigned = self.board.assign_task(task.id, "coder")
        self.assertEqual(assigned.assigned_role, "coder")

    def test_format_board_text(self):
        self.board.create_task(title="Text Task")
        text = self.board.format_board_text()
        self.assertIn("Board Status", text)
        self.assertIn("Text Task", text)


class TestAgentManager(TestBase):
    """Test agent session management."""

    def setUp(self):
        super().setUp()
        self.am = AgentManager(self.db, self.project_id)

    def test_spawn_agent(self):
        session = self.am.spawn_agent(role="coder")
        self.assertIn("agent-code", session.id)
        self.assertEqual(session.role, "coder")
        self.assertEqual(session.status, "active")
        self.assertTrue(len(session.system_prompt) > 100)

    def test_spawn_agent_with_task(self):
        task = self.db.create_task(Task(
            project_id=self.project_id, title="Code Task",
        ))
        session = self.am.spawn_agent(role="coder", task_id=task.id)
        self.assertEqual(session.current_task_id, task.id)

        # Check task was assigned
        updated_task = self.db.get_task(task.id)
        self.assertEqual(updated_task.assigned_session_id, session.id)

    def test_spawn_invalid_role(self):
        with self.assertRaises(ValueError):
            self.am.spawn_agent(role="invalid")

    def test_terminate_agent(self):
        session = self.am.spawn_agent(role="tester")
        terminated = self.am.terminate_agent(session.id, "Done")
        self.assertEqual(terminated.status, "terminated")
        self.assertIsNotNone(terminated.terminated_at)

    def test_terminate_already_terminated(self):
        session = self.am.spawn_agent(role="reviewer")
        self.am.terminate_agent(session.id)
        with self.assertRaises(ValueError):
            self.am.terminate_agent(session.id)

    def test_list_active_agents(self):
        self.am.spawn_agent(role="coder")
        self.am.spawn_agent(role="tester")
        s3 = self.am.spawn_agent(role="reviewer")
        self.am.terminate_agent(s3.id)

        agents = self.am.list_active_agents()
        self.assertEqual(len(agents), 2)

    def test_get_session_context(self):
        session = self.am.spawn_agent(role="architect")
        context = self.am.get_session_context(session.id)
        self.assertIn("system_prompt", context)
        self.assertIn("context_history", context)
        self.assertEqual(context["role"], "architect")

    def test_append_to_context(self):
        session = self.am.spawn_agent(role="coder")
        self.am.append_to_context(session.id, "user", "Implement the login flow")

        context = self.am.get_session_context(session.id)
        history = context["context_history"]
        self.assertTrue(
            any("login flow" in h.get("content", "") for h in history)
        )


class TestCommunicationBus(TestBase):
    """Test inter-agent communication."""

    def setUp(self):
        super().setUp()
        self.bus = CommunicationBus(self.db, self.project_id)
        self.am = AgentManager(self.db, self.project_id)

    def test_send_message(self):
        msg = self.bus.send_message(
            from_role="coder", to_role="reviewer",
            content="Code ready for review",
        )
        self.assertEqual(msg.from_role, "coder")
        self.assertEqual(msg.to_role, "reviewer")

    def test_send_message_with_aliases(self):
        msg = self.bus.send_message(
            from_role="dev", to_role="qa",
            content="Tests needed",
        )
        self.assertEqual(msg.from_role, "coder")
        self.assertEqual(msg.to_role, "tester")

    def test_mention_detection(self):
        msg = self.bus.send_message(
            from_role="coder", to_role="planner",
            content="@reviewer please check this",
        )
        self.assertEqual(msg.message_type, "mention")

    def test_broadcast(self):
        self.am.spawn_agent(role="coder")
        self.am.spawn_agent(role="tester")
        self.am.spawn_agent(role="reviewer")

        messages = self.bus.broadcast(
            from_role="planner", content="Sprint planning done"
        )
        self.assertGreaterEqual(len(messages), 2)

    def test_summon_agent(self):
        msg = self.bus.summon_agent(
            from_role="coder", target_role="security",
            reason="Need security review",
        )
        self.assertEqual(msg.message_type, "summon")

    def test_get_inbox(self):
        self.bus.send_message(
            from_role="coder", to_role="reviewer",
            content="msg 1",
        )
        self.bus.send_message(
            from_role="tester", to_role="reviewer",
            content="msg 2",
        )
        inbox = self.bus.get_inbox("reviewer")
        self.assertEqual(len(inbox), 2)

    def test_get_conversation(self):
        self.bus.send_message(
            from_role="coder", to_role="reviewer", content="a"
        )
        self.bus.send_message(
            from_role="reviewer", to_role="coder", content="b"
        )
        conv = self.bus.get_conversation("coder", "reviewer")
        self.assertEqual(len(conv), 2)


class TestAudit(TestBase):
    """Test audit trail functionality."""

    def setUp(self):
        super().setUp()
        self.audit = AuditTrail(self.db, self.project_id)
        # Create a real task so FK constraints are satisfied
        self.task = self.db.create_task(Task(
            project_id=self.project_id, title="Audit Test Task",
        ))
        self.task_id = self.task.id

    def test_log_event(self):
        entry = self.audit.log_event(
            action="test_action", details="Test details",
            task_id=self.task_id, agent_role="coder",
        )
        self.assertIsNotNone(entry.id)

    def test_get_task_trail(self):
        self.audit.log_event(
            action="task_created", details="Created", task_id=self.task_id
        )
        self.audit.log_event(
            action="task_moved", details="Moved", task_id=self.task_id
        )
        trail = self.audit.get_task_trail(self.task_id)
        self.assertEqual(len(trail), 2)

    def test_project_timeline(self):
        self.audit.log_event(action="a", details="1")
        self.audit.log_event(action="b", details="2")
        timeline = self.audit.get_project_timeline()
        self.assertEqual(len(timeline), 2)

    def test_action_summary(self):
        self.audit.log_event(action="task_created", details="1")
        self.audit.log_event(action="task_created", details="2")
        self.audit.log_event(action="task_moved", details="3")
        summary = self.audit.get_action_summary()
        self.assertEqual(summary["task_created"]["count"], 2)
        self.assertEqual(summary["task_moved"]["count"], 1)

    def test_export_json(self):
        self.audit.log_event(action="test", details="export")
        exported = self.audit.export_audit_log("json")
        data = json.loads(exported)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_export_csv(self):
        self.audit.log_event(action="test", details="csv")
        exported = self.audit.export_audit_log("csv")
        self.assertIn("timestamp", exported)
        self.assertIn("test", exported)

    def test_export_markdown(self):
        self.audit.log_event(action="test", details="md")
        exported = self.audit.export_audit_log("markdown")
        self.assertIn("Audit Log", exported)

    def test_format_project_report(self):
        self.audit.log_event(
            action="task_created", details="1", agent_role="coder"
        )
        report = self.audit.format_project_report()
        self.assertIn("Project Report", report)


class TestPipeline(TestBase):
    """Test CI/CD pipeline management."""

    def setUp(self):
        super().setUp()
        self.tmp_workspace = tempfile.mkdtemp()
        os.environ["AIPM_WORKSPACE"] = self.tmp_workspace
        self.pm = PipelineManager(self.db, self.project_id)

    def tearDown(self):
        super().tearDown()
        import shutil
        shutil.rmtree(self.tmp_workspace, ignore_errors=True)
        if "AIPM_WORKSPACE" in os.environ:
            del os.environ["AIPM_WORKSPACE"]

    def test_trigger_build(self):
        run = self.pm.trigger_stage("build")
        self.assertEqual(run.stage, "build")
        self.assertIn(run.status, ["success", "failed"])

    def test_trigger_invalid_stage(self):
        with self.assertRaises(ValueError):
            self.pm.trigger_stage("invalid_stage")

    def test_store_artifact(self):
        artifact = self.pm.store_artifact(
            name="test.py",
            content="print('hello')",
            artifact_type="code",
            file_path="src/test.py",
        )
        self.assertEqual(artifact.name, "test.py")
        self.assertGreater(artifact.size_bytes, 0)
        self.assertIsNotNone(artifact.checksum)

        # Verify file was written
        file_path = Path(self.tmp_workspace) / "src" / "test.py"
        self.assertTrue(file_path.exists())

    def test_pipeline_status(self):
        status = self.pm.get_pipeline_status()
        self.assertIn("stages", status)
        self.assertIn("build", status["stages"])

    def test_security_scan_findings(self):
        findings = self.pm._basic_security_scan(
            "x = eval(user_input)\nos.system(cmd)", "insecure.py"
        )
        self.assertGreaterEqual(len(findings), 2)

    def test_github_actions_config(self):
        config = self.pm.generate_github_actions_config()
        data = json.loads(config)
        self.assertIn("jobs", data)
        self.assertIn("build", data["jobs"])

    def test_format_pipeline_text(self):
        text = self.pm.format_pipeline_text()
        self.assertIn("Pipeline Status", text)


class TestIntegration(TestBase):
    """Integration tests for full workflows."""

    def test_full_workflow(self):
        """Test a complete task lifecycle: create → assign → spawn → move → done."""
        board = KanbanBoard(self.db, self.project_id)
        am = AgentManager(self.db, self.project_id)
        bus = CommunicationBus(self.db, self.project_id)
        audit = AuditTrail(self.db, self.project_id)

        # 1. Create tasks
        task1 = board.create_task(
            title="Design API endpoints",
            priority="high",
            assigned_role="architect",
        )
        task2 = board.create_task(
            title="Implement API",
            priority="high",
            assigned_role="coder",
            depends_on=[task1.id],
        )

        # 2. Spawn architect agent
        arch_session = am.spawn_agent("architect", task_id=task1.id)
        self.assertEqual(arch_session.role, "architect")

        # 3. Move task1 through lifecycle
        board.move_task(task1.id, "in_progress")
        board.move_task(task1.id, "review")

        # 4. Architect communicates with reviewer
        bus.send_message(
            from_role="architect", to_role="reviewer",
            content="API design ready for review",
            task_id=task1.id,
        )

        board.move_task(task1.id, "done")

        # 5. Now task2 deps are resolved — spawn coder
        coder_session = am.spawn_agent("coder", task_id=task2.id)
        board.move_task(task2.id, "in_progress")

        # 6. Coder signals reviewer
        bus.send_message(
            from_role="coder", to_role="reviewer",
            content="Implementation ready",
            task_id=task2.id,
        )

        board.move_task(task2.id, "review")
        board.move_task(task2.id, "done")

        # 7. Verify final state
        state = board.get_board_state()
        self.assertEqual(state["columns"]["done"]["count"], 2)

        # 8. Verify audit trail
        trail1 = audit.get_task_trail(task1.id)
        self.assertGreater(len(trail1), 3)

        trail2 = audit.get_task_trail(task2.id)
        self.assertGreater(len(trail2), 2)

        # 9. Verify agents
        agents = am.list_active_agents()
        self.assertEqual(len(agents), 2)

    def test_agent_reassignment(self):
        """Test reassigning an agent to a different task."""
        board = KanbanBoard(self.db, self.project_id)
        am = AgentManager(self.db, self.project_id)

        task1 = board.create_task(title="Task 1")
        task2 = board.create_task(title="Task 2")

        session = am.spawn_agent("coder", task_id=task1.id)
        self.assertEqual(session.current_task_id, task1.id)

        reassigned = am.reassign_agent(session.id, task2.id)
        self.assertEqual(reassigned.current_task_id, task2.id)


if __name__ == "__main__":
    unittest.main()
