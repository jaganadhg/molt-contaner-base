import json
import subprocess


def _run_js_or_py(query="Tesla"):
    # Prefer Node.js implementation; fall back to Python if node isn't available
    try:
        cmd = [
            "node",
            "skills/topic-news-search/scripts/fetch_news.js",
            query,
        ]
        return subprocess.check_output(cmd, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        cmd = [
            "python3",
            "skills/topic-news-search/scripts/fetch_news.py",
            query,
        ]
        return subprocess.check_output(cmd, text=True)


def test_fetch_news_returns_results():
    output = _run_js_or_py("Tesla")
    data = json.loads(output)

    assert "query" in data and data["query"] == "Tesla"
    assert "results" in data and isinstance(data["results"], list)
    assert len(data["results"]) > 0, "Expected at least one news result for 'Tesla'"


if __name__ == '__main__':
    # Allow running this test without pytest (avoids pytest being a blocker locally)
    try:
        output = _run_js_or_py("Tesla")
        data = json.loads(output)
        ok = (
            "query" in data and data["query"] == "Tesla" and
            "results" in data and isinstance(data["results"], list) and
            len(data["results"]) > 0
        )
        if ok:
            print('OK: fetch_news returned results')
            raise SystemExit(0)
        else:
            print('FAIL: fetch_news returned no results')
            raise SystemExit(2)
    except Exception as e:
        print('ERROR:', e)
        raise SystemExit(2)
