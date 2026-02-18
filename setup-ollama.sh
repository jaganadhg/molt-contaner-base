#!/usr/bin/env bash
# setup-ollama.sh — Bootstrap OpenClaw + QMD Memory on Podman Compose
# Builds a custom image with QMD, deploys skills, and starts everything.
# Uses cloud LLM providers (OpenAI, Anthropic, etc.) — set API keys in .env
set -euo pipefail

COMPOSE_FILE="podman-compose-ollama.yml"
ENV_EXAMPLE=".env.ollama.example"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ── Preflight ────────────────────────────────────────────────────────────────
require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: $1 is required but not found." >&2
    exit 1
  fi
}

require_cmd podman
if ! podman compose version >/dev/null 2>&1; then
  echo "Error: 'podman compose' is not available."
  echo "Install podman-compose:  pip install podman-compose"
  echo "  or:                    sudo dnf install podman-compose"
  exit 1
fi

# ── .env setup ───────────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  echo "Creating .env from ${ENV_EXAMPLE} ..."
  cp "$ENV_EXAMPLE" .env

  # Generate a random gateway token
  if command -v openssl >/dev/null 2>&1; then
    TOKEN="$(openssl rand -hex 32)"
  else
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  sed -i "s/^OPENCLAW_GATEWAY_TOKEN=.*/OPENCLAW_GATEWAY_TOKEN=${TOKEN}/" .env
  echo "Generated OPENCLAW_GATEWAY_TOKEN."
else
  echo ".env already exists — skipping."
fi

# ── Source env ───────────────────────────────────────────────────────────────
set -a
source .env 2>/dev/null || true
set +a

CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-./data/config}"
WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-./data/workspace}"

# ── Data directories ─────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR" "$WORKSPACE_DIR"

# Create workspace memory directories for QMD
mkdir -p "$WORKSPACE_DIR/memory"

# The container runs as uid 1000 (node), mapped to a sub-UID in rootless Podman.
# Use 700 to restrict access; podman maps ownership automatically.
CONTAINER_UID=$(podman run --rm ghcr.io/openclaw/openclaw:latest id -u 2>/dev/null || echo "")
if [[ -n "$CONTAINER_UID" ]]; then
  podman unshare chown -R "$CONTAINER_UID:$CONTAINER_UID" "$CONFIG_DIR" "$WORKSPACE_DIR"
fi
chmod 700 "$CONFIG_DIR" "$WORKSPACE_DIR" "$WORKSPACE_DIR/memory"

