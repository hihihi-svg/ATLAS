"""
ATLAS Regime Detector
Classifies market into 5 regimes using EMA alignment, RSI, and volatility.
Routes to correct RL policy (A=Trend, B=Volatile, C=Range).
Caches current regime in Redis.
"""

import asyncio
import json
import os

import redis.asyncio as aioredis
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SYMBOL    = os.getenv("TRADING_PAIR", "ETH/USDT")

# Regime → Policy mapping
REGIME_POLICY_MAP = {
    "bull":     "A",   # Trending PPO
    "bear":     "A",   # Trending PPO (short mode)
    "chop":     "C",   # Ranging PPO
    "volatile": "B",   # Volatile PPO
    "crisis":   None,  # No trading
}


def classify_regime(ind_15m: dict, ind_1d: dict) -> tuple[str, float]:
    """
    Returns (regime_type, confidence_score).
    Uses 15m indicators + daily trend for classification.
    """
    rsi       = ind_15m.get("rsi", 50)
    macd_hist = ind_15m.get("macd_hist", 0)
    ema9      = ind_15m.get("ema9", 0)
    ema21     = ind_15m.get("ema21", 0)
    ema50     = ind_15m.get("ema50", 0)
    rvol      = ind_15m.get("rvol", 1.0)
    atr       = ind_15m.get("atr", 0)
    close     = ind_15m.get("close", 1)

    atr_pct   = (atr / close) * 100 if close > 0 else 0

    # CRISIS: extreme volatility (ATR > 5% of price)
    if atr_pct > 5.0:
        return "crisis", 0.9

    # VOLATILE: high ATR + high RVOL
    if atr_pct > 2.5 and rvol > 2.0:
        return "volatile", 0.75

    # BULL: EMA9 > EMA21 > EMA50, RSI 50-70, positive MACD hist
    ema_bull = ema9 > ema21 > ema50
    if ema_bull and 50 < rsi < 75 and macd_hist > 0:
        score = 0.6 + (min(rvol, 2) * 0.1) + (0.1 if rsi > 60 else 0)
        return "bull", min(score, 0.95)

    # BEAR: EMA9 < EMA21 < EMA50, RSI 25-50, negative MACD hist
    ema_bear = ema9 < ema21 < ema50
    if ema_bear and 25 < rsi < 50 and macd_hist < 0:
        score = 0.6 + (0.1 if rsi < 40 else 0)
        return "bear", min(score, 0.90)

    # CHOP: EMAs tangled, RSI near 50, low RVOL
    ema21_safe = ema21 if ema21 != 0 else 1e-9
    if abs(ema9 - ema21) / ema21_safe < 0.005 and 40 < rsi < 60 and rvol < 1.2:
        return "chop", 0.65

    # Default: chop
    return "chop", 0.50


class RegimeDetector:
    def __init__(self):
        self.redis: aioredis.Redis = None
        self._running = False

    async def start(self):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        self._running = True
        logger.info("[RegimeDetector] Starting...")
        await self._detection_loop()

    async def stop(self):
        self._running = False
        await self.redis.aclose()

    async def _detection_loop(self):
        while self._running:
            try:
                await self._classify_and_cache()
            except Exception as e:
                logger.error(f"[Regime] Error: {e}")
            await asyncio.sleep(30)  # Re-classify every 30 seconds

    async def _classify_and_cache(self):
        # Pull indicator snapshots from Redis
        ind_15m_raw = await self.redis.get(f"indicators:{SYMBOL}:15m")
        ind_1d_raw  = await self.redis.get(f"indicators:{SYMBOL}:1d")

        if not ind_15m_raw:
            logger.warning("[Regime] No 15m indicators cached yet. Skipping.")
            return

        ind_15m = json.loads(ind_15m_raw)
        ind_1d  = json.loads(ind_1d_raw) if ind_1d_raw else {}

        regime, score = classify_regime(ind_15m, ind_1d)
        policy = REGIME_POLICY_MAP.get(regime, "C")

        regime_data = {
            "regime":       regime,
            "policy":       policy,
            "score":        score,
            "rsi":          ind_15m.get("rsi"),
            "macd_hist":    ind_15m.get("macd_hist"),
            "rvol":         ind_15m.get("rvol"),
            "atr":          ind_15m.get("atr"),
            "close":        ind_15m.get("close"),
        }

        await self.redis.setex("current:regime", 60 * 10, json.dumps(regime_data))
        logger.info(f"[Regime] {regime.upper()} (score={score:.2f}) → Policy {policy} | RSI={ind_15m.get('rsi', 0):.1f} RVOL={ind_15m.get('rvol', 0):.2f}")

    async def get_current(self) -> dict:
        data = await self.redis.get("current:regime")
        if data:
            return json.loads(data)
        return {"regime": "chop", "policy": "C", "score": 0.5}


async def main():
    detector = RegimeDetector()
    try:
        await detector.start()
    except KeyboardInterrupt:
        await detector.stop()


if __name__ == "__main__":
    asyncio.run(main())
