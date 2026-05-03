"""
ATLAS Main Launcher (Day 1)
Runs all D1 services in parallel:
  - Market Data Engine (CCXT stream + indicators)
  - News Scraper (RSS + Reddit)
  - Regime Detector (5-mode classification)
"""

import asyncio
import os
import signal
import sys

from loguru import logger
from dotenv import load_dotenv

# Configure clean logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="DEBUG",
    colorize=True,
)
logger.add(
    "logs/atlas_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO",
)

load_dotenv()

# Import engines
from core.data.market_data_engine import MarketDataEngine
from core.data.news_scraper import NewsScraper
from core.data.regime_detector import RegimeDetector


async def main():
    logger.info("=" * 60)
    logger.info("  ATLAS v1.0 — Day 1 Data Foundation")
    logger.info("=" * 60)
    logger.info(f"  Asset : {os.getenv('TRADING_PAIR', 'ETH/USDT')}")
    logger.info(f"  Mode  : {'PAPER' if os.getenv('PAPER_TRADING','true')=='true' else 'LIVE'}")
    logger.info("=" * 60)

    market_engine  = MarketDataEngine()
    news_scraper   = NewsScraper()
    regime_detector = RegimeDetector()

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig):
        logger.warning(f"[Main] Received {sig.name}. Shutting down...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    tasks = [
        asyncio.create_task(market_engine.start(),  name="MarketData"),
        asyncio.create_task(news_scraper.start(),   name="NewsScraper"),
        asyncio.create_task(regime_detector.start(), name="RegimeDetector"),
    ]

    # Wait for shutdown signal
    await stop_event.wait()

    # Cancel all tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await market_engine.stop()
    await news_scraper.stop()
    await regime_detector.stop()
    logger.info("[Main] Clean shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
