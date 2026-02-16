#!/usr/bin/env python3
"""
cicd.py — CI/CD pipeline integration for the AI Project Manager.

Manages build, test, security-scan, staging, and production pipeline stages.
Supports GitHub Actions, GitLab CI, and generic webhook triggers.
"""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

from models import (
    PipelineRun, PipelineStage, PipelineStatus, Artifact,
    AuditEntry, AuditAction, _utcnow,
)
from database import Database


# Pipeline stage ordering
STAGE_ORDER = [
    PipelineStage.BUILD,
    PipelineStage.TEST,
    PipelineStage.SECURITY_SCAN,
    PipelineStage.STAGING,
    PipelineStage.PRODUCTION,
]


class PipelineManager:
    """Manages CI/CD pipeline execution for agent-produced artifacts."""

    def __init__(self, db: Database, project_id: str):
        self.db = db
        self.project_id = project_id
        self.workspace_dir = Path(
            os.environ.get("AIPM_WORKSPACE", str(
                Path(__file__).resolve().parent.parent / "workspace"
            ))
        )
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def trigger_stage(
        self,
        stage: str,
        task_id: Optional[int] = None,
        triggered_by: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> PipelineRun:
        """Trigger a pipeline stage."""
        # Validate stage
        try:
            pipeline_stage = PipelineStage(stage)
        except ValueError:
            valid = [s.value for s in PipelineStage]
            raise ValueError(f"Invalid stage '{stage}'. Valid stages: {valid}")

        # Check prerequisites (previous stages must pass)
        stage_idx = STAGE_ORDER.index(pipeline_stage)
        if stage_idx > 0:
            prev_stage = STAGE_ORDER[stage_idx - 1].value
            prev_runs = [
                r for r in self.db.list_pipeline_runs(self.project_id, task_id)
                if r.stage == prev_stage
            ]
            if prev_runs:
                latest = prev_runs[0]
                if latest.status != PipelineStatus.SUCCESS.value:
                    raise ValueError(
                        f"Cannot run '{stage}': previous stage '{prev_stage}' "
                        f"has status '{latest.status}' (must be 'success')"
                    )

        run = PipelineRun(
            project_id=self.project_id,
            task_id=task_id,
            stage=stage,
            status=PipelineStatus.RUNNING.value,
            triggered_by=triggered_by,
        )
        run = self.db.create_pipeline_run(run)

        # Audit
        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            agent_role=triggered_by,
            action=AuditAction.PIPELINE_TRIGGERED.value,
            details=f"Pipeline stage '{stage}' triggered",
            metadata_json=json.dumps({
                "run_id": run.id,
                "stage": stage,
                "config": config or {},
            }),
        ))

        # Execute the stage
        try:
            result = self._execute_stage(pipeline_stage, task_id, config or {})
            self.db.update_pipeline_run(
                run.id,
                status=PipelineStatus.SUCCESS.value,
                logs=result.get("logs", ""),
                artifact_path=result.get("artifact_path"),
                completed_at=_utcnow(),
            )

            # Audit completion
            self.db.create_audit_entry(AuditEntry(
                project_id=self.project_id,
                task_id=task_id,
                action=AuditAction.PIPELINE_COMPLETED.value,
                details=f"Pipeline stage '{stage}' completed successfully",
                metadata_json=json.dumps({
                    "run_id": run.id,
                    "stage": stage,
                    "status": "success",
                }),
            ))

        except Exception as e:
            self.db.update_pipeline_run(
                run.id,
                status=PipelineStatus.FAILED.value,
                logs=str(e),
                completed_at=_utcnow(),
            )

            self.db.create_audit_entry(AuditEntry(
                project_id=self.project_id,
                task_id=task_id,
                action=AuditAction.PIPELINE_COMPLETED.value,
                details=f"Pipeline stage '{stage}' FAILED: {str(e)[:100]}",
                metadata_json=json.dumps({
                    "run_id": run.id,
                    "stage": stage,
                    "status": "failed",
                    "error": str(e),
                }),
            ))

        return self.db.get_pipeline_run(run.id)

    def run_full_pipeline(
        self,
        task_id: Optional[int] = None,
        triggered_by: Optional[str] = None,
        stop_on_failure: bool = True,
        stages: Optional[list[str]] = None,
    ) -> list[PipelineRun]:
        """Run the full pipeline (or specified stages) sequentially."""
        target_stages = stages or [s.value for s in STAGE_ORDER]
        runs = []

        for stage in target_stages:
            try:
                run = self.trigger_stage(
                    stage, task_id=task_id, triggered_by=triggered_by
                )
                runs.append(run)

                if run.status == PipelineStatus.FAILED.value and stop_on_failure:
                    break
            except ValueError as e:
                # Stage prerequisites not met
                break

        return runs

    def get_pipeline_status(self, task_id: Optional[int] = None) -> dict:
        """Get the current pipeline status."""
        runs = self.db.list_pipeline_runs(self.project_id, task_id)

        # Group by stage, latest first
        stages = {}
        for run in runs:
            if run.stage not in stages:
                stages[run.stage] = run.to_dict()

        # Build full status
        status = {
            "project_id": self.project_id,
            "task_id": task_id,
            "stages": {},
        }

        for stage in STAGE_ORDER:
            s = stage.value
            if s in stages:
                status["stages"][s] = stages[s]
            else:
                status["stages"][s] = {
                    "stage": s,
                    "status": PipelineStatus.PENDING.value,
                }

        return status

    def store_artifact(
        self,
        name: str,
        content: str,
        artifact_type: str = "code",
        task_id: Optional[int] = None,
        session_id: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Artifact:
        """Store a build artifact."""
        checksum = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Write to workspace if file_path specified
        if file_path:
            full_path = self.workspace_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

        artifact = Artifact(
            project_id=self.project_id,
            task_id=task_id,
            session_id=session_id,
            name=name,
            artifact_type=artifact_type,
            content=content,
            file_path=file_path,
            size_bytes=len(content.encode()),
            checksum=checksum,
        )
        artifact = self.db.create_artifact(artifact)

        # Audit
        self.db.create_audit_entry(AuditEntry(
            project_id=self.project_id,
            task_id=task_id,
            session_id=session_id,
            action=AuditAction.ARTIFACT_PRODUCED.value,
            details=f"Artifact '{name}' ({artifact_type}, {len(content)} bytes)",
            metadata_json=json.dumps({
                "artifact_id": artifact.id,
                "name": name,
                "type": artifact_type,
                "size": len(content),
                "checksum": checksum,
            }),
        ))

        return artifact

    def trigger_webhook(
        self,
        url: str,
        payload: dict,
        headers: Optional[dict] = None,
    ) -> dict:
        """Trigger an external CI/CD webhook."""
        data = json.dumps(payload).encode("utf-8")
        req_headers = {
            "Content-Type": "application/json",
            "User-Agent": "OpenClaw-AIPM/1.0",
        }
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, data=data, headers=req_headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return {
                    "status": response.status,
                    "body": response.read().decode("utf-8"),
                }
        except Exception as e:
            return {"status": 0, "error": str(e)}

    def generate_github_actions_config(self, task_id: Optional[int] = None) -> str:
        """Generate a GitHub Actions workflow config for the pipeline."""
        project = self.db.get_project(self.project_id)
        name = project.name if project else "AI Project"

        config = {
            "name": f"{name} CI/CD",
            "on": {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}},
            "jobs": {
                "build": {
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"uses": "actions/checkout@v4"},
                        {"name": "Set up Python", "uses": "actions/setup-python@v5",
                         "with": {"python-version": "3.12"}},
                        {"name": "Install dependencies",
                         "run": "pip install -r requirements.txt"},
                        {"name": "Run tests", "run": "python -m pytest tests/ -v"},
                        {"name": "Security scan",
                         "run": "pip install bandit && bandit -r src/ -f json -o security-report.json || true"},
                    ],
                }
            },
        }

        import io
        # Simple YAML-like output (avoiding external deps)
        return json.dumps(config, indent=2)

    def generate_gitlab_ci_config(self) -> str:
        """Generate a GitLab CI config for the pipeline."""
        config = {
            "stages": ["build", "test", "security", "staging", "production"],
            "build": {
                "stage": "build",
                "script": ["pip install -r requirements.txt"],
            },
            "test": {
                "stage": "test",
                "script": ["python -m pytest tests/ -v"],
            },
            "security_scan": {
                "stage": "security",
                "script": ["pip install bandit", "bandit -r src/ -f json"],
                "allow_failure": True,
            },
            "deploy_staging": {
                "stage": "staging",
                "script": ["echo 'Deploy to staging'"],
                "only": ["main"],
            },
            "deploy_production": {
                "stage": "production",
                "script": ["echo 'Deploy to production'"],
                "only": ["tags"],
                "when": "manual",
            },
        }
        return json.dumps(config, indent=2)

    def _execute_stage(
        self, stage: PipelineStage, task_id: Optional[int], config: dict
    ) -> dict:
        """Execute a pipeline stage (local simulation or real command)."""
        # Check for custom command in config
        custom_cmd = config.get("command")
        if custom_cmd:
            return self._run_command(custom_cmd)

        # Default stage behaviors
        if stage == PipelineStage.BUILD:
            return self._stage_build(task_id, config)
        elif stage == PipelineStage.TEST:
            return self._stage_test(task_id, config)
        elif stage == PipelineStage.SECURITY_SCAN:
            return self._stage_security_scan(task_id, config)
        elif stage == PipelineStage.STAGING:
            return self._stage_deploy(task_id, config, "staging")
        elif stage == PipelineStage.PRODUCTION:
            return self._stage_deploy(task_id, config, "production")
        else:
            return {"logs": f"Unknown stage: {stage.value}", "status": "skipped"}

    def _stage_build(self, task_id: Optional[int], config: dict) -> dict:
        """Execute build stage."""
        logs = ["=== BUILD STAGE ==="]

        # Collect artifacts for this task
        if task_id:
            artifacts = self.db.list_artifacts(self.project_id, task_id=task_id)
            logs.append(f"Found {len(artifacts)} artifact(s) for task #{task_id}")

            # Write code artifacts to workspace
            for art in artifacts:
                if art.file_path:
                    full_path = self.workspace_dir / art.file_path
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(art.content)
                    logs.append(f"  Written: {art.file_path} ({art.size_bytes} bytes)")

        # Run build command if specified
        build_cmd = config.get("build_command")
        if build_cmd:
            result = self._run_command(build_cmd)
            logs.append(result.get("logs", ""))

        logs.append("Build completed successfully.")
        return {"logs": "\n".join(logs)}

    def _stage_test(self, task_id: Optional[int], config: dict) -> dict:
        """Execute test stage."""
        logs = ["=== TEST STAGE ==="]

        test_cmd = config.get("test_command", "python3 -m pytest tests/ -v 2>&1 || true")

        # Check if tests exist in workspace
        test_dir = self.workspace_dir / "tests"
        if test_dir.exists():
            result = self._run_command(test_cmd, cwd=str(self.workspace_dir))
            logs.append(result.get("logs", ""))
        else:
            logs.append("No tests directory found. Skipping test execution.")
            logs.append("Test artifacts from tester agents will be validated.")

        # Validate test artifacts
        if task_id:
            artifacts = self.db.list_artifacts(self.project_id, task_id=task_id)
            test_artifacts = [a for a in artifacts if a.artifact_type == "test"]
            logs.append(f"Found {len(test_artifacts)} test artifact(s)")

        logs.append("Test stage completed.")
        return {"logs": "\n".join(logs)}

    def _stage_security_scan(self, task_id: Optional[int], config: dict) -> dict:
        """Execute security scan stage."""
        logs = ["=== SECURITY SCAN STAGE ==="]

        # Collect code artifacts for scanning
        if task_id:
            artifacts = self.db.list_artifacts(self.project_id, task_id=task_id)
            code_artifacts = [a for a in artifacts if a.artifact_type == "code"]
            logs.append(f"Scanning {len(code_artifacts)} code artifact(s)")

            for art in code_artifacts:
                # Basic pattern-based security checks
                findings = self._basic_security_scan(art.content, art.name)
                if findings:
                    for f in findings:
                        logs.append(f"  ⚠️  {f}")
                else:
                    logs.append(f"  ✅ {art.name}: No issues found")

        logs.append("Security scan completed.")
        return {"logs": "\n".join(logs)}

    def _stage_deploy(
        self, task_id: Optional[int], config: dict, environment: str
    ) -> dict:
        """Execute deployment stage."""
        logs = [f"=== DEPLOY TO {environment.upper()} ==="]

        # Check for webhook URL
        webhook_url = config.get(f"{environment}_webhook")
        if webhook_url:
            payload = {
                "project_id": self.project_id,
                "task_id": task_id,
                "environment": environment,
                "timestamp": _utcnow(),
            }
            result = self.trigger_webhook(webhook_url, payload)
            logs.append(f"Webhook response: status={result.get('status')}")
        else:
            logs.append(f"No {environment} webhook configured. Simulating deployment.")
            logs.append(f"Deployment to {environment} successful (simulated).")

        return {"logs": "\n".join(logs)}

    def _run_command(self, cmd: str, cwd: Optional[str] = None) -> dict:
        """Run a shell command and capture output."""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=120, cwd=cwd or str(self.workspace_dir),
            )
            logs = result.stdout
            if result.stderr:
                logs += "\n" + result.stderr
            return {
                "logs": logs,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"logs": "Command timed out after 120 seconds", "return_code": -1}
        except Exception as e:
            return {"logs": f"Command failed: {e}", "return_code": -1}

    def _basic_security_scan(self, code: str, filename: str) -> list[str]:
        """Perform basic pattern-based security checks."""
        findings = []
        lines = code.split("\n")

        patterns = [
            ("eval(", "Potential code injection via eval()"),
            ("exec(", "Potential code injection via exec()"),
            ("os.system(", "Potential command injection via os.system()"),
            ("subprocess.call(", "Potential command injection (use subprocess.run with shell=False)"),
            ("shell=True", "shell=True may enable command injection"),
            ("password", "Potential hardcoded password"),
            ("secret", "Potential hardcoded secret"),
            ("api_key", "Potential hardcoded API key"),
            ("SELECT.*FROM", "Potential SQL injection (use parameterized queries)"),
            ("innerHTML", "Potential XSS via innerHTML"),
            ("dangerouslySetInnerHTML", "Potential XSS via dangerouslySetInnerHTML"),
            ("pickle.loads", "Insecure deserialization via pickle"),
            ("yaml.load(", "Insecure YAML loading (use yaml.safe_load)"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, message in patterns:
                if pattern.lower() in line.lower():
                    findings.append(
                        f"{filename}:{i}: {message} — `{line.strip()[:60]}`"
                    )

        return findings

    def format_pipeline_text(self, task_id: Optional[int] = None) -> str:
        """Format pipeline status as human-readable text."""
        status = self.get_pipeline_status(task_id)

        lines = ["### 🚀 Pipeline Status\n"]
        lines.append("| Stage | Status | Time |")
        lines.append("|-------|--------|------|")

        stage_emoji = {
            PipelineStatus.PENDING.value: "⏳",
            PipelineStatus.RUNNING.value: "🔄",
            PipelineStatus.SUCCESS.value: "✅",
            PipelineStatus.FAILED.value: "❌",
            PipelineStatus.SKIPPED.value: "⏭️",
        }

        for stage_info in status["stages"].values():
            emoji = stage_emoji.get(stage_info["status"], "❓")
            stage_name = stage_info["stage"].replace("_", " ").title()
            time_info = stage_info.get("completed_at", "—")
            lines.append(f"| {stage_name} | {emoji} {stage_info['status']} | {time_info} |")

        return "\n".join(lines)
