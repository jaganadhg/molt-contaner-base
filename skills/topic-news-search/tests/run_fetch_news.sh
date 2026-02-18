#!/usr/bin/env bash
# Run the topic-news-search unit test without requiring pytest
set -euo pipefail
PY=python3
$PY skills/topic-news-search/tests/test_fetch_news.py
