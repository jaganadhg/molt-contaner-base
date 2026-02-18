#!/usr/bin/env node
/*
fetch_news.js — Fetch latest news for a topic/company using Google News RSS.

Usage:
  node fetch_news.js "Apple"
  node fetch_news.js --max 10 "Microsoft"

Outputs JSON with { query, results: [ { title, source, date, link, snippet } ], count }

This implementation is dependency-free so it runs inside the OpenClaw runtime image
without adding npm packages.
*/

const https = require('https');

function usageAndExit() {
  console.error('Usage: node skills/topic-news-search/scripts/fetch_news.js [--max N] "QUERY"');
  process.exit(2);
}

function parseArgs(argv) {
  const args = { max: 8, query: null };
  const rest = [];
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--max') {
      i++;
      if (!argv[i] || Number.isNaN(Number(argv[i]))) usageAndExit();
      args.max = Math.max(1, Number(argv[i]));
      continue;
    }
    rest.push(a);
  }
  if (rest.length === 0) usageAndExit();
  args.query = rest.join(' ');
  return args;
}

function decodeHtmlEntities(str) {
  if (!str) return '';
  return str
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    // numeric entities
    .replace(/&#(x?[0-9a-fA-F]+);/g, (_, n) => {
      const code = n.startsWith('x') ? parseInt(n.slice(1), 16) : parseInt(n, 10);
      if (!isFinite(code)) return '';
      return String.fromCharCode(code);
    });
}

function stripHtmlTags(s) {
  return decodeHtmlEntities((s || '').replace(/<[^>]+>/g, '')).trim();
}

function extractTag(xml, tag) {
  const re = new RegExp(`<${tag}[^>]*>([\s\S]*?)<\\/${tag}>`, 'i');
  const m = xml.match(re);
  return m ? m[1].trim() : '';
}

function fetchGoogleNewsRSS(query, maxResults) {
  return new Promise((resolve) => {
    const encoded = encodeURIComponent(query);
    const startUrl = `https://news.google.com/rss/search?q=${encoded}&hl=en&gl=US&ceid=US:en`;
    const maxRedirects = 5;

    function get(url, redirectsLeft) {
      const opts = new URL(url);
      opts.headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      };
      const req = https.request(opts, (res) => {
        // follow redirects
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location && redirectsLeft > 0) {
          const loc = res.headers.location.startsWith('http') ? res.headers.location : new URL(res.headers.location, url).href;
          res.resume();
          return get(loc, redirectsLeft - 1);
        }

        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => (body += chunk));
        res.on('end', () => {
          try {
            const items = [];
            const itemRe = /<item[^>]*>([\s\S]*?)<\/item>/gi;
            let match;
            while ((match = itemRe.exec(body)) && items.length < maxResults) {
              const itemXml = match[1];
              const title = stripHtmlTags((itemXml.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [,''])[1] || '') || '';
              const link = ((itemXml.match(/<link[^>]*>([\s\S]*?)<\/link>/i) || [,''])[1] || '').trim();
              const pubDateRaw = (itemXml.match(/<pubDate[^>]*>([\s\S]*?)<\/pubDate>/i) || [,''])[1] || '';
              const source = stripHtmlTags((itemXml.match(/<source[^>]*>([\s\S]*?)<\/source>/i) || [,''])[1] || '') || '';
              const description = stripHtmlTags((itemXml.match(/<description[^>]*>([\s\S]*?)<\/description>/i) || [,''])[1] || '') || '';



              let isoDate = pubDateRaw;
              try {
                const dt = new Date(pubDateRaw);
                if (!isNaN(dt.getTime())) {
                  const y = dt.getUTCFullYear();
                  const m = String(dt.getUTCMonth() + 1).padStart(2, '0');
                  const d = String(dt.getUTCDate()).padStart(2, '0');
                  const hh = String(dt.getUTCHours()).padStart(2, '0');
                  const mm = String(dt.getUTCMinutes()).padStart(2, '0');
                  isoDate = `${y}-${m}-${d} ${hh}:${mm} UTC`;
                }
              } catch (err) {
                /* leave raw */
              }

              items.push({
                title,
                source,
                date: isoDate,
                link,
                snippet: description.slice(0, 500),
              });
            }
            resolve(items);
          } catch (err) {
            console.error(JSON.stringify({ error: `Failed to parse RSS: ${err.message}` }));
            resolve([]);
          }
        });
      });
      req.on('error', (err) => {
        console.error(JSON.stringify({ error: `Failed to fetch news: ${err.message}` }));
        resolve([]);
      });
      req.setTimeout(15000, () => {
        req.abort();
      });
      req.end();
    }

    get(startUrl, maxRedirects);
  });
}

async function main() {
  const args = parseArgs(process.argv);
  const results = await fetchGoogleNewsRSS(args.query, args.max);
  if (!results || results.length === 0) {
    console.log(JSON.stringify({ query: args.query, results: [], count: 0 }));
  } else {
    console.log(JSON.stringify({ query: args.query, results, count: results.length }, null, 2));
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  });
}
