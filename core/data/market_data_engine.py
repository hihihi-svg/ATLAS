"""
ATLAS Market Data Engine
Streams live OHLCV from CCXT, computes indicators via pandas-ta,
stores to PostgreSQL, caches hot data in Redis.
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import ccxt.async_support as ccxt
import pandas as pd
import ta
import redis.asyncio as aioredis
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SYMBOL       = os.getenv("TRADING_PAIR", "ETH/USDT")
EXCHANGE_ID  = os.getenv("EXCHANGE_ID", "binance")
REDIS_URL    = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TIMEFRAMES   = ["1m", "15m", "1d"]
CANDLE_LIMIT = 200   # candles to fetch per timeframe


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators in-place on an OHLCV DataFrame."""
    # RSI
    df["rsi"]         = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    # MACD
    macd_ind          = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"]        = macd_ind.macd()
    df["macd_signal"] = macd_ind.macd_signal()
    df["macd_hist"]   = macd_ind.macd_diff()
    # EMAs
    df["ema9"]        = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
    df["ema21"]       = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
    df["ema50"]       = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    # ATR
    df["atr"]         = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
    # VWAP
    df["vwap"]        = ta.volume.VolumeWeightedAveragePrice(df["high"], df["low"], df["close"], df["volume"]).volume_weighted_average_price()
    # Bollinger Bands
    bb                = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"]    = bb.bollinger_hband()
    df["bb_lower"]    = bb.bollinger_lband()
    # Relative Volume (vs 20-candle average)
    vol_avg           = df["volume"].rolling(20).mean()
    df["rvol"]        = df["volume"] / vol_avg
    return df


class MarketDataEngine:
    def __init__(self):
        self.exchange = getattr(ccxt, EXCHANGE_ID)({
            "apiKey":    os.getenv("EXCHANGE_API_KEY", ""),
            "secret":    os.getenv("EXCHANGE_API_SECRET", ""),
            "enableRateLimit": True,
        })
        self.redis: aioredis.Redis = None
        self._running = False

    async def start(self):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        self._running = True
        logger.info(f"[MarketData] Starting stream: {SYMBOL} on {EXCHANGE_ID}")
        await self.exchange.load_markets()
        await asyncio.gather(
            self._candle_loop("1m",  60),
            self._candle_loop("15m", 60 * 15),
            self._candle_loop("1d",  60 * 60 * 4),
        )

    async def stop(self):
        self._running = False
        await self.exchange.close()
        await self.redis.aclose()
        logger.info("[MarketData] Stopped.")

    async def _candle_loop(self, tf: str, interval_secs: int):
        """Fetch + compute indicators on each timeframe at its natural cadence."""
        while self._running:
            try:
                df = await self._fetch_ohlcv(tf)
                df = compute_indicators(df)
                latest = df.iloc[-1]

                # Cache latest indicator row in Redis (TTL = 2× interval)
                key = f"indicators:{SYMBOL}:{tf}"
                payload = {
                    "rsi":         float(latest.get("rsi", 0) or 0),
                    "macd":        float(latest.get("macd", 0) or 0),
                    "macd_signal": float(latest.get("macd_signal", 0) or 0),
                    "macd_hist":   float(latest.get("macd_hist", 0) or 0),
                    "ema9":        float(latest.get("ema9", 0) or 0),
                    "ema21":       float(latest.get("ema21", 0) or 0),
                    "ema50":       float(latest.get("ema50", 0) or 0),
                    "atr":         float(latest.get("atr", 0) or 0),
                    "vwap":        float(latest.get("vwap", 0) or 0),
                    "bb_upper":    float(latest.get("bb_upper", 0) or 0),
                    "bb_lower":    float(latest.get("bb_lower", 0) or 0),
                    "rvol":        float(latest.get("rvol", 1) or 1),
                    "close":       float(latest["close"]),
                    "volume":      float(latest["volume"]),
                    "ts":          str(latest["timestamp"]),
                }
                await self.redis.setex(key, interval_secs * 2, json.dumps(payload))

                # Also cache latest regime-relevant price data
                price_key = f"price:{SYMBOL}"
                await self.redis.setex(price_key, 120, json.dumps({
                    "close": float(latest["close"]),
                    "high":  float(latest["high"]),
                    "low":   float(latest["low"]),
                    "ts":    str(latest["timestamp"]),
                }))

                logger.debug(f"[{tf}] RSI={payload['rsi']:.1f} | MACD={payload['macd']:.4f} | RVOL={payload['rvol']:.2f} | Close={payload['close']:.2f}")

            except Exception as e:
                logger.error(f"[MarketData:{tf}] Error: {e}")

            await asyncio.sleep(interval_secs)

    async def _fetch_ohlcv(self, tf: str) -> pd.DataFrame:
        raw = await self.exchange.fetch_ohlcv(SYMBOL, tf, limit=CANDLE_LIMIT)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    async def get_latest(self, tf: str = "15m") -> dict:
        """Read cached latest indicators from Redis."""
        key = f"indicators:{SYMBOL}:{tf}"
        data = await self.redis.get(key)
        return json.loads(data) if data else {}


async def main():
    engine = MarketDataEngine()
    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
