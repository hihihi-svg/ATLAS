"""
ATLAS Contrarian Agent
Specifically tasked with finding reasons NOT to take the trade.
Adversarial by design — argues against every signal.
Outputs: list of concerns with severity + overall red flag score.
"""

from dataclasses import dataclass, field
from loguru import logger
from core.agents.llm_client import call_llm

CONTRARIAN_SYSTEM_PROMPT = """You are a skeptical risk manager reviewing a proposed ETH/USD trade.
Your job is to identify GENUINE risks — not to reject every trade, but to catch real problems.

Flag concerns only when data actually supports them:
- RSI > 72: Overbought risk (HIGH)
- RSI < 28: Oversold risk (HIGH)
- RVOL < 0.4: Dangerously low volume (HIGH)
- MACD histogram negative when BUY proposed: Momentum divergence (MEDIUM)
- Price within 0.3% of BB Upper when BUY: Near resistance (MEDIUM)
- Regime = CHOP: Poor timing (MEDIUM)
- RVOL 0.4-0.9: Low volume caution (LOW)
- EMA crossed bearish: Trend concern (LOW)

Set trade_killing_concern=true ONLY if 2 or more HIGH severity concerns exist.
If the setup is reasonable, vote PASS and keep concerns minimal.

Severity: "low" = minor, "medium" = notable, "high" = serious risk

Output ONLY valid JSON:
{
  "concerns": [
    {"issue": "<specific concern>", "severity": "<low|medium|high>"}
  ],
  "overall_risk_score": <float 0-10, where 10=maximum risk>,
  "trade_killing_concern": <true ONLY if 2+ HIGH severity issues>,
  "vote": "<CAUTION|REJECT|PASS>",
  "reasoning": "<brief summary>"
}"""


@dataclass
class ContrarianOutput:
    concerns: list[dict]          # List of {issue, severity}
    overall_risk_score: float     # 0-10 (higher = more risky)
    trade_killing_concern: bool   # True = at least one HIGH severity
    vote: str                     # CAUTION | REJECT | PASS
    penalty: float                # How much to subtract from confidence (0-2.0)
    reasoning: str
    raw: dict


class ContrarianAgent:

    async def analyze(self, indicators: dict, tech_vote: str, regime: str) -> ContrarianOutput:
        """
        Challenge the proposed trade. Look for red flags.
        """
        user_prompt = self._build_prompt(indicators, tech_vote, regime)
        logger.debug(f"[Contrarian] Challenging {tech_vote} signal in {regime} regime...")

        result = await call_llm(CONTRARIAN_SYSTEM_PROMPT, user_prompt, max_tokens=400)

        concerns = result.get("concerns", [])
        risk_score = float(result.get("overall_risk_score", 5.0))
        killing = bool(result.get("trade_killing_concern", False))
        vote = result.get("vote", "CAUTION")

        # Calculate penalty for Judge (blueprint §7.4)
        # 0 concerns = 0, medium concerns = -0.5, high severity = -2.0
        penalty = self._calc_penalty(concerns, killing)

        return ContrarianOutput(
            concerns              = concerns,
            overall_risk_score    = risk_score,
            trade_killing_concern = killing,
            vote                  = vote,
            penalty               = penalty,
            reasoning             = result.get("reasoning", ""),
            raw                   = result
        )

    def _calc_penalty(self, concerns: list[dict], killing: bool) -> float:
        penalty = 0.0
        high_count = 0
        for c in concerns:
            sev = c.get("severity", "low")
            if sev == "high":
                penalty += 0.6
                high_count += 1
            elif sev == "medium":
                penalty += 0.25
            elif sev == "low":
                penalty += 0.05
        # Only apply killing bonus if genuinely 2+ high concerns
        if killing and high_count >= 2:
            penalty += 0.5
        return min(penalty, 1.20)   # Cap at 1.2 (was 2.0)

    def _build_prompt(self, ind: dict, tech_vote: str, regime: str) -> str:
        close  = ind.get("close", 0)
        rsi    = ind.get("rsi", 50)
        mhist  = ind.get("macd_hist", 0)
        ema9   = ind.get("ema9", 0)
        ema21  = ind.get("ema21", 0)
        vwap   = ind.get("vwap", 0)
        rvol   = ind.get("rvol", 1.0)
        bb_u   = ind.get("bb_upper", 0)
        atr    = ind.get("atr", 0)

        dist_from_vwap = abs(close - vwap) / vwap * 100 if vwap else 0
        dist_from_bb_u = (bb_u - close) / close * 100 if bb_u else 0

        return f"""The Technician just voted {tech_vote} on ETH/USD. Challenge this decision.

Current data:
- Price: ${close:.2f} | Regime: {regime.upper()}
- RSI: {rsi:.1f} | MACD Hist: {mhist:.4f} ({'positive' if mhist>0 else 'NEGATIVE'})
- EMA9: ${ema9:.2f} | EMA21: ${ema21:.2f} | {'aligned' if ema9>ema21 else 'CROSSED BEARISH'}
- Distance from VWAP: {dist_from_vwap:.2f}% ({'far' if dist_from_vwap>1.5 else 'close'})
- Distance to BB Upper: {dist_from_bb_u:.2f}% ({'near resistance' if dist_from_bb_u<1 else 'room to move'})
- RVOL: {rvol:.2f}x ({'volume confirmed' if rvol>1.3 else 'LOW VOLUME - no conviction'})
- ATR: ${atr:.2f}

Find EVERY reason NOT to take this trade. Be thorough and critical. Output as JSON."""
