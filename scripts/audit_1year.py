"""
ATLAS 1-Year Performance Audit
Fetches 365 days of ETH/USD data and runs full-year simulation.
Outputs detailed audit report.
"""

import asyncio
import os
import sys
from pathlib import Path
from loguru import logger

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from simulation.backtester import Backtester
from simulation.report_generator import generate_report, print_summary

async def run_audit():
    print("\n" + "="*60)
    print("  ATLAS 1-YEAR PERFORMANCE AUDIT")
    print("  Target: ETH/USD | Duration: 365 Days")
    print("="*60)

    bt = Backtester(initial_capital=10000.0)
    
    # ── 1. Run Simulation ─────────────────────────────────────────────────────
    print("\n[1/2] Replaying 1 year of market history (1h candles)...")
    
    # Run backtester for 365 days using 1h interval
    result = bt.run(days=365, interval="1h")
    
    print("\n[2/2] Generating Audit Report...")
    print_summary(result)
    
    # Generate HTML report
    report_path = generate_report(result, days=365)
    
    # Rename to Audit Report for clarity
    audit_report_name = "simulation/reports/ATLAS_1YEAR_AUDIT.html"
    if Path(report_path).exists():
        # Ensure directory exists
        Path("simulation/reports").mkdir(parents=True, exist_ok=True)
        # Move/Rename
        if Path(audit_report_name).exists():
            os.remove(audit_report_name)
        os.rename(report_path, audit_report_name)
    
    print("\n" + "="*60)
    print("  AUDIT COMPLETE")
    print(f"  Final Report: {audit_report_name}")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(run_audit())
