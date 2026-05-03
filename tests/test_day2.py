"""
ATLAS Day 2 Smoke Test
Tests full agent pipeline with LIVE market data + MOCK LLM (no API key needed).
Flow: yfinance data → indicators → all agents → Judge → TradeSignal
"""

import asyncio
import sys
import pandas as pd
import ta
import yfinance as yf

from core.data.regime_detector import classify_regime, REGIME_POLICY_MAP
from core.agents.analyst_agent    import AnalystAgent, AnalystOutput
from core.agents.technician_agent import TechnicianAgent
from core.agents.risk_agent       import RiskAgent
from core.agents.contrarian_agent import ContrarianAgent
from core.agents.judge            import JudgeAgent


def get_live_indicators() -> dict:
    """Fetch live ETH-USD 15m data and compute indicators."""
    df = yf.download("ETH-USD", period="30d", interval="15m", auto_adjust=True, progress=False)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})

    close = df["close"].squeeze()
    high  = df["high"].squeeze()
    low   = df["low"].squeeze()
    vol   = df["volume"].squeeze()

    ema9  = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    ema21 = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    atr   = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    bb    = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    macd  = ta.trend.MACD(close)
    rsi   = ta.momentum.RSIIndicator(close, window=14).rsi()
    vwap  = ta.volume.VolumeWeightedAveragePrice(high, low, close, vol).volume_weighted_average_price()

    latest = df.iloc[-1]
    def v(s): return float(s.iloc[-1]) if hasattr(s.iloc[-1], '__float__') else 0.0

    return {
        "close":       v(close),
        "high":        float(latest["high"].item() if hasattr(latest["high"], "item") else latest["high"]),
        "low":         float(latest["low"].item()  if hasattr(latest["low"],  "item") else latest["low"]),
        "rsi":         v(rsi),
        "macd":        v(macd.macd()),
        "macd_signal": v(macd.macd_signal()),
        "macd_hist":   v(macd.macd_diff()),
        "ema9":        v(ema9),
        "ema21":       v(ema21),
        "ema50":       v(ema50),
        "atr":         v(atr),
        "vwap":        v(vwap),
        "bb_upper":    v(bb.bollinger_hband()),
        "bb_lower":    v(bb.bollinger_lband()),
        "rvol":        1.0,   # yfinance doesn't give easy RVOL, use 1.0 baseline
    }


