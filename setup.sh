#!/usr/bin/env bash
# setup.sh — Bootstrap OpenClaw on Podman Compose
# Creates data dirs, generates a gateway token, and starts the container.
set -euo pipefail

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
  echo "Creating .env from .env.example ..."
  cp .env.example .env

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

# ── Data directories ─────────────────────────────────────────────────────────
source .env 2>/dev/null || true
CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-./data/config}"
WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-./data/workspace}"

mkdir -p "$CONFIG_DIR" "$WORKSPACE_DIR"
# The container runs as uid 1000 (node), mapped to a sub-UID in rootless Podman.
# Use 700 to restrict access; podman maps ownership automatically.
CONTAINER_UID=$(podman run --rm ghcr.io/openclaw/openclaw:latest id -u 2>/dev/null || echo "")
if [[ -n "$CONTAINER_UID" ]]; then
  podman unshare chown "$CONTAINER_UID:$CONTAINER_UID" "$CONFIG_DIR" "$WORKSPACE_DIR"
fi
chmod 700 "$CONFIG_DIR" "$WORKSPACE_DIR"

# Seed a minimal config so the gateway starts without the interactive wizard
OPENCLAW_JSON="$CONFIG_DIR/openclaw.json"
if [[ ! -f "$OPENCLAW_JSON" ]]; then
  cat > "$OPENCLAW_JSON" <<'JSON'
{ "gateway": { "mode": "local" } }
JSON
  echo "Created minimal $OPENCLAW_JSON."
fi

# ── Pull image ───────────────────────────────────────────────────────────────
echo "Pulling OpenClaw image ..."
podman pull ghcr.io/openclaw/openclaw:latest

# ── Start ────────────────────────────────────────────────────────────────────
echo ""
echo "Starting OpenClaw gateway ..."
podman compose -f podman-compose.yml up -d openclaw-gateway

# Read the token for display
TOKEN="$(grep '^OPENCLAW_GATEWAY_TOKEN=' .env | cut -d= -f2)"

echo ""
echo "=============================================="
echo " OpenClaw is running!"
echo "=============================================="
echo ""
echo " Gateway:   http://localhost:${OPENCLAW_GATEWAY_PORT:-18789}"
echo " Token:     ${TOKEN:0:8}…(see .env for full token)"
echo " Config:    ${CONFIG_DIR}"
echo " Workspace: ${WORKSPACE_DIR}"
echo ""
echo " Useful commands:"
echo "   podman compose -f podman-compose.yml logs -f openclaw-gateway"
echo "   podman compose -f podman-compose.yml down"
echo "   podman compose -f podman-compose.yml --profile cli run --rm openclaw-cli onboard --no-install-daemon"
echo ""
