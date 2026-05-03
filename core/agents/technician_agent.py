"""
ATLAS Technician Agent
Reads live indicator values from Redis cache.
Scores chart setup 0-10. Identifies entry zones and key levels.
Output: setup_score, entry_zone, key_levels, vote, reasoning.
"""

from dataclasses import dataclass, field
from loguru import logger
from core.agents.llm_client import call_llm

TECHNICIAN_SYSTEM_PROMPT = """You are a professional technical analyst with 15 years of experience in cryptocurrency markets.
Your ONLY job: evaluate price action and technical indicators. Do NOT consider news or fundamentals.

Scoring rules:
- Score the technical setup from 0 (terrible) to 10 (perfect textbook setup)
- Only score ABOVE 8 for setups with: clear trend, volume confirmation, multiple timeframe alignment
- Score 6-7 for borderline setups
- Score below 5 for no clear setup or opposing signals

LONG signals: EMA9>EMA21>EMA50, RSI 50-70, MACD_hist>0, RVOL>1.3
SHORT signals: EMA9<EMA21<EMA50, RSI 30-50, MACD_hist<0, RVOL>1.3
NEUTRAL: EMAs tangled, RSI near 50, MACD near zero

Output ONLY valid JSON:
{
  "setup_score": <float 0-10>,
  "vote": "<BUY|SELL|NEUTRAL>",
  "direction_bias": "<LONG|SHORT|NONE>",
  "entry_zone": "<description of ideal entry>",
  "key_levels": {
    "support": "<level description>",
    "resistance": "<level description>",
    "vwap_position": "<above|below|at>"
  },
  "timeframe_alignment": "<strong|moderate|weak|none>",
  "flags": ["<any warning flags>"],
  "reasoning": "<concise explanation>"
}"""


@dataclass
class TechnicianOutput:
    setup_score: float         # 0 to 10
    vote: str                  # BUY | SELL | NEUTRAL
    direction_bias: str        # LONG | SHORT | NONE
    entry_zone: str
    key_levels: dict
    timeframe_alignment: str
    flags: list[str]
    reasoning: str
    raw: dict


class TechnicianAgent:

    async def analyze(self, indicators: dict, regime: str = "chop") -> TechnicianOutput:
        """
        Score the technical setup given current indicator values.
        indicators: dict from Redis (rsi, macd, ema9, ema21, ema50, atr, vwap, rvol, close)
        """
        user_prompt = self._build_prompt(indicators, regime)
        logger.debug(f"[Technician] Analyzing setup | RSI={indicators.get('rsi',0):.1f} RVOL={indicators.get('rvol',0):.2f}")

        result = await call_llm(TECHNICIAN_SYSTEM_PROMPT, user_prompt, max_tokens=500)

        return TechnicianOutput(
            setup_score         = float(result.get("setup_score", 5.0)),
            vote                = result.get("vote", "NEUTRAL"),
            direction_bias      = result.get("direction_bias", "NONE"),
            entry_zone          = result.get("entry_zone", "No clear zone"),
            key_levels          = result.get("key_levels", {}),
            timeframe_alignment = result.get("timeframe_alignment", "weak"),
            flags               = result.get("flags", []),
            reasoning           = result.get("reasoning", ""),
            raw                 = result
        )

    def _build_prompt(self, ind: dict, regime: str) -> str:
        close  = ind.get("close", 0)
        ema9   = ind.get("ema9", 0)
        ema21  = ind.get("ema21", 0)
        ema50  = ind.get("ema50", 0)
        rsi    = ind.get("rsi", 50)
        macd   = ind.get("macd", 0)
        mhist  = ind.get("macd_hist", 0)
        msig   = ind.get("macd_signal", 0)
        atr    = ind.get("atr", 0)
        vwap   = ind.get("vwap", 0)
        rvol   = ind.get("rvol", 1.0)
        bb_u   = ind.get("bb_upper", 0)
        bb_l   = ind.get("bb_lower", 0)

        # Pre-compute EMA alignment
        if ema9 and ema21 and ema50:
            if ema9 > ema21 > ema50:
                ema_align = "BULLISH (EMA9 > EMA21 > EMA50)"
            elif ema9 < ema21 < ema50:
                ema_align = "BEARISH (EMA9 < EMA21 < EMA50)"
            else:
                ema_align = f"TANGLED (EMA9={ema9:.0f}, EMA21={ema21:.0f}, EMA50={ema50:.0f})"
        else:
            ema_align = "UNKNOWN"

        vwap_pos = "above VWAP" if close > vwap else "below VWAP" if vwap else "VWAP unavailable"
        atr_pct  = (atr / close * 100) if close else 0

        return f"""Evaluate this ETH/USD 15-minute chart setup:

PRICE ACTION:
  Current Price: ${close:,.2f}
  VWAP: ${vwap:,.2f} (price is {vwap_pos})
  Bollinger Upper: ${bb_u:,.2f} | Lower: ${bb_l:,.2f}

TREND INDICATORS:
  EMA Alignment: {ema_align}
  EMA9: ${ema9:,.2f} | EMA21: ${ema21:,.2f} | EMA50: ${ema50:,.2f}

MOMENTUM:
  RSI(14): {rsi:.1f}
  MACD: {macd:.4f} | Signal: {msig:.4f} | Histogram: {mhist:.4f}
  MACD bias: {"BULLISH" if mhist > 0 else "BEARISH"}

VOLATILITY & VOLUME:
  ATR(14): ${atr:.2f} ({atr_pct:.2f}% of price)
  Relative Volume: {rvol:.2f}x ({"above" if rvol > 1.2 else "below"} average)

MARKET CONTEXT:
  Current Regime: {regime.upper()}

Score this setup and provide your technical analysis as JSON."""
