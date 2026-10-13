import asyncio
import os

import aiohttp
import feedparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEED_PATH = os.path.join(BASE_DIR, "feed_list.txt")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RussiaHeatmapBot/1.0)"}
MAX_CONCURRENCY = 10


def load_feeds():
    with open(FEED_PATH, "r", encoding="utf-8") as f:
        feeds = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    return list(dict.fromkeys(feeds))  # dedupe, keep order


async def fetch_feed(session, sem, url):
    """Fetch one feed, return list of {title, description}."""
    try:
        async with sem:
            async with session.get(url) as response:
                if response.status != 200:
                    print(f"  Warning: {response.status} from {url}")
                    return []
                # bytes, not text: feedparser sniffs encoding itself (windows-1251 feeds)
                raw = await response.read()

        feed = feedparser.parse(raw)
        if feed.bozo and not feed.entries:
            print(f"  Warning: unparseable feed {url}")
            return []

        articles = [
            {"title": e.get("title", ""), "description": e.get("summary", "")}
            for e in feed.entries
        ]
        print(f"  -> Found {len(articles)} articles from {url}")
        return articles
    except Exception as e:
        # TimeoutError has empty str(); print type too
        print(f"  Error connecting to {url}: {type(e).__name__}: {e}")
        return []


async def get_all_news():
    feeds = load_feeds()
    print(f"Fetching {len(feeds)} news feeds...")
    timeout = aiohttp.ClientTimeout(total=10)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
        results = await asyncio.gather(*(fetch_feed(session, sem, u) for u in feeds))

    articles_list = [a for result in results for a in result]
    print(f"Fetched {len(articles_list)} articles.")
    return {"articles": articles_list}