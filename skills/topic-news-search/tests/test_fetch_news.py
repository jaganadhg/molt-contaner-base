import json
import subprocess


def test_fetch_news_returns_results():
    # Run the fetch_news.py script for a query that should return results on public news
    cmd = [
        "python3",
        "skills/topic-news-search/scripts/fetch_news.py",
        "Tesla",
    ]
    output = subprocess.check_output(cmd, text=True)
    data = json.loads(output)

    assert "query" in data and data["query"] == "Tesla"
    assert "results" in data and isinstance(data["results"], list)
    assert len(data["results"]) > 0, "Expected at least one news result for 'Tesla'"
