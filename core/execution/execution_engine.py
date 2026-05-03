"""
ATLAS Paper Trading Execution Engine
Simulates OCO (One-Cancels-Other) order placement and position management.
Paper mode: uses live price from yfinance, zero real money.
Designed to swap to live broker (ccxt) by changing _get_current_price().

OCO structure per blueprint §2.3 Feature 10:
  Order 1: Limit Entry at target price
  Order 2: Stop Loss (market)
  Order 3: Take Profit Limit (T1 = 50%, T2 = remaining 50%)
"""

import asyncio
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from dotenv import load_dotenv

import yfinance as yf

from core.execution.circuit_breakers import (
    can_trade, get_size_multiplier, record_trade_result,
    validate_order_size, status_summary
)
from core.execution.stop_manager import Position, StopManager
from core.agents.judge import TradeSignal

load_dotenv()

SYMBOL      = os.getenv("TRADING_PAIR", "ETH/USDT")
CAPITAL_USD = float(os.getenv("CAPITAL_USD", "10000"))
PAPER_MODE  = os.getenv("PAPER_TRADING", "true").lower() == "true"

YF_TICKER = "ETH-USD"   # Yahoo Finance ticker


@dataclass
class OrderRecord:
    """Log of every order placed."""
    order_id:     str
    symbol:       str
    direction:    str
    order_type:   str       # LIMIT_ENTRY | STOP_LOSS | TAKE_PROFIT
    price:        float
    quantity:     float
    status:       str       # PENDING | FILLED | CANCELLED
    filled_at:    Optional[datetime] = None
    filled_price: Optional[float]    = None
    pnl_usd:      Optional[float]    = None


