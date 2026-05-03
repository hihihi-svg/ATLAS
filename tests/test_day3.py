"""
ATLAS Day 3 Smoke Test
Tests: Execution Engine + Circuit Breakers + Stop Manager
Simulates a complete trade lifecycle without real money.
"""

import sys
from datetime import datetime, timezone, timedelta

# ── Circuit Breaker Tests ─────────────────────────────────────────────────────
from core.execution import circuit_breakers as cb
from core.execution.stop_manager import Position, StopManager
from core.execution.execution_engine import PaperExecutionEngine
from core.agents.judge import TradeSignal


def make_dummy_signal(
    direction="LONG", confidence=7.5, decision="EXECUTE",
    price=2300.0, stop=2275.0, t1=2350.0, t2=2400.0, size_usd=500.0
) -> TradeSignal:
    return TradeSignal(
        symbol="ETH/USD", direction=direction,
        entry_price=price, stop_loss=stop, target_1=t1, target_2=t2,
        position_size_usd=size_usd, position_size_units=size_usd/price,
        confidence=confidence, decision=decision, size_multiplier=1.0,
        strategy_dna="momentum", regime="bull", active_policy="A",
        rl_vote=7.0, analyst_score=7.5, tech_score=8.0, risk_score=7.0,
        contrarian_penalty=0.5, concerns=[],
        reasoning_summary="Test signal",
        agent_votes={}
    )


def test_circuit_breakers():
    print("\n[TEST 1] Circuit Breakers")
    print("-" * 50)

    # Reset to clean state
    cb.reset_daily()
    assert cb.can_trade() == (True, "OK"), "Should allow trading initially"
    print("  OK: Initial state allows trading")

    # Test consecutive loss reduction
    cb.record_trade_result(-50.0, "ETH/USD")
    cb.record_trade_result(-50.0, "ETH/USD")
    cb.record_trade_result(-60.0, "ETH/USD")   # 3rd consecutive loss
    state = cb.get_state()
    assert state.reduced_size_trades == 5, f"Should have 5 reduced-size trades, got {state.reduced_size_trades}"
    assert cb.get_size_multiplier() == 0.50, f"Should be 50% size, got {cb.get_size_multiplier()}"
    print(f"  OK: 3 consecutive losses -> 50% size for next 5 trades")

    # Record a win — resets streak
    cb.record_trade_result(+200.0, "ETH/USD")
    assert cb.get_state().consecutive_losses == 0, "Win should reset consecutive loss counter"
    print(f"  OK: Win resets consecutive loss counter")

    # Test daily loss halt
    cb.reset_daily()
    cb.record_trade_result(-600.0, "ETH/USD")   # 6% of $10k capital = triggers 5% limit
    assert cb.get_state().trading_halted == True, "Should halt after 6% daily loss"
    allowed, reason = cb.can_trade()
    assert not allowed, f"Should not allow trading after daily halt"
    print(f"  OK: Daily loss limit triggered halt -> '{reason[:50]}'")

    # Test VIX spike
    cb.reset_daily()
    cb.update_vix(35.0)
    assert cb.get_size_multiplier() == 0.25, f"VIX>30 should give 25% size"
    print(f"  OK: VIX=35 -> 25% position size multiplier")

    # Test abnormal order size
    valid, reason = cb.validate_order_size(60000, 1000)  # 60x normal
    assert not valid, "Should block 60x normal order"
    print(f"  OK: Abnormal order size blocked -> '{reason[:50]}'")

    # Test flash crash halt
    cb.reset_daily()
    cb.trigger_flash_crash(0.04)   # 4% drop
    assert cb.get_state().flash_crash_halt == True
    assert not cb.can_trade()[0], "Should halt on flash crash"
    print(f"  OK: Flash crash (4% drop) triggers emergency halt")

    # Manual resume
    cb.manual_resume("Test admin override")
    assert cb.can_trade() == (True, "OK"), "Should allow trading after manual resume"
    print(f"  OK: Admin manual resume works")

    print("  CIRCUIT BREAKERS: ALL PASSED")


