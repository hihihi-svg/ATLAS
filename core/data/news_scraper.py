"""
ATLAS News Scraper
Pulls news from Yahoo Finance RSS + Reddit (PRAW).
Stores raw articles in PostgreSQL. Caches sentiment-relevant
symbols in Redis for fast agent access.
"""

import asyncio
import hashlib
import os
from datetime import datetime, timezone

import feedparser
import httpx
import praw
import redis.asyncio as aioredis
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SYMBOL        = os.getenv("TRADING_PAIR", "ETH/USDT")
ASSET         = SYMBOL.split("/")[0]  # 'ETH'
SCRAPE_INTERVAL = 60 * 15  # every 15 minutes

# RSS feeds to scrape (free, no auth)
RSS_FEEDS = [
    f"https://finance.yahoo.com/rss/headline?s={ASSET}-USD",
    "https://finance.yahoo.com/rss/topstories",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
]

REDDIT_SUBS = ["CryptoCurrency", "ethtrader", "wallstreetbets", "stocks"]


class NewsScraper:
    def __init__(self):
        self.redis: aioredis.Redis = None
        self._seen_urls: set = set()   # in-memory dedup (URL hash)
        self._running = False

        # Reddit client
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID", ""),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
            user_agent=os.getenv("REDDIT_USER_AGENT", "atlas-bot/1.0"),
        )

    async def start(self):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        self._running = True
        logger.info("[NewsScraper] Starting...")
        await asyncio.gather(
            self._rss_loop(),
            self._reddit_loop(),
        )

    async def stop(self):
        self._running = False
        await self.redis.aclose()
        logger.info("[NewsScraper] Stopped.")

    # ── RSS ──────────────────────────────────────────────────────────────────

    async def _rss_loop(self):
        while self._running:
            try:
                articles = await self._fetch_rss()
                new_count = 0
                for article in articles:
                    stored = await self._store_article(article)
                    if stored:
                        new_count += 1
                logger.info(f"[RSS] Fetched {len(articles)} articles, {new_count} new.")
            except Exception as e:
                logger.error(f"[RSS] Error: {e}")
            await asyncio.sleep(SCRAPE_INTERVAL)

    async def _fetch_rss(self) -> list[dict]:
        articles = []
        async with httpx.AsyncClient(timeout=15) as client:
            for url in RSS_FEEDS:
                try:
                    resp = await client.get(url)
                    feed = feedparser.parse(resp.text)
                    for entry in feed.entries[:10]:  # top 10 per feed
                        articles.append({
                            "source":    "rss",
                            "url":       entry.get("link", ""),
                            "headline":  entry.get("title", ""),
                            "body_text": entry.get("summary", ""),
                            "symbol":    ASSET if ASSET.lower() in entry.get("title", "").lower() else None,
                        })
                except Exception as e:
                    logger.warning(f"[RSS] Failed {url}: {e}")
        return articles

    # ── Reddit ───────────────────────────────────────────────────────────────

    async def _reddit_loop(self):
        while self._running:
            try:
                posts = await asyncio.to_thread(self._fetch_reddit_sync)
                new_count = 0
                for post in posts:
                    stored = await self._store_article(post)
                    if stored:
                        new_count += 1
                logger.info(f"[Reddit] Fetched {len(posts)} posts, {new_count} new.")
            except Exception as e:
                logger.error(f"[Reddit] Error: {e}")
            await asyncio.sleep(SCRAPE_INTERVAL)

    def _fetch_reddit_sync(self) -> list[dict]:
        posts = []
        for sub in REDDIT_SUBS:
            try:
                subreddit = self.reddit.subreddit(sub)
                for post in subreddit.hot(limit=15):
                    # Only take posts with enough upvotes (noise filter)
                    if post.score < 10:
                        continue
                    posts.append({
                        "source":    f"reddit/{sub}",
                        "url":       f"https://reddit.com{post.permalink}",
                        "headline":  post.title,
                        "body_text": post.selftext[:500] if post.selftext else "",
                        "symbol":    ASSET if ASSET.lower() in post.title.lower() else None,
                    })
            except Exception as e:
                logger.warning(f"[Reddit] Failed r/{sub}: {e}")
        return posts

    # ── Storage ───────────────────────────────────────────────────────────────

    async def _store_article(self, article: dict) -> bool:
        """Dedup by URL hash. Store in Redis queue for LLM processing."""
        url = article.get("url", "")
        url_hash = hashlib.md5(url.encode()).hexdigest()

        if url_hash in self._seen_urls:
            return False
        self._seen_urls.add(url_hash)

        # Push to Redis list for LLM sentiment processor to consume
        import json
        payload = {
            **article,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "url_hash":   url_hash,
            "processed":  False,
        }
        await self.redis.lpush("news:queue", json.dumps(payload))
        await self.redis.ltrim("news:queue", 0, 999)  # cap queue at 1000

        logger.debug(f"[News] New: [{article['source']}] {article['headline'][:80]}...")
        return True

    async def get_unprocessed_count(self) -> int:
        return await self.redis.llen("news:queue")


async def main():
    scraper = NewsScraper()
    try:
        await scraper.start()
    except KeyboardInterrupt:
        await scraper.stop()


if __name__ == "__main__":
    asyncio.run(main())