async def test_agent_pipeline():
    print("\n" + "="*60)
    print("  ATLAS Day 2 Smoke Test — Agent Pipeline")
    print("="*60)

    # ── Step 1: Live data ────────────────────────────────────────────────────
    print("\n[1/6] Fetching live market data...")
    ind = get_live_indicators()
    print(f"      Close=${ind['close']:,.2f} | RSI={ind['rsi']:.1f} | ATR=${ind['atr']:.2f}")
    print(f"      EMA9={ind['ema9']:.0f} > EMA21={ind['ema21']:.0f} ? {ind['ema9'] > ind['ema21']}")

    # ── Step 2: Regime ───────────────────────────────────────────────────────
    print("\n[2/6] Classifying regime...")
    regime, regime_score = classify_regime(ind, {})
    policy = REGIME_POLICY_MAP.get(regime, "C")
    print(f"      Regime: {regime.upper()} (score={regime_score:.2f}) -> Policy {policy}")

    # ── Step 3: Analyst (mock LLM) ───────────────────────────────────────────
    print("\n[3/6] Running Analyst Agent (mock LLM)...")
    analyst = AnalystAgent()
    # Don't connect Redis — test offline mode
    analyst_out = await analyst.analyze("ETH")
    print(f"      Vote: {analyst_out.vote} | Score: {analyst_out.score:.1f}/10")
    print(f"      Sentiment: {analyst_out.sentiment_score:+.2f} | Bullish: {analyst_out.bullish_flag}")
    print(f"      Summary: {analyst_out.summary[:80]}...")

    # ── Step 4: Technician (mock LLM) ────────────────────────────────────────
    print("\n[4/6] Running Technician Agent (mock LLM)...")
    tech = TechnicianAgent()
    tech_out = await tech.analyze(ind, regime)
    print(f"      Vote: {tech_out.vote} | Setup Score: {tech_out.setup_score:.1f}/10")
    print(f"      Direction: {tech_out.direction_bias} | Alignment: {tech_out.timeframe_alignment}")
    print(f"      Flags: {tech_out.flags}")

    # ── Step 5: Risk Agent (pure math) ────────────────────────────────────────
    print("\n[5/6] Running Risk Agent (pure math)...")
    risk = RiskAgent()
    risk_out = risk.calculate_with_atr(
        entry_price=ind["close"], atr=ind["atr"],
        regime=regime, confidence=6.5,
        direction=tech_out.direction_bias or "LONG",
        open_positions=0
    )
    print(f"      Vote: {risk_out.vote} | Score: {risk_out.score:.1f}")
    print(f"      Size: ${risk_out.position_size_usd:.2f} ({risk_out.position_size_units:.4f} ETH)")
    print(f"      Stop: ${risk_out.stop_loss:.2f} | T1: ${risk_out.target_1:.2f} | T2: ${risk_out.target_2:.2f}")
    print(f"      Max Loss: ${risk_out.max_loss_usd:.2f} | R:R: {risk_out.risk_reward_ratio}")

    # ── Step 6: Contrarian + Judge ────────────────────────────────────────────
    print("\n[6/6] Running Contrarian + Judge (mock LLM)...")
    contrarian = ContrarianAgent()
    contr_out = await contrarian.analyze(ind, tech_out.vote, regime)
    print(f"      Contrarian Vote: {contr_out.vote} | Risk Score: {contr_out.overall_risk_score:.1f}")
    print(f"      Concerns: {len(contr_out.concerns)} | Penalty: -{contr_out.penalty:.2f}")
    for c in contr_out.concerns[:3]:
        print(f"        [{c.get('severity','?').upper()}] {c.get('issue','')[:70]}")

    judge = JudgeAgent()
    signal = judge.decide(
        rl_confidence = 6.0,   # Simulated PPO output
        analyst       = analyst_out,
        technician    = tech_out,
        risk          = risk_out,
        contrarian    = contr_out,
        regime        = regime,
        active_policy = policy,
        symbol        = "ETH/USD",
        price         = ind["close"],
    )

    print(f"\n{'='*60}")
    print(f"  FINAL TRADE SIGNAL")
    print(f"{'='*60}")
    print(f"  Decision:   {signal.decision}")
    print(f"  Direction:  {signal.direction}")
    print(f"  Confidence: {signal.confidence:.3f}/10")
    print(f"  Size:       ${signal.position_size_usd:.2f} ({signal.size_multiplier*100:.0f}%)")
    print(f"  Entry:      ${signal.entry_price:,.2f}")
    print(f"  Stop:       ${signal.stop_loss:,.2f}")
    print(f"  Target 1:   ${signal.target_1:,.2f}")
    print(f"  Target 2:   ${signal.target_2:,.2f}")
    print(f"  DNA:        {signal.strategy_dna}")
    print(f"  Policy:     {signal.active_policy}")
    print(f"\n  Agent Breakdown:")
    print(f"    RL Policy:    {signal.rl_vote:.1f} x{W_RL:.2f}")
    print(f"    Technician:   {signal.tech_score:.1f} x{W_TECH:.2f}")
    print(f"    Analyst:      {signal.analyst_score:.1f} x{W_ANALYST:.2f}")
    print(f"    Risk:         {signal.risk_score:.1f} x{W_RISK:.2f}")
    print(f"    Contrarian:   -{signal.contrarian_penalty:.2f} (penalty)")
    print(f"\n  Reasoning: {signal.reasoning_summary}")
    print(f"\n{'='*60}")
    print(f"  Day 2 Smoke Test PASSED")
    print(f"{'='*60}\n")


# Constants for display
W_RL, W_TECH, W_ANALYST, W_RISK = 0.35, 0.30, 0.20, 0.15

if __name__ == "__main__":
    asyncio.run(test_agent_pipeline())
