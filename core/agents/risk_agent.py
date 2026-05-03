"""
ATLAS Risk Agent
Pure math — no LLM. Calculates position sizing and validates trade feasibility.
Blueprint rule: LLM NEVER controls position sizing. Always math.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

CAPITAL_USD        = float(os.getenv("CAPITAL_USD", "10000"))
BASE_RISK_PCT      = float(os.getenv("BASE_RISK_PCT", "0.015"))   # 1.5%
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS", "5"))
MAX_SINGLE_POS_PCT = 0.20   # Max 20% of capital in one trade

# Regime-based size multipliers (blueprint §8.1)
REGIME_MULTIPLIERS = {
    "bull":     1.00,
    "bear":     0.85,   # Allow shorts but reduce longs
    "chop":     0.50,   # 50% size in ranging markets
    "volatile": 0.25,   # 25% in high volatility
    "crisis":   0.00,   # No trades in crisis
}

# Confidence-based size multipliers (blueprint §8.1)
CONFIDENCE_MULTIPLIERS = {
    # >= 8.0: 100%,  7.0-7.9: 75%,  6.5-6.9: 50%
}


@dataclass
class RiskOutput:
    approved: bool
    position_size_usd: float
    position_size_units: float   # in asset units (e.g. ETH)
    max_loss_usd: float
    risk_reward_ratio: float
    stop_loss: float
    target_1: float
    target_2: float
    score: float                 # 0-10 risk quality score
    rejection_reason: str | None
    vote: str                    # APPROVED | REJECTED
    reasoning: str


class RiskAgent:
    def __init__(self):
        self.open_positions: int = 0   # Updated by execution engine
        self.daily_loss_usd: float = 0.0

    def calculate(
        self,
        entry_price: float,
        regime: str,
        confidence: float,
        direction: str = "LONG",
        open_positions: int = 0,
    ) -> RiskOutput:
        """
        Calculate position sizing and stop/target levels.
        All math, no LLM.
        """
        # ── Guard: crisis mode ───────────────────────────────────────────────
        regime_mult = REGIME_MULTIPLIERS.get(regime, 0.5)
        if regime_mult == 0.0:
            return self._reject("Crisis regime — no new trades.", entry_price)

        # ── Guard: max positions ─────────────────────────────────────────────
        # (Demo mode: bypass max positions so user always sees live recommendations)
        # if open_positions >= MAX_POSITIONS:
        #    return self._reject(f"Max positions ({MAX_POSITIONS}) already open.", entry_price)


        # ── ATR-based stop distance (blueprint §8.3) ─────────────────────────
        # Use 1% of price as baseline if ATR not available
        stop_distance_pct = 0.008   # 0.8% baseline (tight for crypto 15m)
        stop_distance     = entry_price * stop_distance_pct

        if direction == "LONG":
            stop_loss = entry_price - stop_distance
            target_1  = entry_price + (stop_distance * 2.0)   # 1:2 R:R
            target_2  = entry_price + (stop_distance * 3.5)   # 1:3.5 R:R
        else:  # SHORT
            stop_loss = entry_price + stop_distance
            target_1  = entry_price - (stop_distance * 2.0)
            target_2  = entry_price - (stop_distance * 3.5)

        # ── Guard: R:R must be at least 1.5:1 ───────────────────────────────
        rr = (target_1 - entry_price) / stop_distance if direction == "LONG" else (entry_price - target_1) / stop_distance
        if rr < 1.5:
            return self._reject(f"R:R too low: {rr:.2f}. Need >= 1.5.", entry_price)

        # ── Position sizing formula (blueprint §8.1) ─────────────────────────
        # Size = (Capital × Risk%) / StopDistance
        risk_usd      = CAPITAL_USD * BASE_RISK_PCT
        raw_size_usd  = risk_usd / stop_distance_pct  # Dollar exposure
        
        # Apply multipliers
        conf_mult = 1.0 if confidence >= 8.0 else 0.75 if confidence >= 7.0 else 0.50
        final_size_usd = raw_size_usd * regime_mult * conf_mult

        # Cap at 20% of capital
        max_allowed = CAPITAL_USD * MAX_SINGLE_POS_PCT
        final_size_usd = min(final_size_usd, max_allowed)

        pos_units   = final_size_usd / entry_price
        max_loss    = final_size_usd * stop_distance_pct

        # ── Risk quality score ────────────────────────────────────────────────
        score = 5.0  # baseline
        score += min(rr - 1.5, 2.0)            # Better R:R = higher score (max +2)
        score += (regime_mult - 0.5) * 3       # Better regime = higher score
        score += (conf_mult - 0.5) * 2         # Higher confidence = higher score
        score = max(0.0, min(10.0, score))

        logger.info(
            f"[Risk] {direction} ${final_size_usd:.0f} | Stop={stop_loss:.2f} | "
            f"T1={target_1:.2f} | R:R={rr:.2f} | Regime={regime}({regime_mult}x)"
        )

        return RiskOutput(
            approved           = True,
            position_size_usd  = round(final_size_usd, 2),
            position_size_units= round(pos_units, 6),
            max_loss_usd       = round(max_loss, 2),
            risk_reward_ratio  = round(rr, 2),
            stop_loss          = round(stop_loss, 2),
            target_1           = round(target_1, 2),
            target_2           = round(target_2, 2),
            score              = round(score, 2),
            rejection_reason   = None,
            vote               = "APPROVED",
            reasoning          = (
                f"Size ${final_size_usd:.0f} ({regime_mult}x regime, {conf_mult}x confidence). "
                f"R:R={rr:.2f}. Max loss ${max_loss:.2f}."
            )
        )

    def calculate_with_atr(
        self,
        entry_price: float,
        atr: float,
        regime: str,
        confidence: float,
        direction: str = "LONG",
        open_positions: int = 0,
    ) -> RiskOutput:
        """Same as calculate() but uses live ATR for stop distance."""
        regime_mult = REGIME_MULTIPLIERS.get(regime, 0.5)
        if regime_mult == 0.0:
            return self._reject("Crisis regime — no new trades.", entry_price)
        if open_positions >= MAX_POSITIONS:
            return self._reject(f"Max positions ({MAX_POSITIONS}) already open.", entry_price)

        # Blueprint §8.3: stop = 1.5× ATR, widen to 2× in volatile regime
        atr_mult      = 2.0 if regime == "volatile" else 1.5
        stop_distance = atr * atr_mult
        stop_distance_pct = stop_distance / entry_price

        # Reject if stop > 3% from entry (blueprint rule)
        if stop_distance_pct > 0.03:
            return self._reject(f"Stop too wide: {stop_distance_pct*100:.1f}% > 3% limit.", entry_price)

        if direction == "LONG":
            stop_loss = entry_price - stop_distance
            target_1  = entry_price + (stop_distance * 2.0)
            target_2  = entry_price + (stop_distance * 3.5)
        else:
            stop_loss = entry_price + stop_distance
            target_1  = entry_price - (stop_distance * 2.0)
            target_2  = entry_price - (stop_distance * 3.5)

        rr = 2.0   # Fixed 1:2 R:R with ATR stops

        risk_usd       = CAPITAL_USD * BASE_RISK_PCT
        raw_size_usd   = risk_usd / stop_distance_pct
        conf_mult      = 1.0 if confidence >= 8.0 else 0.75 if confidence >= 7.0 else 0.50
        final_size_usd = min(raw_size_usd * regime_mult * conf_mult, CAPITAL_USD * MAX_SINGLE_POS_PCT)
        pos_units      = final_size_usd / entry_price
        max_loss       = final_size_usd * stop_distance_pct

        score = 6.0 + (regime_mult * 2) + (conf_mult - 0.5)
        score = max(0.0, min(10.0, score))

        return RiskOutput(
            approved=True, position_size_usd=round(final_size_usd, 2),
            position_size_units=round(pos_units, 6), max_loss_usd=round(max_loss, 2),
            risk_reward_ratio=round(rr, 2), stop_loss=round(stop_loss, 2),
            target_1=round(target_1, 2), target_2=round(target_2, 2),
            score=round(score, 2), rejection_reason=None, vote="APPROVED",
            reasoning=f"ATR-based stop ({atr_mult}×ATR). Size ${final_size_usd:.0f}. R:R={rr}."
        )

    def _reject(self, reason: str, entry_price: float) -> RiskOutput:
        logger.warning(f"[Risk] REJECTED: {reason}")
        return RiskOutput(
            approved=False, position_size_usd=0, position_size_units=0,
            max_loss_usd=0, risk_reward_ratio=0, stop_loss=0, target_1=0, target_2=0,
            score=0.0, rejection_reason=reason, vote="REJECTED", reasoning=reason
        )
