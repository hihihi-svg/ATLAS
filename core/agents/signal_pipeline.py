"""
ATLAS Signal Pipeline
Orchestrates all agents in parallel for a given trade opportunity.
Flow: Indicators + News → [Analyst, Technician, Risk, Contrarian] → Judge → TradeSignal
"""

import asyncio
import os
from loguru import logger

from core.agents.analyst_agent    import AnalystAgent
from core.agents.technician_agent import TechnicianAgent
from core.agents.risk_agent       import RiskAgent
from core.agents.contrarian_agent import ContrarianAgent
from core.agents.judge            import JudgeAgent, TradeSignal

# Lazy import — RL policy loaded separately
_analyst    = AnalystAgent()
_technician = TechnicianAgent()
_risk       = RiskAgent()
_contrarian = ContrarianAgent()
_judge      = JudgeAgent()

SYMBOL = os.getenv("TRADING_PAIR", "ETH/USDT")


async def evaluate_trade_opportunity(
    indicators: dict,
    regime: str,
    active_policy: str,
    rl_confidence: float = 5.0,   # From PPO policy (0-10). Default neutral.
    open_positions: int  = 0,
) -> TradeSignal:
    """
    Run all agents in parallel and produce final trade decision.
    This is the main entry point called by the market data loop.
    """
    price  = indicators.get("close", 0)
    symbol = SYMBOL.split("/")[0] + "/USD"

    if price == 0:
        logger.error("[Pipeline] No price data. Skipping evaluation.")
        return None

    logger.info(f"[Pipeline] Evaluating {symbol} @ ${price:.2f} | Regime={regime} Policy={active_policy}")

    # ── Run analyst + technician + contrarian in parallel ────────────────────
    analyst_task    = _analyst.analyze(symbol.split("/")[0], indicators)
    technician_task = _technician.analyze(indicators, regime)

    analyst_out, tech_out = await asyncio.gather(analyst_task, technician_task)

    # ── Risk is pure math — no await needed ──────────────────────────────────
    atr = indicators.get("atr", 0)
    if atr and atr > 0:
        risk_out = _risk.calculate_with_atr(
            entry_price=price, atr=atr, regime=regime,
            confidence=rl_confidence, direction=tech_out.direction_bias or "LONG",
            open_positions=open_positions
        )
    else:
        risk_out = _risk.calculate(
            entry_price=price, regime=regime,
            confidence=rl_confidence, direction=tech_out.direction_bias or "LONG",
            open_positions=open_positions
        )

    # ── Contrarian runs after technician (needs tech vote) ───────────────────
    contrarian_out = await _contrarian.analyze(indicators, tech_out.vote, regime)

    # ── Judge combines all votes ──────────────────────────────────────────────
    signal = _judge.decide(
        rl_confidence = rl_confidence,
        analyst       = analyst_out,
        technician    = tech_out,
        risk          = risk_out,
        contrarian    = contrarian_out,
        regime        = regime,
        active_policy = active_policy,
        symbol        = symbol,
        price         = price,
    )

    return signal


async def connect_agents():
    """Connect Redis-dependent agents."""
    await _analyst.connect()

async def disconnect_agents():
    """Clean up connections."""
    await _analyst.disconnect()
