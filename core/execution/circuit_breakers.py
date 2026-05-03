"""
ATLAS Circuit Breakers
Hard-coded safety rules. CANNOT be overridden by any agent or config.
Blueprint §8.2 — all 8 circuit breakers implemented.

These are the LAST LINE OF DEFENSE before real money is at risk.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, date
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

CAPITAL_USD = float(os.getenv("CAPITAL_USD", "10000"))

# ── Thresholds (hard-coded, NOT from .env) ────────────────────────────────────
DAILY_LOSS_LIMIT_PCT    = 0.05    # 5% → halt rest of day
WEEKLY_LOSS_LIMIT_PCT   = 0.10    # 10% → halt rest of week, need manual restart
SINGLE_TRADE_ALERT_PCT  = 0.02    # 2% single trade loss → alert
CONSECUTIVE_LOSS_LIMIT  = 3       # 3 losses → 50% size for next 5 trades
CONSECUTIVE_HALT_LIMIT  = 5       # 5 losses → full halt + review
MAX_ORDER_SIZE_MULT     = 5.0     # >5x normal → block + alert
VIX_CAUTION_LEVEL       = 20      # VIX > 20 → reduce sizes
VIX_REDUCE_LEVEL        = 30      # VIX > 30 → 25% size
FLASH_CRASH_PCT         = 0.03    # 3% drop in 5 min → emergency halt


@dataclass
class CircuitBreakerState:
    """Mutable state tracking — persists across trade decisions."""
    # Daily state
    daily_pnl_usd:      float = 0.0
    daily_date:         date  = field(default_factory=date.today)
    trading_halted:     bool  = False
    halt_reason:        str   = ""

    # Weekly state
    weekly_pnl_usd:     float = 0.0
    weekly_halt:        bool  = False

    # Consecutive loss tracking
    consecutive_losses: int   = 0
    reduced_size_trades: int  = 0   # remaining trades at 50% size

    # VIX state
    current_vix:        float = 15.0
    vix_override_mult:  float = 1.0  # 1.0 normal, 0.25 if VIX > 30

    # Flash crash
    flash_crash_halt:   bool  = False

    # Stats
    total_trades_today: int   = 0
    wins_today:         int   = 0
    losses_today:       int   = 0


# Global singleton state — one instance for the whole session
_state = CircuitBreakerState()


def get_state() -> CircuitBreakerState:
    return _state


def reset_daily(new_date: date = None):
    """Call at start of each trading day (from CoPAW 9:00 AM cron)."""
    global _state
    _state.daily_pnl_usd    = 0.0
    _state.daily_date       = new_date or date.today()
    _state.trading_halted   = False
    _state.halt_reason      = ""
    _state.flash_crash_halt = False
    _state.total_trades_today = 0
    _state.wins_today       = 0
    _state.losses_today     = 0
    logger.info("[CircuitBreaker] Daily state reset.")


def can_trade() -> tuple[bool, str]:
    """
    Master gate — call BEFORE placing any order.
    Returns (allowed: bool, reason: str).
    """
    s = _state

    # Daily reset check
    if s.daily_date != date.today():
        reset_daily()

    if s.weekly_halt:
        return False, "Weekly loss limit hit. Manual restart required."
    if s.trading_halted:
        return False, f"Trading halted: {s.halt_reason}"
    if s.flash_crash_halt:
        return False, "Flash crash detected. Emergency halt active."

    return True, "OK"


def get_size_multiplier() -> float:
    """
    Returns current position size multiplier based on circuit state.
    1.0 = normal, 0.5 = reduced (3 consecutive losses), 0.25 = VIX spike.
    """
    s = _state
    mult = 1.0

    # VIX-based reduction (lower priority, can stack)
    mult *= s.vix_override_mult

    # Consecutive loss reduction (overrides if more restrictive)
    if s.reduced_size_trades > 0:
        mult = min(mult, 0.50)

    return mult


def record_trade_result(pnl_usd: float, symbol: str = "") -> dict:
    """
    Call after every trade closes.
    Updates state and triggers circuit breakers if needed.
    Returns dict of any triggered alerts.
    """
    global _state
    s = _state
    alerts = []

    # Daily reset check
    if s.daily_date != date.today():
        reset_daily()

    s.daily_pnl_usd  += pnl_usd
    s.weekly_pnl_usd += pnl_usd
    s.total_trades_today += 1

    if pnl_usd >= 0:
        s.wins_today += 1
        s.consecutive_losses = 0
        if s.reduced_size_trades > 0:
            s.reduced_size_trades -= 1
    else:
        s.losses_today += 1
        s.consecutive_losses += 1

        # ── CB1: Single trade loss alert ────────────────────────────────────
        loss_pct = abs(pnl_usd) / CAPITAL_USD
        if loss_pct >= SINGLE_TRADE_ALERT_PCT:
            msg = f"CB-ALERT: Single trade loss ${abs(pnl_usd):.2f} ({loss_pct*100:.1f}%) on {symbol}"
            logger.warning(f"[CircuitBreaker] {msg}")
            alerts.append({"type": "single_loss_alert", "msg": msg})

        # ── CB2: Consecutive loss reduction ──────────────────────────────────
        if s.consecutive_losses >= CONSECUTIVE_HALT_LIMIT:
            s.trading_halted = True
            s.halt_reason = f"5 consecutive losses. Full halt — manual review required."
            logger.error(f"[CircuitBreaker] FULL HALT: {s.halt_reason}")
            alerts.append({"type": "halt", "msg": s.halt_reason})

        elif s.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
            s.reduced_size_trades = 5
            msg = f"CB: 3 consecutive losses. Position size cut 50% for next 5 trades."
            logger.warning(f"[CircuitBreaker] {msg}")
            alerts.append({"type": "size_reduction", "msg": msg})

    # ── CB3: Daily loss limit ────────────────────────────────────────────────
    daily_loss_pct = abs(s.daily_pnl_usd) / CAPITAL_USD
    if s.daily_pnl_usd < 0 and daily_loss_pct >= DAILY_LOSS_LIMIT_PCT:
        s.trading_halted = True
        s.halt_reason = f"Daily loss limit hit: ${abs(s.daily_pnl_usd):.2f} ({daily_loss_pct*100:.1f}% of capital)"
        logger.error(f"[CircuitBreaker] DAILY HALT: {s.halt_reason}")
        alerts.append({"type": "daily_halt", "msg": s.halt_reason})

    # ── CB4: Weekly loss limit ────────────────────────────────────────────────
    weekly_loss_pct = abs(s.weekly_pnl_usd) / CAPITAL_USD
    if s.weekly_pnl_usd < 0 and weekly_loss_pct >= WEEKLY_LOSS_LIMIT_PCT:
        s.weekly_halt = True
        msg = f"Weekly loss limit hit: ${abs(s.weekly_pnl_usd):.2f} ({weekly_loss_pct*100:.1f}%)"
        logger.error(f"[CircuitBreaker] WEEKLY HALT: {msg}")
        alerts.append({"type": "weekly_halt", "msg": msg})

    logger.info(
        f"[CircuitBreaker] Trade recorded: PnL=${pnl_usd:+.2f} | "
        f"Daily={s.daily_pnl_usd:+.2f} | ConsecLosses={s.consecutive_losses} | "
        f"SizeReduction={'YES' if s.reduced_size_trades>0 else 'NO'}"
    )

    return {"alerts": alerts, "state": s}


def update_vix(vix_value: float):
    """Update VIX level and set size multiplier accordingly."""
    global _state
    _state.current_vix = vix_value

    if vix_value > VIX_REDUCE_LEVEL:
        _state.vix_override_mult = 0.25
        logger.warning(f"[CircuitBreaker] VIX={vix_value:.1f} > {VIX_REDUCE_LEVEL} → 25% position sizes")
    elif vix_value > VIX_CAUTION_LEVEL:
        _state.vix_override_mult = 0.75
        logger.info(f"[CircuitBreaker] VIX={vix_value:.1f} > {VIX_CAUTION_LEVEL} → 75% position sizes")
    else:
        _state.vix_override_mult = 1.0


def trigger_flash_crash(drop_pct: float):
    """Call when index drops >3% in 5 minutes."""
    global _state
    if drop_pct >= FLASH_CRASH_PCT:
        _state.flash_crash_halt = True
        logger.error(f"[CircuitBreaker] FLASH CRASH DETECTED: {drop_pct*100:.1f}% drop. Emergency halt.")


def manual_resume(reason: str = "Admin manual resume"):
    """Admin override — re-enables trading after halt."""
    global _state
    _state.trading_halted   = False
    _state.halt_reason      = ""
    _state.flash_crash_halt = False
    logger.info(f"[CircuitBreaker] Trading RESUMED by admin: {reason}")


def validate_order_size(order_usd: float, normal_size_usd: float) -> tuple[bool, str]:
    """CB: Abnormal order size check — blocks if >5x normal."""
    ratio = order_usd / normal_size_usd if normal_size_usd > 0 else 999
    if ratio > MAX_ORDER_SIZE_MULT:
        msg = f"BLOCKED: Order ${order_usd:.0f} is {ratio:.1f}x normal ${normal_size_usd:.0f} (limit {MAX_ORDER_SIZE_MULT}x)"
        logger.error(f"[CircuitBreaker] {msg}")
        return False, msg
    return True, "OK"


def status_summary() -> dict:
    """Return current circuit breaker status for dashboard."""
    s = _state
    allowed, reason = can_trade()
    return {
        "can_trade":         allowed,
        "halt_reason":       reason,
        "daily_pnl_usd":     s.daily_pnl_usd,
        "daily_pnl_pct":     s.daily_pnl_usd / CAPITAL_USD,
        "weekly_pnl_usd":    s.weekly_pnl_usd,
        "consecutive_losses":s.consecutive_losses,
        "size_multiplier":   get_size_multiplier(),
        "vix":               s.current_vix,
        "vix_mult":          s.vix_override_mult,
        "reduced_size_trades":s.reduced_size_trades,
        "trades_today":      s.total_trades_today,
        "wins_today":        s.wins_today,
        "losses_today":      s.losses_today,
    }
