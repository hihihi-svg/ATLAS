"""
ATLAS HERMES Memory Agent
End-of-day tasks:
  1. Post-mortem: analyse closed trades → store lessons
  2. Strategy DNA evolution: update weights based on win/loss per DNA
  3. Regime performance tracking: what regime made money?
  4. Memory persistence: save to JSON (Redis optional)
  5. Morning briefing: generate start-of-day summary

Blueprint §10: HERMES = Hindsight & Experience Retrieval Memory Engine System
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from pathlib import Path
from loguru import logger

from core.agents.llm_client import call_llm
from core.execution import circuit_breakers as cb

MEMORY_DIR  = Path(os.getenv("MEMORY_DIR", "memory"))
MEMORY_DIR.mkdir(exist_ok=True)

HERMES_SYSTEM_PROMPT = """You are HERMES, the Senior Market Analyst for an autonomous crypto advisory system.
Your job is to write a BIG, comprehensive, easy-to-understand Daily Market Report based ONLY on the 4 graphs provided to you.

Focus heavily on:
1. The 4 Graphs (Price, Moving Averages, RSI, MACD). Explain what they are currently doing in plain, simple English that a beginner can understand.
2. What is your final conclusion and clear recommendation for the user? What should they expect tomorrow?

Make the report BIG, comprehensive, and highly readable. Do not use complex trading jargon without explaining it.

Output ONLY valid JSON:
{
  "performance_grade": "<A|B|C|D|F>",
  "top_insight": "<single most important lesson>",
  "daily_market_report": "<Long, detailed, comprehensive daily market report using markdown formatting. Address the 4 graphs explicitly. Give a clear final conclusion.>",
  "strategy_lessons": [{"dna": "<strategy>", "assessment": "<brief>", "adjust": "<increase|decrease|maintain>"}],
  "failure_patterns": ["<pattern 1>", "<pattern 2>"],
  "tomorrow_rules": ["<actionable rule>", "<actionable rule>"]
}"""


@dataclass
class DayMemory:
    """Complete memory for one trading day."""
    date:            str
    trades:          list[dict]
    total_pnl:       float
    win_rate:        float
    total_trades:    int
    wins:            int
    losses:          int
    regime_breakdown: dict     # {regime: {trades, pnl}}
    dna_breakdown:   dict      # {dna: {trades, pnl, wins}}
    lessons:         dict      # Raw LLM post-mortem output
    circuit_events:  list[str]
    morning_briefing: str = ""


@dataclass
class StrategyDNA_Weights:
    """
    Evolving weights per strategy DNA.
    Updated daily based on win rate performance.
    """
    momentum:       float = 1.0
    mean_reversion: float = 1.0
    sentiment:      float = 1.0
    breakout:       float = 1.0

    def update(self, dna: str, win_rate: float, trades: int):
        """Increase weight if win_rate > 60%, decrease if < 40%."""
        if trades < 3:
            return   # Not enough data
        current = getattr(self, dna, 1.0)
        if win_rate > 0.60:
            new_w = min(current * 1.10, 1.5)   # Max 1.5x
        elif win_rate < 0.40:
            new_w = max(current * 0.90, 0.5)   # Min 0.5x
        else:
            new_w = current   # No change
        setattr(self, dna, round(new_w, 3))
        logger.info(f"[HERMES] DNA weight updated: {dna} {current:.3f} → {new_w:.3f} (WR={win_rate:.0%})")


class HERMESAgent:
    def __init__(self):
        self.weights_path = MEMORY_DIR / "dna_weights.json"
        self.dna_weights  = self._load_dna_weights()

    def _load_dna_weights(self) -> StrategyDNA_Weights:
        if self.weights_path.exists():
            try:
                data = json.loads(self.weights_path.read_text())
                return StrategyDNA_Weights(**data)
            except Exception:
                pass
        return StrategyDNA_Weights()

    def _save_dna_weights(self):
        self.weights_path.write_text(json.dumps(asdict(self.dna_weights), indent=2))

    async def run_post_mortem(self, trade_log: list[dict], signal_history: list[dict], market_data: dict = None) -> DayMemory:
        """
        Called at end of day (or on demand).
        Analyses trades, generates lessons, updates DNA weights.
        """
        today = date.today().isoformat()
        logger.info(f"[HERMES] Running post-mortem for {today} ({len(trade_log)} trades)")

        if not trade_log and not market_data:
            logger.info("[HERMES] No trades today and no market data. Skipping post-mortem.")
            return self._empty_day_memory(today)

        # ── Compute stats ─────────────────────────────────────────────────────
        wins       = [t for t in trade_log if t.get("pnl_usd", 0) >= 0]
        losses     = [t for t in trade_log if t.get("pnl_usd", 0) < 0]
        total_pnl  = sum(t.get("pnl_usd", 0) for t in trade_log)
        win_rate   = len(wins) / len(trade_log) if len(trade_log) > 0 else 0.0

        # ── Regime breakdown ──────────────────────────────────────────────────
        regime_bd = {}
        for sig in signal_history:
            if sig.get("decision") != "EXECUTE":
                continue
            r = sig.get("regime", "unknown")
            if r not in regime_bd:
                regime_bd[r] = {"trades": 0, "pnl": 0}
            regime_bd[r]["trades"] += 1

        # ── DNA breakdown ─────────────────────────────────────────────────────
        dna_bd = {}
        for sig in signal_history:
            if sig.get("decision") != "EXECUTE":
                continue
            d = sig.get("strategy", "unknown")
            if d not in dna_bd:
                dna_bd[d] = {"trades": 0, "pnl": 0, "wins": 0}
            dna_bd[d]["trades"] += 1

        # Match trades to signals by rough index for DNA pnl (simplified)
        for i, t in enumerate(trade_log):
            if i < len(signal_history):
                d = signal_history[i].get("strategy", "unknown")
                if d in dna_bd:
                    dna_bd[d]["pnl"] += t.get("pnl_usd", 0)
                    if t.get("pnl_usd", 0) >= 0:
                        dna_bd[d]["wins"] += 1

        # ── Update DNA weights ────────────────────────────────────────────────
        for dna, stats in dna_bd.items():
            if stats["trades"] >= 2 and hasattr(self.dna_weights, dna.replace("-", "_")):
                wr = stats["wins"] / stats["trades"]
                self.dna_weights.update(dna, wr, stats["trades"])
        self._save_dna_weights()

        # ── LLM post-mortem ───────────────────────────────────────────────────
        user_prompt = self._build_post_mortem_prompt(
            trade_log, total_pnl, win_rate, regime_bd, dna_bd, market_data
        )
        lessons = await call_llm(HERMES_SYSTEM_PROMPT, user_prompt, max_tokens=1000)

        # ── Circuit events ────────────────────────────────────────────────────
        cb_state = cb.get_state()
        circuit_events = []
        if cb_state.trading_halted:
            circuit_events.append(f"Trading halted: {cb_state.halt_reason}")
        if cb_state.consecutive_losses >= 3:
            circuit_events.append(f"Consecutive loss reduction triggered ({cb_state.consecutive_losses} losses)")

        # ── Morning briefing ──────────────────────────────────────────────────
        briefing = await self._generate_morning_briefing(lessons, total_pnl, win_rate)

        mem = DayMemory(
            date            = today,
            trades          = trade_log,
            total_pnl       = round(total_pnl, 2),
            win_rate        = round(win_rate, 3),
            total_trades    = len(trade_log),
            wins            = len(wins),
            losses          = len(losses),
            regime_breakdown= regime_bd,
            dna_breakdown   = dna_bd,
            lessons         = lessons,
            circuit_events  = circuit_events,
            morning_briefing= briefing,
        )

        # ── Save to disk ──────────────────────────────────────────────────────
        self._save_memory(mem)
        logger.info(f"[HERMES] Post-mortem complete. Grade: {lessons.get('performance_grade','?')} | PnL=${total_pnl:+.2f} | WR={win_rate:.0%}")
        return mem

    async def _generate_morning_briefing(self, lessons: dict, pnl: float, wr: float) -> str:
        """Short morning briefing message for Telegram."""
        grade    = lessons.get("performance_grade", "?")
        insight  = lessons.get("top_insight", "No data")
        rules    = lessons.get("tomorrow_rules", [])
        wr_pct   = f"{wr*100:.0f}%"
        rules_str = "\n".join(f"• {r}" for r in rules[:3])

        return (
            f"🌅 ATLAS Morning Briefing\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Yesterday Grade:  {grade}\n"
            f"P&L:  ${pnl:+.2f} | Win Rate: {wr_pct}\n"
            f"DNA Weights: {self._weights_summary()}\n"
            f"\nTop Insight:\n{insight}\n"
            f"\nToday's Rules:\n{rules_str}"
        )

    def _weights_summary(self) -> str:
        w = self.dna_weights
        return f"MOM:{w.momentum:.2f} MR:{w.mean_reversion:.2f} SENT:{w.sentiment:.2f}"

    def _build_post_mortem_prompt(self, trades, pnl, wr, regime_bd, dna_bd, market_data) -> str:
        md_str = ""
        if market_data:
            md_str = f"""
