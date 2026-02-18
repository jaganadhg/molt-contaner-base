---
name: topic-news-search
description: "Search latest news for a topic or company. Returns summarized articles with event categorization (Executive Move, Financial Update, Merger & Acquisition, Product Launch, etc.)."
metadata:
  {
    "openclaw":
      {
        "emoji": "📰",
        "requires": { "bins": ["node", "python3"] },
        "commands": ["/company-news"]
      },
  }
---

# Topic News Search

Search the latest news for a given **topic** or **company name**, then summarize and categorize each result.

## How to use

Run the bundled Python script to fetch news, then analyze and present the results.

### Step 1: Fetch news

```bash
# Node.js implementation (preferred)
node skills/topic-news-search/scripts/fetch_news.js "QUERY"
# Python fallback (still supported)
python3 skills/topic-news-search/scripts/fetch_news.py "QUERY"
```

You can also invoke this skill with the slash shortcut in the simulator: `/company-news <QUERY>`, or run the CLI wrapper directly:

```bash
python3 skills/topic-news-search/scripts/company-news "Microsoft"
```

Replace `QUERY` with the topic or company name (e.g., `"Tesla"`, `"Apple product launch"`, `"Goldman Sachs"`).

Use `--max N` to control the number of results (default: 8):

```bash
node skills/topic-news-search/scripts/fetch_news.js --max 5 "Microsoft"
# python fallback:
# python3 skills/topic-news-search/scripts/fetch_news.py --max 5 "Microsoft"
```

The script returns JSON with an array of news items containing `title`, `source`, `date`, `link`, and `snippet`.

### Step 2: Analyze and present results

For **each news item** returned, you MUST provide:

1. **Headline**: The article title and source
2. **Three-line summary**: A concise 3-sentence summary of the article based on the title and snippet
3. **Category**: Classify the news into exactly ONE of these categories:
   - 🏢 **Executive Move** — C-suite appointments, departures, board changes
   - 💰 **Financial Update** — Earnings, revenue, stock price, funding rounds, IPO
   - 🤝 **Merger & Acquisition** — Mergers, acquisitions, divestitures, buyouts
   - 🚀 **Product Launch** — New products, features, services, platform updates
   - ⚖️ **Regulatory / Legal** — Lawsuits, regulations, compliance, government action
   - 📊 **Market / Industry** — Industry trends, market analysis, competitive moves
   - 🔬 **Research / Innovation** — Patents, R&D, scientific breakthroughs
   - 📋 **Other** — Anything that doesn't fit the above categories

### Output format

Present results in this format:

```
## 📰 News for: [QUERY] (N results)

### 1. [Article Title]
**Source:** [Source Name] | **Date:** [Date]
**Category:** [emoji] [Category Name]

**Summary:**
- [First sentence summarizing the key news]
- [Second sentence with important details or context]
- [Third sentence with implications or outlook]

🔗 [Read more](link)

---
```

### Example

```
## 📰 News for: Tesla (3 results)

### 1. Tesla Reports Record Q4 Deliveries
**Source:** Reuters | **Date:** 2026-01-03 14:30 UTC
**Category:** 💰 Financial Update

**Summary:**
- Tesla delivered a record 510,000 vehicles in Q4 2025, exceeding analyst expectations.
- The strong deliveries were driven by Model Y demand in China and Europe.
- The results signal continued growth momentum heading into 2026.

🔗 [Read more](https://example.com/article1)

---
```

## Important notes

- Always run the fetch script first before summarizing. Do not fabricate news.
- If the script returns no results, tell the user no recent news was found for that query.
- Base your summary ONLY on the title and snippet from the fetched data.
- When the snippet is sparse, derive the summary from the title and source context.
- If you cannot confidently assign a category, use 📋 **Other**.
