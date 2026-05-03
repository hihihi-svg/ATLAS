"""
ATLAS Judge Agent
Final arbiter — combines votes from Analyst, Technician, Risk, and Contrarian agents.
Produces a TradeSignal with EXECUTE | WAIT | REJECT decision.
Blueprint §7: Confidence scoring + strategy DNA selection.
"""

from dataclasses import dataclass, field
from loguru import logger


# ── Confidence thresholds (blueprint §7.3) ────────────────────────────────────
EXECUTE_THRESHOLD = 6.5    # Must score ≥ 6.5 to EXECUTE
WAIT_THRESHOLD    = 4.5    # 4.5–6.4 = WAIT (signal present but not strong enough)
                           # < 4.5   = REJECT

# Per-regime min thresholds (tighter in bad regimes)
REGIME_MIN_CONFIDENCE = {
    "bull":     6.0,
    "bear":     7.0,   # Require stronger signal in bear market
    "chop":     7.5,   # Very selective in chop
    "volatile": 7.5,   # High bar in volatile
    "crisis":   99.0,  # Never execute in crisis (circuit breaker also blocks)
}

# Strategy DNA: which regime favors which approach
REGIME_STRATEGY_MAP = {
    "bull":     "momentum",
    "bear":     "mean_reversion",
    "chop":     "range_fade",
    "volatile": "volatility_breakout",
    "crisis":   "cash",
}


@dataclass
class TradeSignal:
    symbol:              str
    direction:           str          # LONG | SHORT | NONE
    entry_price:         float
    stop_loss:           float
    target_1:            float
    target_2:            float
    position_size_usd:   float
    position_size_units: float
    confidence:          float        # 0–10 composite score
    decision:            str          # EXECUTE | WAIT | REJECT
    size_multiplier:     float        # 0–1, applied by execution engine
    strategy_dna:        str          # momentum | mean_reversion | ...
    regime:              str
    active_policy:       str
    rl_vote:             float        # Raw RL confidence passed in
    analyst_score:       float
    tech_score:          float
    risk_score:          float
    contrarian_penalty:  float
    concerns:            list[str]    # From contrarian
    reasoning_summary:   str
    agent_votes:         dict         # Raw vote string per agent