CURRENT MARKET DATA FOR THE 4 GRAPHS:
Price (Close): ${market_data.get('close', 0):.2f}
EMAs (Moving Averages): 9-EMA=${market_data.get('ema9',0):.2f}, 21-EMA=${market_data.get('ema21',0):.2f}, 50-EMA=${market_data.get('ema50',0):.2f}
RSI (Momentum): {market_data.get('rsi', 0):.2f}
MACD Histogram: {market_data.get('macd_hist', 0):.4f}
Volume (RVOL): {market_data.get('rvol', 0):.2f}x average
"""

        return f"""Write the Daily Market Report based on current conditions:
{md_str}

Ignore past trades. Focus ONLY on the market analysis of the 4 graphs above.
Generate your analysis and Daily Market Report as JSON."""

    def _save_memory(self, mem: DayMemory):
        path = MEMORY_DIR / f"memory_{mem.date}.json"
        path.write_text(json.dumps(asdict(mem), indent=2))
        logger.info(f"[HERMES] Memory saved to {path}")

    def load_memory(self, day: str = None) -> dict | None:
        day  = day or date.today().isoformat()
        path = MEMORY_DIR / f"memory_{day}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def get_all_memories(self) -> list[dict]:
        """Load all saved memories for weekly review."""
        memories = []
        for f in sorted(MEMORY_DIR.glob("memory_*.json")):
            try:
                memories.append(json.loads(f.read_text()))
            except Exception:
                continue
        return memories

    def get_dna_weights(self) -> dict:
        return asdict(self.dna_weights)

    def _empty_day_memory(self, today: str) -> DayMemory:
        return DayMemory(
            date=today, trades=[], total_pnl=0, win_rate=0,
            total_trades=0, wins=0, losses=0,
            regime_breakdown={}, dna_breakdown={},
            lessons={"performance_grade": "N/A", "top_insight": "No trades today"},
            circuit_events=[], morning_briefing="No trades — markets closed or system idle."
        )
