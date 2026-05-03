"""
ATLAS Analyst Agent
Reads news headlines + sentiment from Redis queue.
Scores sentiment -1.0 to +1.0 per asset.
Output: vote (BUY/SELL/NEUTRAL), score 0-10, reasoning.
"""

import json
import os
from dataclasses import dataclass

import redis.asyncio as aioredis
from dotenv import load_dotenv
from loguru import logger

from core.agents.llm_client import call_llm

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SYMBOL    = os.getenv("TRADING_PAIR", "ETH/USDT")
ASSET     = SYMBOL.split("/")[0]

ANALYST_SYSTEM_PROMPT = """You are a financial news analyst specializing in cryptocurrency markets.
Your ONLY job: analyze news headlines and score market sentiment.

Rules:
- Score sentiment from -1.0 (extremely bearish) to +1.0 (extremely bullish)
- Convert to a 0-10 analyst score where 0=very bearish, 5=neutral, 10=very bullish
- Be conservative. Only score above 8 for major positive catalysts.
- Recent news (last 2 hours) weighs 3x more than older news.

Output ONLY valid JSON:
{
  "sentiment_score": <float -1.0 to 1.0>,
  "score": <float 0 to 10>,
  "vote": "<BUY|SELL|NEUTRAL>",
  "bullish_flag": <true|false>,
  "summary": "<2 sentence summary>",
  "key_catalyst": "<most impactful news item or null>",
  "reasoning": "<brief explanation>"
}"""


@dataclass
class AnalystOutput:
    sentiment_score: float   # -1.0 to +1.0
    score: float             # 0 to 10
    vote: str                # BUY | SELL | NEUTRAL
    bullish_flag: bool
    summary: str
    key_catalyst: str | None
    reasoning: str
    raw: dict


class AnalystAgent:
    def __init__(self):
        self.redis: aioredis.Redis = None

    async def connect(self):
        self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    async def disconnect(self):
        if self.redis:
            await self.redis.aclose()

    async def analyze(self, symbol: str = None, indicators: dict = None) -> AnalystOutput:
        """
        Pull recent news from Redis queue, pass to LLM, return structured output.
        """
        symbol = symbol or ASSET
        headlines = await self._get_recent_headlines(symbol, limit=15)

        if not headlines:
            logger.warning(f"[Analyst] No news found for {symbol}. Using momentum-based sentiment fallback.")
            # Fallback: Use RSI and MACD to guess sentiment from price action
            rsi = indicators.get("rsi", 50)
            mhist = indicators.get("macd_hist", 0)
            
            # Base score 5.0 (Neutral)
            score = 5.0
            # RSI 50-70: bullish momentum (up to +1.5)
            # RSI 30-50: bearish momentum (up to -1.5)
            score += (rsi - 50) / 20 * 1.5
            # MACD histogram confirmation (up to +1.0)
            score += max(-1.0, min(1.0, mhist * 1000))
            
            score = max(1.0, min(9.0, score))
            sentiment = (score - 5.0) / 4.0
            
            return AnalystOutput(
                sentiment_score=round(sentiment, 3), 
                score=round(score, 2), 
                vote="BUY" if score > 6.0 else "SELL" if score < 4.0 else "NEUTRAL",
                bullish_flag=score > 6.0, 
                summary="No recent news found. Sentiment inferred from price momentum.",
                key_catalyst=None, 
                reasoning=f"RSI={rsi:.1f}, MACD_Hist={mhist:.4f}. Falling back to technical momentum for analyst view.", 
                raw={"fallback": True}
            )

        user_prompt = f"""Analyze sentiment for {symbol} cryptocurrency based on these recent news items:

{self._format_headlines(headlines)}

Today's market context: {symbol} is currently trading with moderate volume.
Provide your sentiment analysis as JSON."""

        logger.debug(f"[Analyst] Analyzing {len(headlines)} headlines for {symbol}...")
        result = await call_llm(ANALYST_SYSTEM_PROMPT, user_prompt, max_tokens=400)

        return AnalystOutput(
            sentiment_score = float(result.get("sentiment_score", 0.0)),
            score           = float(result.get("score", 5.0)),
            vote            = result.get("vote", "NEUTRAL"),
            bullish_flag    = bool(result.get("bullish_flag", False)),
            summary         = result.get("summary", ""),
            key_catalyst    = result.get("key_catalyst"),
            reasoning       = result.get("reasoning", ""),
            raw             = result
        )

    async def _get_recent_headlines(self, symbol: str, limit: int = 15) -> list[dict]:
        """Pull recent news from Redis queue. Also check symbol-specific cache."""
        if not self.redis:
            return []
        try:
            raw_items = await self.redis.lrange("news:queue", 0, limit - 1)
            headlines = []
            for item in raw_items:
                try:
                    data = json.loads(item)
                    # Include general market news + symbol-specific
                    if data.get("symbol") == symbol or data.get("symbol") is None:
                        headlines.append(data)
                except Exception:
                    continue
            return headlines[:limit]
        except Exception as e:
            logger.warning(f"[Analyst] Redis read failed: {e}. Using empty list.")
            return []

    def _format_headlines(self, headlines: list[dict]) -> str:
        lines = []
        for i, h in enumerate(headlines, 1):
            src  = h.get("source", "unknown")
            head = h.get("headline", "")[:150]
            ts   = h.get("scraped_at", "")[:19]
            lines.append(f"{i}. [{src}] {head} ({ts})")
        return "\n".join(lines)
