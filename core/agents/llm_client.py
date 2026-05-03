"""
ATLAS LLM Client
Wraps OpenAI API with:
- Structured JSON output enforcement
- Mock/offline fallback for testing without API key
- Retry logic with backoff
- Token usage tracking
"""

import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL      = os.getenv("LLM_MODEL", "gpt-4o-mini")
MOCK_MODE      = not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_key_here"

if not MOCK_MODE:
    from openai import AsyncOpenAI
    _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
else:
    logger.warning("[LLM] No API key found. Running in MOCK mode. Set OPENAI_API_KEY in .env for real inference.")
    _client = None


async def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 800) -> dict:
    """
    Call LLM and return parsed JSON dict.
    Falls back to mock response if no API key.
    """
    if MOCK_MODE:
        return _mock_response(system_prompt, user_prompt)

    # Only request JSON mode when prompt explicitly asks for JSON output
    use_json_mode = "json" in system_prompt.lower() or "json" in user_prompt.lower()

    for attempt in range(3):
        try:
            kwargs = dict(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await _client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content

            # Try JSON parse; if not JSON mode return raw string in dict
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                if use_json_mode:
                    logger.error(f"[LLM] JSON parse error on: {raw[:100]}")
                    return {"error": "json_parse_failed"}
                return {"result": raw}

        except Exception as e:
            logger.warning(f"[LLM] Attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return {"error": "llm_call_failed"}


def _mock_response(system_prompt: str, user_prompt: str) -> dict:
    """
    Returns plausible mock data for offline testing.
    Agent type detected from system prompt keywords.
    """
    sp = system_prompt.lower()

    if "analyst" in sp or "sentiment" in sp:
        return {
            "sentiment_score": 0.35,
            "summary": "[MOCK] Mixed bullish news on ETH. Some profit-taking pressure.",
            "bullish_flag": True,
            "score": 6.5,
            "vote": "NEUTRAL",
            "reasoning": "Mock: moderate positive sentiment with low confidence."
        }
    elif "technician" in sp or "technical" in sp:
        return {
            "setup_score": 6.8,
            "entry_zone": "current price ±0.3%",
            "key_levels": {"support": "EMA21", "resistance": "BB upper"},
            "vote": "BUY",
            "reasoning": "Mock: EMA9 > EMA21 but RSI neutral. MACD weak bearish. Borderline setup.",
            "flags": ["low_rvol", "chop_regime"]
        }
    elif "risk" in sp or "contrarian" in sp or "skeptic" in sp:
        return {
            "concerns": [
                {"issue": "MACD histogram negative - momentum declining", "severity": "low"},
                {"issue": "Low RVOL - no volume confirmation", "severity": "medium"},
            ],
            "overall_risk_score": 3.5,
            "vote": "CAUTION",
            "reasoning": "Mock: 2 concerns identified. Risk moderate."
        }
    else:
        return {"result": "mock_response", "score": 5.0}