# Deploy custom skills to workspace
if [[ -d "skills" ]]; then
  echo "Deploying custom skills to workspace ..."
  mkdir -p "$WORKSPACE_DIR/skills"
  cp -r skills/* "$WORKSPACE_DIR/skills/"
  chmod -R 755 "$WORKSPACE_DIR/skills"
fi

# Deploy AGENTS.md to workspace
echo "Writing AGENTS.md to workspace ..."
cat > "$WORKSPACE_DIR/AGENTS.md" << 'AGENTSEOF'
# AGENTS.md - Workspace

## Every Session
1. Read SOUL.md - this is who you are
2. Read USER.md - who you are helping
3. Read memory/YYYY-MM-DD.md (today + yesterday) for context

## Memory
- Daily notes: memory/YYYY-MM-DD.md - raw logs
- Long-term: MEMORY.md - curated memories
Capture decisions, context, things to remember.

## Tools
Skills provide your tools. Check SKILL.md for each skill.
Keep local notes in TOOLS.md.

## CRITICAL: News & Topic Queries (MUST)
When asked about news, updates, latest information, or any topic queries, the agent MUST run the `topic-news-search` skill using the bash/exec tool and present the results exactly in the SKILL.md output format.

Required procedure (order matters):
1. Invoke the skill via exec and pass the user's query verbatim:

   ```bash
   python3 skills/topic-news-search/scripts/fetch_news.py "<QUERY>"
   ```

2. If the script returns articles, summarize and categorize each result per `SKILL.md`.
3. If the script returns zero results, reply exactly: "No recent news found for '<QUERY>'. Would you like me to try a different query or timeframe?" and offer alternatives.

Absolute prohibitions:
- DO NOT use `web_search` or `web_fetch` for news queries.
- DO NOT fabricate or infer news from memory — memory may be used for background context only.

Rationale: this ensures reproducible, auditable news results and prevents hallucinated updates.
    "lastRunCommand": "doctor",
    "lastRunMode": "local"
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "openai/gpt-4o-mini"
      },
      "bootstrapMaxChars": 6000,
      "maxConcurrent": 1
    }
  },
  "commands": {
    "native": "auto",
    "nativeSkills": "auto",
    "bash": true
  },
  "tools": {
    "web": {
      "search": { "enabled": false },
      "fetch": { "enabled": false }
    }
  },
  "gateway": {
    "mode": "local",
    "auth": {
      "mode": "token"
    },
    "controlUi": {}
  },
  "models": {
    "providers": {
      "openai": {
        "models": [
          {
            "id": "gpt-4o-mini",
            "name": "GPT-4o Mini",
            "contextWindow": 128000
          },
          {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "contextWindow": 128000
          }
        ]
      }
    }
  },
  "plugins": {
    "entries": {
      "whatsapp": {
        "enabled": true
      }
    }
  },
  "memory": {
    "backend": "qmd",
    "citations": "auto",
    "qmd": {
      "includeDefaultMemory": true,
      "searchMode": "search",
      "sessions": {
        "enabled": true
      },
      "update": {
        "onBoot": true,
        "waitForBootSync": false,
        "interval": "5m"
      }
    }
  },
  "meta": {
    "lastTouchedVersion": "2026.2.13",
    "lastTouchedAt": "2026-01-01T00:00:00.000Z"
  }
}
JSONEOF
  echo "Created $OPENCLAW_JSON (model: openai/gpt-4o-mini, memory: qmd)."
fi

# ── Pull image & build QMD layer ─────────────────────────────────────────────
echo ""
echo "Pulling OpenClaw base image ..."
podman pull ghcr.io/openclaw/openclaw:latest

echo ""
echo "Building openclaw-qmd image (installs Bun + QMD in the container)..."
echo "This may take a few minutes on first run."
podman build -t openclaw-qmd:latest -f Dockerfile.qmd . 2>&1
echo "openclaw-qmd image built."

# ── Start OpenClaw gateway ───────────────────────────────────────────────────
echo ""
echo "Starting OpenClaw gateway ..."
podman compose -f "$COMPOSE_FILE" up -d openclaw-gateway

# Read the token for display
TOKEN="$(grep '^OPENCLAW_GATEWAY_TOKEN=' .env | cut -d= -f2)"

echo ""
echo "=============================================="
echo " OpenClaw + QMD Memory is running!"
echo "=============================================="
echo ""
echo " Gateway:   http://localhost:${OPENCLAW_GATEWAY_PORT:-18789}"
echo " Dashboard: http://localhost:${OPENCLAW_GATEWAY_PORT:-18789}/#token=${TOKEN:0:8}…"
echo "            (full token in .env — do not share it)"
echo " Model:     openai/gpt-4o-mini (configure in dashboard)"
echo " Memory:    QMD (BM25 search mode)"
echo " WhatsApp:  Enabled (link via dashboard QR code)"
echo " Config:    ${CONFIG_DIR}"
echo " Workspace: ${WORKSPACE_DIR}"
echo ""
echo " Setup:"
echo "   1. Set your OPENAI_API_KEY in .env (or configure via dashboard)"
echo "   2. Open the Dashboard URL above"
echo "   3. For WhatsApp: go to Channels → WhatsApp → scan QR code"
echo ""
echo " QMD Memory:"
echo "   Place .md files in ${WORKSPACE_DIR}/memory/ for persistent memory."
echo "   Or create ${WORKSPACE_DIR}/MEMORY.md for quick notes."
echo "   QMD indexes these automatically every 5 minutes."
echo ""
echo " Useful commands:"
echo "   podman compose -f ${COMPOSE_FILE} logs -f"
echo "   podman compose -f ${COMPOSE_FILE} down"
echo "   podman exec openclaw-gateway qmd status"
echo ""