class PaperExecutionEngine:
    """
    Simulates live trading in paper mode.
    - Tracks open positions in memory
    - Checks stops every poll interval
    - Records full trade log for post-mortem
    """

    def __init__(self):
        self.open_positions: dict[str, Position] = {}   # symbol → Position
        self.order_log:      list[OrderRecord]   = []
        self.trade_log:      list[dict]          = []
        self.stop_manager    = StopManager()
        self._order_counter  = 0
        self._running        = False

    # ── Order Placement ───────────────────────────────────────────────────────

    def place_trade(self, signal: TradeSignal, sentiment: float = 0.0) -> dict:
        """
        Main entry point. Called when Judge says EXECUTE.
        Places OCO structure: Entry + Stop + Target orders.
        Returns trade receipt.
        """
        # ── Circuit breaker gate ──────────────────────────────────────────────
        allowed, reason = can_trade()
        if not allowed:
            logger.warning(f"[Execution] BLOCKED by circuit breaker: {reason}")
            return {"status": "BLOCKED", "reason": reason}

        if signal.decision == "SKIP":
            return {"status": "SKIPPED", "reason": "Below confidence threshold"}

        # ── Apply circuit breaker size multiplier ─────────────────────────────
        cb_mult  = get_size_multiplier()
        sig_mult = signal.size_multiplier
        final_size_usd = signal.position_size_usd * cb_mult

        # ── Validate order size isn't abnormal ────────────────────────────────
        normal_size = CAPITAL_USD * 0.10  # 10% of capital = "normal"
        valid, val_reason = validate_order_size(final_size_usd, normal_size)
        if not valid:
            return {"status": "BLOCKED", "reason": val_reason}

        # ── Paper fill at current live price ─────────────────────────────────
        fill_price = self._get_current_price()
        if not fill_price:
            return {"status": "ERROR", "reason": "Could not get current price"}

        quantity = final_size_usd / fill_price

        # ── Register position ──────────────────────────────────────────────────
        pos = Position(
            symbol          = signal.symbol,
            direction       = signal.direction,
            entry_price     = fill_price,
            initial_stop    = signal.stop_loss,
            current_stop    = signal.stop_loss,
            target_1        = signal.target_1,
            target_2        = signal.target_2,
            quantity        = quantity,
            atr_at_entry    = abs(fill_price - signal.stop_loss) / 1.5,  # Reverse ATR calc
            max_hold_hours  = 4.0,   # Day trade default
            entry_sentiment = sentiment,
        )
        self.open_positions[signal.symbol] = pos

        # ── Log the entry order ───────────────────────────────────────────────
        entry_order = self._make_order(
            signal.symbol, signal.direction, "LIMIT_ENTRY",
            fill_price, quantity, "FILLED", fill_price
        )
        self.order_log.append(entry_order)

        trade_info = {
            "status":          "OPENED",
            "mode":            "PAPER",
            "symbol":          signal.symbol,
            "direction":       signal.direction,
            "fill_price":      fill_price,
            "quantity":        round(quantity, 6),
            "position_usd":    round(final_size_usd, 2),
            "stop_loss":       signal.stop_loss,
            "target_1":        signal.target_1,
            "target_2":        signal.target_2,
            "confidence":      signal.confidence,
            "strategy_dna":    signal.strategy_dna,
            "cb_size_mult":    cb_mult,
            "signal_mult":     sig_mult,
            "opened_at":       datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"[Execution] PAPER TRADE OPENED | {signal.direction} {signal.symbol} | "
            f"${final_size_usd:.0f} @ ${fill_price:,.2f} | "
            f"Stop={signal.stop_loss:.2f} | T1={signal.target_1:.2f} | "
            f"Confidence={signal.confidence:.2f}"
        )

        self.trade_log.append(trade_info)
        return trade_info

    # ── Position Monitoring ───────────────────────────────────────────────────

    async def monitor_loop(self, poll_interval: int = 60):
        """
        Runs every N seconds (60 by default). Checks all open positions
        against current price and stop conditions.
        """
        self._running = True
        logger.info(f"[Execution] Position monitor started (interval={poll_interval}s)")

        while self._running:
            if self.open_positions:
                await self._check_all_positions()
            await asyncio.sleep(poll_interval)

    async def _check_all_positions(self):
        """Check every open position for exit conditions."""
        price = self._get_current_price()
        if not price:
            logger.warning("[Execution] Could not get price for position monitoring.")
            return

        to_close = []
        for symbol, pos in self.open_positions.items():
            result = self.stop_manager.full_check(pos, price)

            if result["break_even"]:
                logger.info(f"[Execution] {symbol}: break-even stop set at {pos.entry_price:.2f}")

            if result["partial_exit"]:
                qty     = result["exit_qty"]
                pnl     = self._calc_pnl(pos, price, qty)
                logger.info(f"[Execution] {symbol}: PARTIAL EXIT (T1) {qty:.4f} units @ ${price:.2f} | PnL=${pnl:+.2f}")
                self._log_exit(pos, price, qty, result["exit_reason"], pnl)

            if result["should_exit"]:
                qty = result["exit_qty"]
                to_close.append((symbol, pos, price, qty, result["exit_reason"]))

        for symbol, pos, price, qty, reason in to_close:
            self._close_position(symbol, pos, price, qty, reason)

    def _close_position(self, symbol: str, pos: Position, price: float, qty: float, reason: str):
        """Close position, record P&L, update circuit breakers."""
        pnl = self._calc_pnl(pos, price, qty)
        self._log_exit(pos, price, qty, reason, pnl)
        record_trade_result(pnl, symbol)
        del self.open_positions[symbol]

        logger.info(
            f"[Execution] PAPER TRADE CLOSED | {symbol} | {reason} | "
            f"PnL=${pnl:+.2f} ({pnl/CAPITAL_USD*100:+.2f}%) | "
            f"Exit=${price:.2f}"
        )

    def close_all(self, reason: str = "manual_exitall"):
        """Close every open position immediately (Telegram /exitall)."""
        price = self._get_current_price()
        if not price:
            logger.error("[Execution] Can't get price for emergency close.")
            return

        symbols = list(self.open_positions.keys())
        for symbol in symbols:
            pos = self.open_positions[symbol]
            self._close_position(symbol, pos, price, pos.quantity_remaining, reason)

        logger.warning(f"[Execution] ALL POSITIONS CLOSED: {reason}")

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _get_current_price(self) -> Optional[float]:
        """Get live price via yfinance. In production, swap for ccxt WebSocket."""
        try:
            ticker = yf.Ticker(YF_TICKER)
            data   = ticker.history(period="1d", interval="1m")
            if data.empty:
                return None
            return float(data["Close"].iloc[-1])
        except Exception as e:
            logger.error(f"[Execution] Price fetch error: {e}")
            return None

    def _calc_pnl(self, pos: Position, exit_price: float, qty: float) -> float:
        if pos.direction == "LONG":
            return (exit_price - pos.entry_price) * qty
        else:
            return (pos.entry_price - exit_price) * qty

    def _make_order(self, symbol, direction, order_type, price, qty, status, fill_price=None) -> OrderRecord:
        self._order_counter += 1
        return OrderRecord(
            order_id     = f"PAPER-{self._order_counter:06d}",
            symbol       = symbol,
            direction    = direction,
            order_type   = order_type,
            price        = price,
            quantity     = qty,
            status       = status,
            filled_at    = datetime.now(timezone.utc) if status == "FILLED" else None,
            filled_price = fill_price,
        )

    def _log_exit(self, pos: Position, price: float, qty: float, reason: str, pnl: float):
        self.trade_log.append({
            "symbol":      pos.symbol,
            "direction":   pos.direction,
            "entry_price": pos.entry_price,
            "exit_price":  price,
            "quantity":    qty,
            "pnl_usd":     round(pnl, 4),
            "pnl_pct":     round(pnl / CAPITAL_USD * 100, 4),
            "exit_reason": reason,
            "closed_at":   datetime.now(timezone.utc).isoformat(),
        })

    def portfolio_status(self) -> dict:
        """Current portfolio snapshot for dashboard."""
        price = self._get_current_price() or 0
        total_unrealized = 0.0
        positions = []

        for sym, pos in self.open_positions.items():
            unrealized = self._calc_pnl(pos, price, pos.quantity_remaining)
            total_unrealized += unrealized
            positions.append({
                "symbol":       sym,
                "direction":    pos.direction,
                "entry":        pos.entry_price,
                "current":      price,
                "qty":          pos.quantity_remaining,
                "unrealized":   round(unrealized, 2),
                "stop":         pos.current_stop,
                "target_1":     pos.target_1,
                "break_even":   pos.break_even_triggered,
            })

        return {
            "open_positions": len(self.open_positions),
            "positions":      positions,
            "unrealized_pnl": round(total_unrealized, 2),
            "circuit_status": status_summary(),
        }
