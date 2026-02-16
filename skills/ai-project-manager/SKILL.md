---
name: ai-project-manager
description: "Multi-Session AI Project Manager with Agent Swarms. Spawns and orchestrates multiple persistent agent sessions (Planner, Coder, Tester, Reviewer, Security Auditor) on a real-time Kanban board with audit trails and CI/CD integration."
metadata:
  {
    "openclaw":
      {
        "emoji": "🧠",
        "requires": { "bins": ["python3"] },
      },
  }
---

# Multi-Session AI Project Manager with Agent Swarms

An OpenClaw skill that turns your AI assistant into a **distributed AI team**. It spawns and orchestrates multiple persistent agent sessions — each configured for a specific role — collaborating on complex projects through a real-time Kanban board.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   ORCHESTRATOR                       │
│  ┌───────────┐ ┌───────────┐ ┌───────────────────┐  │
│  │  Kanban    │ │  Agent    │ │  Inter-Agent      │  │
│  │  Board     │ │  Session  │ │  Communication    │  │
│  │  Manager   │ │  Manager  │ │  Bus              │  │
│  └─────┬─────┘ └─────┬─────┘ └────────┬──────────┘  │
│        │              │                │             │
│  ┌─────┴──────────────┴────────────────┴──────────┐  │
│  │              SQLite Database                    │  │
│  │  (Tasks, Sessions, Messages, Audit Logs)       │  │
│  └────────────────────────────────────────────────┘  │
│        │                                             │
│  ┌─────┴─────┐  ┌─────────────┐  ┌──────────────┐  │
│  │  Audit &   │  │  CI/CD      │  │  Web UI      │  │
│  │  Trace     │  │  Pipeline   │  │  (Kanban)    │  │
│  └───────────┘  └─────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────┘
```

## Agent Roles

| Role | Emoji | Description |
|------|-------|-------------|
| **Architect** | 🏗️ | System design, requirements analysis, task decomposition |
| **Coder** | 💻 | Implementation, code generation, refactoring |
| **Tester** | 🧪 | Test creation, test execution, quality assurance |
| **Reviewer** | 👀 | Code review, best practices enforcement |
| **Security Auditor** | 🔒 | Security analysis, vulnerability scanning, compliance |
| **UX Designer** | 🎨 | UI/UX design guidance, accessibility review |
| **DevOps** | 🚀 | CI/CD pipeline management, deployment automation |
| **Planner** | 📋 | Sprint planning, task prioritization, timeline management |

## How to Use

### Step 1: Initialize a Project

```bash
python3 skills/ai-project-manager/scripts/orchestrator.py init --name "My Project" --description "Build a REST API"
```

This creates the project database, initializes the Kanban board, and registers default agent roles.

### Step 2: Launch the Kanban Board UI

```bash
python3 skills/ai-project-manager/scripts/server.py --port 8420
```

Open `http://localhost:8420` to view the real-time Kanban board.

### Step 3: Create Tasks

```bash
python3 skills/ai-project-manager/scripts/orchestrator.py task create \
  --title "Design API endpoints" \
  --description "Define REST endpoints for user management" \
  --assign architect \
  --priority high
```

### Step 4: Spawn Agent Sessions

```bash
python3 skills/ai-project-manager/scripts/orchestrator.py agent spawn --role coder --task-id 3
```

This starts a new agent session tailored for the `coder` role, pre-loaded with context from task #3.

### Step 5: List Project Status

```bash
python3 skills/ai-project-manager/scripts/orchestrator.py status
```

Returns a JSON summary of all tasks, agent sessions, and pipeline state.

### Step 6: Inter-Agent Communication

Agents can mention or summon each other:

```bash
python3 skills/ai-project-manager/scripts/orchestrator.py message \
  --from coder --to reviewer \
  --content "Code for task #3 is ready for review" \
  --task-id 3
```

### Step 7: View Audit Trail

```bash
python3 skills/ai-project-manager/scripts/orchestrator.py audit --task-id 3
```

Returns the full interaction history for a task.

### Step 8: Trigger CI/CD Pipeline

```bash
python3 skills/ai-project-manager/scripts/orchestrator.py pipeline run \
  --task-id 3 --stage test
```

Stages: `build` → `test` → `security-scan` → `staging` → `production`

## Command Reference

### `orchestrator.py` Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize a new project |
| `task create` | Create a new task card |
| `task move` | Move task between Kanban columns |
| `task list` | List all tasks with filters |
| `agent spawn` | Spawn a new agent session for a role |
| `agent list` | List active agent sessions |
| `agent terminate` | Terminate an agent session |
| `message` | Send inter-agent message |
| `status` | Full project status overview |
| `audit` | View audit trail |
| `pipeline run` | Trigger CI/CD pipeline stage |
| `pipeline status` | View pipeline status |
| `board export` | Export board state as JSON |

## Output Format

### Task Status Output

```
## 🧠 Project: My Project

### 📊 Board Status
| Column      | Count | Tasks                    |
|-------------|-------|--------------------------|
| 📥 Backlog  | 3     | #1, #4, #7               |
| 🔄 In Progress | 2  | #2 (💻 Coder), #5 (🧪 Tester) |
| 👀 Review   | 1     | #3 (👀 Reviewer)         |
| ✅ Done     | 4     | #6, #8, #9, #10          |

### 🤖 Active Agents
| Agent        | Role       | Current Task | Session Age |
|--------------|------------|-------------|-------------|
| agent-coder-1 | 💻 Coder  | #2          | 12m         |
| agent-test-1  | 🧪 Tester | #5          | 8m          |
| agent-rev-1   | 👀 Reviewer | #3        | 3m          |

### 📬 Recent Messages
- 💻 **Coder** → 👀 **Reviewer**: "Task #2 code ready for review"
- 🧪 **Tester** → 💻 **Coder**: "3 tests failing in auth module"
- 🔒 **Security** → 📋 **Planner**: "Critical: SQL injection in task #6"
```

### Audit Trail Output

```
## 📜 Audit Trail — Task #3

| Timestamp           | Agent       | Action              | Details                    |
|---------------------|-------------|----------------------|----------------------------|
| 2026-02-16 09:00:00 | 🏗️ Architect | created task        | "Design API endpoints"     |
| 2026-02-16 09:05:00 | 📋 Planner  | assigned to coder   | priority: high             |
| 2026-02-16 09:10:00 | 💻 Coder    | moved to In Progress | session: agent-coder-1     |
| 2026-02-16 10:30:00 | 💻 Coder    | artifact produced   | api_endpoints.py (142 LOC) |
| 2026-02-16 10:31:00 | 💻 Coder    | mentioned reviewer  | "Ready for review"         |
| 2026-02-16 10:45:00 | 👀 Reviewer | moved to Review     | —                          |
| 2026-02-16 11:00:00 | 👀 Reviewer | comment             | "LGTM, minor style fix"   |
| 2026-02-16 11:05:00 | 💻 Coder    | moved to Done       | —                          |
```

## Important Notes

- **Always initialize a project** before creating tasks or spawning agents.
- Agent sessions are **persistent** — they maintain context across interactions within the same task.
- The Kanban board UI updates in **real-time** via Server-Sent Events (SSE).
- All agent interactions are logged in the audit database for traceability.
- The CI/CD pipeline integration supports **GitHub Actions**, **GitLab CI**, and **generic webhook** triggers.
- Inter-agent messages create **dependency chains** that the Planner agent uses for scheduling.
- Use `--format json` on any command for machine-readable output.