class JudgeAgent:
    """
    Deterministic decision engine — no LLM.
    Weights: Tech 35% | Analyst 20% | RL 25% | Risk 20%
    Then subtract contrarian penalty.
    """

    # Agent weights (must sum to 1.0)
    W_TECH     = 0.35
    W_ANALYST  = 0.20
    W_RL       = 0.25
    W_RISK     = 0.20

    def decide(
        self,
        rl_confidence: float,
        analyst,       # AnalystOutput
        technician,    # TechnicianOutput
        risk,          # RiskOutput
        contrarian,    # ContrarianOutput
        regime:        str,
        active_policy: str,
        symbol:        str,
        price:         float,
    ) -> TradeSignal:
        """
        Combine all agent outputs into a final trade signal.
        """
        # ── 1. Reject immediately if risk math failed ─────────────────────────
        if not risk.approved:
            logger.info(f"[Judge] REJECT — Risk not approved: {risk.rejection_reason}")
            return self._make_signal(
                decision="REJECT", confidence=4.0, # Minimum floor for visibility
                direction="NONE", regime=regime, policy=active_policy,
                symbol=symbol, price=price, risk=risk,
                analyst=analyst, technician=technician,
                contrarian=contrarian, rl_vote=rl_confidence,
                reason=f"Risk rejected: {risk.rejection_reason}",
            )

        # ── 2. Reject if contrarian found trade-killing concerns ──────────────
        if contrarian.trade_killing_concern:
            logger.info(f"[Judge] REJECT — Contrarian kill: {contrarian.reasoning[:80]}")
            return self._make_signal(
                decision="REJECT", confidence=3.5, # Floor for visibility
                direction="NONE", regime=regime, policy=active_policy,
                symbol=symbol, price=price, risk=risk,
                analyst=analyst, technician=technician,
                contrarian=contrarian, rl_vote=rl_confidence,
                reason=f"Contrarian kill: {contrarian.reasoning}",
            )

        # ── 3. Compute weighted composite confidence ──────────────────────────
        # Normalise all scores to 0-10 scale before weighting
        tech_score     = float(technician.setup_score)          # already 0-10
        analyst_score  = float(analyst.score)                   # already 0-10
        rl_score       = max(0.0, min(10.0, float(rl_confidence)))
        risk_score     = float(risk.score)                      # already 0-10

        raw_confidence = (
            tech_score    * self.W_TECH    +
            analyst_score * self.W_ANALYST +
            rl_score      * self.W_RL      +
            risk_score    * self.W_RISK
        )

        # ── 4. Apply contrarian penalty ───────────────────────────────────────
        confidence = max(0.0, raw_confidence - contrarian.penalty)

        logger.info(
            f"[Judge] Raw={raw_confidence:.2f} Penalty={contrarian.penalty:.2f} "
            f"Final={confidence:.2f} | Tech={tech_score:.1f} "
            f"Ana={analyst_score:.1f} RL={rl_score:.1f} Risk={risk_score:.1f}"
        )

        # ── 5. Determine direction (technician leads) ─────────────────────────
        direction = technician.direction_bias  # LONG | SHORT | NONE

        # If analyst strongly disagrees with tech, downgrade to WAIT
        analyst_agrees = (
            (direction == "LONG"  and analyst.vote in ("BUY", "NEUTRAL")) or
            (direction == "SHORT" and analyst.vote in ("SELL", "NEUTRAL")) or
            (direction == "NONE")
        )
        if not analyst_agrees and analyst_score < 4.0:
            # Strong analyst disagreement — penalise further
            confidence -= 0.5
            logger.info(f"[Judge] Analyst strongly disagrees ({analyst.vote}). -0.5 penalty.")

        # ── 6. Regime-based minimum threshold ────────────────────────────────
        regime_min = REGIME_MIN_CONFIDENCE.get(regime, EXECUTE_THRESHOLD)

        # ── 7. Determine decision ─────────────────────────────────────────────
        if direction == "NONE" or technician.vote == "NEUTRAL":
            decision = "WAIT"
            reason   = f"No clear direction from Technician (regime={regime})"
        elif confidence >= max(EXECUTE_THRESHOLD, regime_min):
            decision = "EXECUTE"
            reason   = f"All agents aligned. Conf={confidence:.2f} ≥ threshold {max(EXECUTE_THRESHOLD, regime_min):.1f}"
        elif confidence >= WAIT_THRESHOLD:
            decision = "WAIT"
            reason   = f"Signal present but confidence {confidence:.2f} < execute threshold {max(EXECUTE_THRESHOLD, regime_min):.1f}"
        else:
            decision = "REJECT"
            reason   = f"Low confidence {confidence:.2f} < {WAIT_THRESHOLD} floor"

        # ── 8. Size multiplier (circuit-breaker-aware) ────────────────────────
        # Uses already-computed position size from risk agent
        size_mult = 1.0
        if confidence < 7.0:
            size_mult = 0.75
        if confidence < 6.0:
            size_mult = 0.50

        strategy = REGIME_STRATEGY_MAP.get(regime, "momentum")

        logger.info(
            f"[Judge] {decision} | {direction} | conf={confidence:.2f} | "
            f"strategy={strategy} | reason: {reason[:80]}"
        )

        return self._make_signal(
            decision=decision, confidence=round(confidence, 3),
            direction=direction, regime=regime, policy=active_policy,
            symbol=symbol, price=price, risk=risk,
            analyst=analyst, technician=technician,
            contrarian=contrarian, rl_vote=rl_confidence,
            reason=reason, strategy=strategy,
            size_mult=size_mult,
            tech_score=tech_score, analyst_score=analyst_score,
            risk_score=risk_score,
        )

    # ── Helper ─────────────────────────────────────────────────────────────────
    def _make_signal(
        self,
        decision:      str,
        confidence:    float,
        direction:     str,
        regime:        str,
        policy:        str,
        symbol:        str,
        price:         float,
        risk,
        analyst,
        technician,
        contrarian,
        rl_vote:       float,
        reason:        str,
        strategy:      str = "cash",
        size_mult:     float = 0.0,
        tech_score:    float = 0.0,
        analyst_score: float = 0.0,
        risk_score:    float = 0.0,
    ) -> TradeSignal:
        concerns = [c.get("issue", "") for c in contrarian.concerns]
        return TradeSignal(
            symbol              = symbol,
            direction           = direction,
            entry_price         = price,
            stop_loss           = risk.stop_loss,
            target_1            = risk.target_1,
            target_2            = risk.target_2,
            position_size_usd   = risk.position_size_usd * size_mult,
            position_size_units = risk.position_size_units * size_mult,
            confidence          = confidence,
            decision            = decision,
            size_multiplier     = size_mult,
            strategy_dna        = strategy,
            regime              = regime,
            active_policy       = policy,
            rl_vote             = rl_vote,
            analyst_score       = analyst_score,
            tech_score          = tech_score,
            risk_score          = risk_score,
            contrarian_penalty  = contrarian.penalty,
            concerns            = concerns,
            reasoning_summary   = reason,
            agent_votes         = {
                "analyst":    analyst.vote,
                "technician": technician.vote,
                "contrarian": contrarian.vote,
                "risk":       risk.vote,
            },
        )