def test_stop_manager():
    print("\n[TEST 2] Stop Manager — Trade Lifecycle")
    print("-" * 50)

    mgr = StopManager()
    entry = 2300.0
    atr   = 15.0
    stop  = entry - (1.5 * atr)   # 2277.5
    t1    = entry + (2.0 * atr)   # 2330.0
    t2    = entry + (3.5 * atr)   # 2352.5

    pos = Position(
        symbol="ETH/USD", direction="LONG",
        entry_price=entry, initial_stop=stop, current_stop=stop,
        target_1=t1, target_2=t2,
        quantity=1.0, atr_at_entry=atr,
        max_hold_hours=4.0, entry_sentiment=0.2
    )

    # Price rises — trailing stop should move
    result = mgr.full_check(pos, 2320.0)
    assert not result["should_exit"], "Should not exit at 2320"
    assert pos.current_stop > stop, f"Trailing stop should have moved up from {stop:.2f}"
    print(f"  OK: Price 2320 -> trailing stop moved to {pos.current_stop:.2f}")

    # Price hits T1
    result = mgr.full_check(pos, t1 + 1)
    assert result["partial_exit"], "T1 hit should trigger partial exit"
    assert result["exit_qty"] == 0.5, f"Should close 50%, got {result['exit_qty']}"
    assert pos.target_1_hit == True
    assert pos.break_even_triggered == True
    print(f"  OK: T1 hit at {t1:.2f} -> 50% closed, stop moved to entry")

    # Price hits T2
    result = mgr.full_check(pos, t2 + 1)
    assert result["should_exit"], "T2 hit should trigger full exit"
    assert result["exit_reason"] == "target_2"
    print(f"  OK: T2 hit at {t2:.2f} -> remaining 50% closed")

    # Test time stop (backdate entry)
    pos2 = Position(
        symbol="ETH/USD", direction="LONG",
        entry_price=entry, initial_stop=stop, current_stop=stop,
        target_1=t1, target_2=t2, quantity=1.0, atr_at_entry=atr,
        max_hold_hours=0.001,   # Very short — will expire immediately
        entry_time=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    result = mgr.full_check(pos2, entry + 1)  # Price barely moved
    assert result["should_exit"], "Time stop should trigger"
    print(f"  OK: Time stop triggered after max hold time")

    # Test sentiment flip exit
    pos3 = Position(
        symbol="ETH/USD", direction="LONG",
        entry_price=entry, initial_stop=stop, current_stop=stop,
        target_1=t1, target_2=t2, quantity=1.0, atr_at_entry=atr,
        entry_sentiment=0.6
    )
    result = mgr.full_check(pos3, entry + 5, current_sentiment=-0.1)  # Dropped 0.7
    assert result["should_exit"], "Sentiment flip should trigger exit"
    assert "sentiment" in result["exit_reason"].lower()
    print(f"  OK: Sentiment flip (0.6 -> -0.1) triggers exit")

    print("  STOP MANAGER: ALL PASSED")


def test_execution_engine():
    print("\n[TEST 3] Paper Execution Engine")
    print("-" * 50)

    cb.reset_daily()
    cb.update_vix(15.0)  # Normal VIX

    engine = PaperExecutionEngine()
    price  = engine._get_current_price()
    
    if not price:
        print("  SKIP: Cannot fetch live ETH price (network). Skipping execution test.")
        return

    print(f"  Live ETH price: ${price:,.2f}")

    # Build signal based on live price
    stop = price * 0.99
    t1   = price * 1.01
    t2   = price * 1.02
    signal = make_dummy_signal(price=price, stop=stop, t1=t1, t2=t2, size_usd=200.0)

    # Place paper trade
    receipt = engine.place_trade(signal, sentiment=0.3)
    assert receipt["status"] == "OPENED", f"Expected OPENED, got {receipt['status']}"
    print(f"  OK: Paper trade opened @ ${receipt['fill_price']:,.2f}")
    print(f"      Size: ${receipt['position_usd']:.2f} | Qty: {receipt['quantity']:.4f} ETH")
    print(f"      Stop: ${receipt['stop_loss']:.2f} | T1: ${receipt['target_1']:.2f}")

    # Portfolio status
    status = engine.portfolio_status()
    assert status["open_positions"] == 1
    print(f"  OK: Portfolio shows 1 open position | Unrealized: ${status['unrealized_pnl']:+.2f}")

    # Test circuit breaker blocks while halted
    cb.get_state().trading_halted = True
    cb.get_state().halt_reason = "Test halt"
    blocked = engine.place_trade(signal)
    assert blocked["status"] == "BLOCKED"
    print(f"  OK: Circuit breaker correctly blocks new trade while halted")
    cb.manual_resume()

    # Close all positions
    engine.close_all("test_exitall")
    assert len(engine.open_positions) == 0
    print(f"  OK: /exitall closes all positions")
    print(f"  OK: Trade PnL recorded: ${engine.trade_log[-1]['pnl_usd']:+.4f}")

    print("  EXECUTION ENGINE: ALL PASSED")


def run_all():
    print("\n" + "="*60)
    print("  ATLAS Day 3 Smoke Test — Execution + Risk")
    print("="*60)

    test_circuit_breakers()
    test_stop_manager()
    test_execution_engine()

    print("\n" + "="*60)
    print("  Day 3 Smoke Test PASSED")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_all()
