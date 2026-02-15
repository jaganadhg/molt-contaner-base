#!/usr/bin/env python3
"""
fetch_news.py — Fetch latest news for a topic/company using Google News RSS.

Usage:
    python3 fetch_news.py "Apple"
    python3 fetch_news.py "Tesla merger"
    python3 fetch_news.py --max 10 "Microsoft"

Returns JSON array of news items with title, source, date, link, and snippet.
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from html import unescape
import re
from datetime import datetime


def strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    clean = re.sub(r"<[^>]+>", "", text)
    return unescape(clean).strip()


def fetch_google_news_rss(query: str, max_results: int = 8) -> list[dict]:
    """Fetch news from Google News RSS feed."""
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en&gl=US&ceid=US:en"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            xml_data = response.read().decode("utf-8")
    except Exception as e:
        print(json.dumps({"error": f"Failed to fetch news: {e}"}), file=sys.stderr)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(json.dumps({"error": f"Failed to parse RSS: {e}"}), file=sys.stderr)
        return []

    items = []
    for item in root.findall(".//item")[:max_results]:
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        source = item.findtext("source", "").strip()
        description = strip_html(item.findtext("description", ""))

        # Parse date to ISO format
        iso_date = pub_date
        try:
            dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
            iso_date = dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, TypeError):
            pass

        items.append(
            {
                "title": title,
                "source": source,
                "date": iso_date,
                "link": link,
                "snippet": description[:500] if description else "",
            }
        )

    return items


def main():
    parser = argparse.ArgumentParser(
        description="Fetch latest news for a topic or company."
    )
    parser.add_argument("query", help="Topic or company name to search for")
    parser.add_argument(
        "--max",
        type=int,
        default=8,
        help="Maximum number of results (default: 8)",
    )
    args = parser.parse_args()

    results = fetch_google_news_rss(args.query, args.max)

    if not results:
        print(json.dumps({"query": args.query, "results": [], "count": 0}))
    else:
        print(
            json.dumps(
                {"query": args.query, "results": results, "count": len(results)},
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
