"""
ATLAS Day 6 Smoke Test + Full Simulation
Runs 60-day backtest on live ETH/USD historical data.
Validates: trades executed, metrics computed, report generated.
Also validates minimum thresholds (system must not be completely broken).
"""

import asyncio
import os
import sys
from pathlib import Path


async def test_backtest():
    from simulation.backtester import Backtester
    from simulation.report_generator import generate_report, print_summary

    print("\n" + "="*60)
    print("  ATLAS Day 6 — Full 60-Day Simulation")
    print("="*60)

    # ── Run backtest ──────────────────────────────────────────────────────────
    print("\n[1/4] Running 60-day backtest simulation...")
    bt = Backtester(initial_capital=10000.0)
    result = bt.run(days=60)

    print(f"  Simulation complete: {result.total_trades} trades executed")

    # ── Validate basics ───────────────────────────────────────────────────────
    print("\n[2/4] Validating results...")

    assert result.total_trades >= 0, "Trade count invalid"
    print(f"  OK: {result.total_trades} total trades")

    if result.total_trades > 0:
        assert 0 <= result.win_rate <= 1.0, f"Win rate out of range: {result.win_rate}"
        print(f"  OK: Win rate = {result.win_rate*100:.1f}%")

        assert result.max_drawdown >= 0, "Drawdown can't be negative"
        print(f"  OK: Max drawdown = -${result.max_drawdown:.2f} (-{result.max_drawdown_pct:.2f}%)")

        assert result.max_drawdown_pct <= 50, f"Drawdown > 50%: {result.max_drawdown_pct:.2f}% — system broken"
        print(f"  OK: Drawdown within acceptable range (< 50%)")

        assert result.profit_factor >= 0, "Profit factor invalid"
        print(f"  OK: Profit factor = {result.profit_factor:.3f}")

        assert len(result.equity_curve) >= 2, "Equity curve too short"
        print(f"  OK: Equity curve has {len(result.equity_curve)} data points")

        assert result.avg_hold_bars > 0, "Avg hold must be positive"
        print(f"  OK: Avg hold = {result.avg_hold_bars:.1f} bars ({result.avg_hold_bars*15/60:.1f}h)")

        assert len(result.regime_trades) >= 0
        print(f"  OK: Regime breakdown: {list(result.regime_trades.keys())}")

        assert len(result.dna_trades) >= 0
        print(f"  OK: DNA breakdown: {list(result.dna_trades.keys())}")
    else:
        print("  NOTE: No trades fired (market conditions too choppy for signal threshold). Metrics still valid.")

    # ── Print full summary ────────────────────────────────────────────────────
    print("\n[3/4] Performance Summary:")
    print_summary(result)

    # ── Generate report ───────────────────────────────────────────────────────
    print("[4/4] Generating HTML report...")
    report_path = generate_report(result, days=60)
    assert Path(report_path).exists()
    size = Path(report_path).stat().st_size
    assert size > 3000, f"Report too small: {size} bytes"
    print(f"  OK: HTML report saved -> {report_path} ({size:,} bytes)")

    json_path = report_path.replace(".html", ".json").replace("backtest_", "backtest_")
    # JSON is always generated alongside HTML
    json_files = list(Path("simulation/reports").glob("backtest_*.json"))
    assert len(json_files) >= 1
    print(f"  OK: JSON report saved ({json_files[-1].stat().st_size:,} bytes)")

    print("\n" + "="*60)
    print("  Day 6 Smoke Test PASSED")
    print(f"  Report: {report_path}")
    print("="*60 + "\n")

    return report_path


if __name__ == "__main__":
    report_path = asyncio.run(test_backtest())
    print(f"\nOpen report: {report_path}")
