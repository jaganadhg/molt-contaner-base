#!/usr/bin/env bash
set -euo pipefail

IMAGE=openclaw-qmd:local-verify

echo "Building image using Dockerfile.qmd..."
docker build -f Dockerfile.qmd -t "$IMAGE" .

echo "Checking for fetch_news.js inside image..."
docker run --rm "$IMAGE" test -f /home/node/.openclaw/workspace/skills/topic-news-search/scripts/fetch_news.js && echo "OK: fetch_news.js present in image" || (echo "MISSING: fetch_news.js not found" && exit 1)
