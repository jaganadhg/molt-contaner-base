#!/usr/bin/env bash
# setup-ollama.sh — Bootstrap OpenClaw + Ollama + QMD Memory on Podman Compose
# Builds a custom image with QMD, pulls models, and starts everything.
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

OLLAMA_MODEL="${OLLAMA_MODEL:-phi4}"
CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-./data/config}"
WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-./data/workspace}"

# ── Data directories ─────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR" "$WORKSPACE_DIR"
chmod 777 "$CONFIG_DIR" "$WORKSPACE_DIR"

# Create workspace memory directories for QMD
mkdir -p "$WORKSPACE_DIR/memory"
chmod 777 "$WORKSPACE_DIR/memory"

# ── Seed OpenClaw config for Ollama + QMD memory ─────────────────────────────
OPENCLAW_JSON="$CONFIG_DIR/openclaw.json"
if [[ ! -f "$OPENCLAW_JSON" ]]; then
  cat > "$OPENCLAW_JSON" <<JSONEOF
{
  "wizard": {
    "lastRunAt": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)",
    "lastRunVersion": "2026.2.13",
    "lastRunCommand": "doctor",
    "lastRunMode": "local"
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/${OLLAMA_MODEL}"
      }
    }
  },
  "commands": {
    "native": "auto",
    "nativeSkills": "auto"
  },
  "gateway": {
    "mode": "local",
    "auth": {
      "mode": "token"
    },
    "controlUi": {
      "dangerouslyDisableDeviceAuth": true
    }
  },
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "http://ollama:11434",
        "models": []
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
    "lastTouchedAt": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
  }
}
JSONEOF
  echo "Created $OPENCLAW_JSON (model: ollama/${OLLAMA_MODEL}, memory: qmd)."
fi

# ── Pull images ──────────────────────────────────────────────────────────────
echo ""
echo "Pulling container images ..."
podman pull docker.io/ollama/ollama:latest
podman pull ghcr.io/openclaw/openclaw:latest

# ── Build custom OpenClaw+QMD image ──────────────────────────────────────────
echo ""
echo "Building openclaw-qmd image (installs Bun + QMD in the container)..."
echo "This may take a few minutes on first run."
podman build -t openclaw-qmd:latest -f Dockerfile.qmd . 2>&1
echo "openclaw-qmd image built."

# ── Start Ollama first ───────────────────────────────────────────────────────
echo ""
echo "Starting Ollama server ..."
podman compose -f "$COMPOSE_FILE" up -d ollama

# Wait for Ollama API to be ready
echo "Waiting for Ollama API ..."
for i in $(seq 1 30); do
  if podman exec ollama curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama API ready."
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "Warning: Ollama API did not respond in 30s. Model pull may fail."
  fi
  sleep 1
done

# ── Pull the Phi model ───────────────────────────────────────────────────────
echo ""
echo "Pulling model: ${OLLAMA_MODEL} (this may take a few minutes) ..."
podman exec ollama ollama pull "${OLLAMA_MODEL}"
echo "Model ${OLLAMA_MODEL} ready."

# ── Start OpenClaw gateway ───────────────────────────────────────────────────
echo ""
echo "Starting OpenClaw gateway ..."
podman compose -f "$COMPOSE_FILE" up -d openclaw-gateway

# Read the token for display
TOKEN="$(grep '^OPENCLAW_GATEWAY_TOKEN=' .env | cut -d= -f2)"

echo ""
echo "=============================================="
echo " OpenClaw + Ollama (${OLLAMA_MODEL}) + QMD is running!"
echo "=============================================="
echo ""
echo " Gateway:   http://localhost:${OPENCLAW_GATEWAY_PORT:-18789}"
echo " Dashboard: http://localhost:${OPENCLAW_GATEWAY_PORT:-18789}/#token=${TOKEN}"
echo " Ollama:    http://localhost:${OLLAMA_HOST_PORT:-11434}"
echo " Model:     ollama/${OLLAMA_MODEL}"
echo " Memory:    QMD (BM25 search mode)"
echo " WhatsApp:  Enabled (link via dashboard QR code)"
echo " Config:    ${CONFIG_DIR}"
echo " Workspace: ${WORKSPACE_DIR}"
echo ""
echo " WhatsApp Setup:"
echo "   1. Open the Dashboard URL above"
echo "   2. Go to Channels → WhatsApp → Login"
echo "   3. Scan the QR code with WhatsApp on your phone"
echo "      (Settings → Linked Devices → Link a Device)"
echo ""
echo " QMD Memory:"
echo "   Place .md files in ${WORKSPACE_DIR}/memory/ for persistent memory."
echo "   Or create ${WORKSPACE_DIR}/MEMORY.md for quick notes."
echo "   QMD indexes these automatically every 5 minutes."
echo ""
echo " Useful commands:"
echo "   podman compose -f ${COMPOSE_FILE} logs -f"
echo "   podman compose -f ${COMPOSE_FILE} down"
echo "   podman exec ollama ollama list"
echo "   podman exec openclaw-gateway qmd status"
echo ""
