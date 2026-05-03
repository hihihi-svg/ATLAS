"""
ATLAS Stop Manager
Manages adaptive stop loss logic for open positions.
Four stop types per blueprint §8.3 + §11:
  1. ATR Trailing  — moves with price, never backward
  2. Break-Even    — once +1R profit hit, move stop to entry
  3. Time Stop     — close if no movement after N hours
  4. Sentiment Flip — exit immediately on large sentiment drop
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from loguru import logger


@dataclass
class Position:
    """Tracks a single open trade and its adaptive stop state."""
    symbol:         str
    direction:      str          # LONG | SHORT
    entry_price:    float
    initial_stop:   float
    current_stop:   float        # Moves over time
    target_1:       float
    target_2:       float
    quantity:       float        # Units held
    atr_at_entry:   float

    # State flags
    break_even_triggered: bool = False
    target_1_hit:         bool = False
    quantity_remaining:   float = 0.0   # After partial exit at T1

    # Time tracking
    entry_time:     datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    max_hold_hours: float = 4.0  # Day trade default; swing = 72h

    # Sentiment tracking
    entry_sentiment: float = 0.0

    def __post_init__(self):
        self.quantity_remaining = self.quantity


class StopManager:

    # ── ATR Trailing Stop ─────────────────────────────────────────────────────

    def update_trailing_stop(self, pos: Position, current_price: float) -> tuple[bool, str]:
        """
        Move trailing stop using 1.5× ATR distance.
        Stop only MOVES IN PROFIT DIRECTION — never backward.
        Returns (stop_hit: bool, reason: str).
        """
        atr_mult = 1.5
        trail_dist = pos.atr_at_entry * atr_mult

        if pos.direction == "LONG":
            new_stop = current_price - trail_dist
            if new_stop > pos.current_stop:
                old = pos.current_stop
                pos.current_stop = new_stop
                logger.debug(f"[StopMgr] Trailing stop moved {old:.2f} → {new_stop:.2f} (price={current_price:.2f})")

            # Check if stop hit
            if current_price <= pos.current_stop:
                return True, f"Trailing stop hit at {current_price:.2f} (stop={pos.current_stop:.2f})"

        else:  # SHORT
            new_stop = current_price + trail_dist
            if new_stop < pos.current_stop:
                pos.current_stop = new_stop

            if current_price >= pos.current_stop:
                return True, f"Trailing stop hit at {current_price:.2f} (stop={pos.current_stop:.2f})"

        return False, ""

    # ── Break-Even Stop ───────────────────────────────────────────────────────

    def check_break_even(self, pos: Position, current_price: float) -> bool:
        """
        Move stop to entry once +1R profit is reached.
        1R = initial risk amount (entry - initial_stop).
        Returns True if break-even was just triggered.
        """
        if pos.break_even_triggered:
            return False

        initial_risk = abs(pos.entry_price - pos.initial_stop)

        if pos.direction == "LONG":
            profit_1r = pos.entry_price + initial_risk
            if current_price >= profit_1r:
                pos.current_stop = pos.entry_price  # Move to entry
                pos.break_even_triggered = True
                logger.info(f"[StopMgr] Break-even triggered! Stop moved to entry {pos.entry_price:.2f}")
                return True

        else:  # SHORT
            profit_1r = pos.entry_price - initial_risk
            if current_price <= profit_1r:
                pos.current_stop = pos.entry_price
                pos.break_even_triggered = True
                logger.info(f"[StopMgr] Break-even triggered! Stop moved to entry {pos.entry_price:.2f}")
                return True

        return False

    # ── Target Management ─────────────────────────────────────────────────────

    def check_targets(self, pos: Position, current_price: float) -> tuple[str, float]:
        """
        Check if T1 or T2 hit. T1 = close 50%, T2 = close remaining 50%.
        Returns (action: str, close_qty: float).
        action: 'none' | 'partial_t1' | 'full_t2'
        """
        if pos.direction == "LONG":
            if not pos.target_1_hit and current_price >= pos.target_1:
                close_qty = pos.quantity * 0.50
                pos.quantity_remaining -= close_qty
                pos.target_1_hit = True
                pos.current_stop = pos.entry_price   # Move to break-even on T1 hit
                pos.break_even_triggered = True
                logger.info(f"[StopMgr] TARGET 1 HIT at {current_price:.2f}! Closing 50% ({close_qty:.4f} units)")
                return "partial_t1", close_qty

            if pos.target_1_hit and current_price >= pos.target_2:
                close_qty = pos.quantity_remaining
                logger.info(f"[StopMgr] TARGET 2 HIT at {current_price:.2f}! Closing remaining {close_qty:.4f}")
                return "full_t2", close_qty

        else:  # SHORT
            if not pos.target_1_hit and current_price <= pos.target_1:
                close_qty = pos.quantity * 0.50
                pos.quantity_remaining -= close_qty
                pos.target_1_hit = True
                pos.current_stop = pos.entry_price
                pos.break_even_triggered = True
                return "partial_t1", close_qty

            if pos.target_1_hit and current_price <= pos.target_2:
                return "full_t2", pos.quantity_remaining

        return "none", 0.0

    # ── Time Stop ─────────────────────────────────────────────────────────────

    def check_time_stop(self, pos: Position, current_price: float, bar_time: datetime = None) -> tuple[bool, str]:
        """
        Close if position held too long without reaching T1.
        Day trade: 4 hours. Swing: 72 hours.
        bar_time: use historical bar time for backtesting (default = now).
        """
        if pos.target_1_hit:
            return False, ""   # Let it run to T2

        now = bar_time or datetime.now(timezone.utc)
        elapsed = now - pos.entry_time
        if elapsed > timedelta(hours=pos.max_hold_hours):
            return True, (
                f"Time stop: {elapsed.total_seconds()/3600:.1f}h elapsed "
                f"(limit={pos.max_hold_hours}h). No T1 reached."
            )

        return False, ""

    # ── Sentiment Flip Exit ───────────────────────────────────────────────────

    def check_sentiment_flip(
        self,
        pos: Position,
        current_sentiment: float,
        sentiment_delta_threshold: float = 0.5
    ) -> tuple[bool, str]:
        """
        Exit LONG immediately if sentiment drops >0.5 points rapidly.
        Exit SHORT if sentiment rises >0.5 points.
        """
        delta = current_sentiment - pos.entry_sentiment

        if pos.direction == "LONG" and delta <= -sentiment_delta_threshold:
            return True, f"Sentiment flip: {pos.entry_sentiment:+.2f} → {current_sentiment:+.2f} (delta={delta:.2f})"

        if pos.direction == "SHORT" and delta >= sentiment_delta_threshold:
            return True, f"Sentiment flip: {pos.entry_sentiment:+.2f} → {current_sentiment:+.2f} (delta={delta:.2f})"

        return False, ""

    # ── Master Check ──────────────────────────────────────────────────────────

    def full_check(
        self,
        pos: Position,
        current_price: float,
        current_sentiment: float = None,
        bar_time: datetime = None,
    ) -> dict:
        """
        Run all stop checks. Returns exit decision.
        Call every 60 seconds per blueprint §3.3.
        """
        result = {
            "should_exit":  False,
            "exit_qty":     0.0,
            "exit_reason":  "",
            "partial_exit": False,
            "break_even":   False,
        }

        # 1. Check targets first (priority)
        action, qty = self.check_targets(pos, current_price)
        if action == "full_t2":
            result.update(should_exit=True, exit_qty=qty, exit_reason="target_2", partial_exit=False)
            return result
        if action == "partial_t1":
            result.update(partial_exit=True, exit_qty=qty, exit_reason="target_1")
            # Don't return — continue monitoring remaining position

        # 2. Break-even
        be_triggered = self.check_break_even(pos, current_price)
        result["break_even"] = be_triggered

        # 3. Trailing stop (skip if partial exit just happened — stop already moved)
        stop_hit, stop_reason = self.update_trailing_stop(pos, current_price)
        if stop_hit:
            result.update(should_exit=True, exit_qty=pos.quantity_remaining, exit_reason=stop_reason)
            return result

        # 4. Time stop
        time_hit, time_reason = self.check_time_stop(pos, current_price, bar_time=bar_time)
        if time_hit:
            result.update(should_exit=True, exit_qty=pos.quantity_remaining, exit_reason=time_reason)
            return result

        # 5. Sentiment flip
        if current_sentiment is not None:
            sent_hit, sent_reason = self.check_sentiment_flip(pos, current_sentiment)
            if sent_hit:
                result.update(should_exit=True, exit_qty=pos.quantity_remaining, exit_reason=sent_reason)
                return result

        return result
