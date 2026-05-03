"""
ATLAS Day 5 Smoke Test
Tests: HERMES memory agent, post-mortem, DNA weight evolution, memory persistence.
"""

import asyncio
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Use test memory dir to avoid polluting production memory
os.environ["MEMORY_DIR"] = "memory_test"


async def test_hermes():
    from core.memory.hermes import HERMESAgent, StrategyDNA_Weights

    print("\n" + "="*60)
    print("  ATLAS Day 5 Smoke Test — HERMES Memory Agent")
    print("="*60)

    agent = HERMESAgent()

    # ── Mock trade log ─────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    trade_log = [
        {"symbol":"ETH/USD","direction":"LONG","entry_price":2264.0,"exit_price":2291.0,
         "quantity":0.22,"pnl_usd":142.50,"exit_reason":"target_1","closed_at":(now-timedelta(hours=5)).isoformat()},
        {"symbol":"ETH/USD","direction":"LONG","entry_price":2240.0,"exit_price":2258.0,
         "quantity":0.19,"pnl_usd":87.30,"exit_reason":"target_1","closed_at":(now-timedelta(hours=3.5)).isoformat()},
        {"symbol":"ETH/USD","direction":"SHORT","entry_price":2270.0,"exit_price":2282.0,
         "quantity":0.18,"pnl_usd":-45.0,"exit_reason":"trailing_stop","closed_at":(now-timedelta(hours=2)).isoformat()},
        {"symbol":"ETH/USD","direction":"LONG","entry_price":2255.0,"exit_price":2298.0,
         "quantity":0.20,"pnl_usd":210.75,"exit_reason":"target_2","closed_at":(now-timedelta(hours=0.8)).isoformat()},
    ]

    signal_history = [
        {"symbol":"ETH/USD","direction":"LONG","decision":"EXECUTE","confidence":7.82,"strategy":"momentum","regime":"bull","price":2264.0,"ts":(now-timedelta(hours=5)).isoformat()},
        {"symbol":"ETH/USD","direction":"LONG","decision":"EXECUTE","confidence":8.10,"strategy":"momentum","regime":"bull","price":2240.0,"ts":(now-timedelta(hours=4)).isoformat()},
        {"symbol":"ETH/USD","direction":"SHORT","decision":"EXECUTE","confidence":6.80,"strategy":"mean_reversion","regime":"chop","price":2270.0,"ts":(now-timedelta(hours=2.5)).isoformat()},
        {"symbol":"ETH/USD","direction":"LONG","decision":"EXECUTE","confidence":7.50,"strategy":"sentiment","regime":"bull","price":2255.0,"ts":(now-timedelta(hours=1)).isoformat()},
        {"symbol":"ETH/USD","direction":"NONE","decision":"SKIP","confidence":5.65,"strategy":"none","regime":"chop","price":2262.0,"ts":(now-timedelta(hours=3)).isoformat()},
    ]

    print("\n[1/5] Running post-mortem analysis...")
    mem = await agent.run_post_mortem(trade_log, signal_history)
    assert mem.total_trades == 4, f"Expected 4 trades, got {mem.total_trades}"
    assert mem.wins == 3
    assert mem.losses == 1
    assert abs(mem.total_pnl - 395.55) < 0.01, f"PnL mismatch: {mem.total_pnl}"
    assert abs(mem.win_rate - 0.75) < 0.01
    print(f"  OK: {mem.total_trades} trades | {mem.wins}W/{mem.losses}L | WR={mem.win_rate:.0%} | PnL=${mem.total_pnl:+.2f}")
    print(f"  OK: Grade = {mem.lessons.get('performance_grade','?')}")
    print(f"  OK: Top insight: {mem.lessons.get('top_insight','')[:80]}")

    print("\n[2/5] Testing DNA weight evolution...")
    w_before = agent.dna_weights.momentum
    # Simulate 5 momentum trades with 80% win rate → should increase
    agent.dna_weights.update("momentum", 0.80, 5)
    w_after = agent.dna_weights.momentum
    assert w_after > w_before, f"Weight should increase: {w_before:.3f} → {w_after:.3f}"
    print(f"  OK: momentum weight {w_before:.3f} → {w_after:.3f} (80% WR → +10%)")

    agent.dna_weights.update("mean_reversion", 0.30, 5)
    w_mr = agent.dna_weights.mean_reversion
    assert w_mr < 1.0, f"mean_reversion weight should decrease: {w_mr:.3f}"
    print(f"  OK: mean_reversion weight decreased (30% WR → -10%): {w_mr:.3f}")

    # Cap test
    for _ in range(20):
        agent.dna_weights.update("momentum", 1.0, 5)
    assert agent.dna_weights.momentum <= 1.5, f"Weight should cap at 1.5: {agent.dna_weights.momentum}"
    print(f"  OK: Weight cap at 1.5x respected: {agent.dna_weights.momentum:.3f}")

    # Floor test
    for _ in range(20):
        agent.dna_weights.update("mean_reversion", 0.0, 5)
    assert agent.dna_weights.mean_reversion >= 0.5, f"Weight floor at 0.5: {agent.dna_weights.mean_reversion}"
    print(f"  OK: Weight floor at 0.5x respected: {agent.dna_weights.mean_reversion:.3f}")

    print("\n[3/5] Testing memory persistence...")
    agent._save_dna_weights()
    assert Path("memory_test/dna_weights.json").exists()
    loaded = json.loads(Path("memory_test/dna_weights.json").read_text())
    assert "momentum" in loaded
    print(f"  OK: DNA weights saved to disk: {loaded}")

    mem_path = Path(f"memory_test/memory_{mem.date}.json")
    assert mem_path.exists(), f"Memory file not found: {mem_path}"
    loaded_mem = json.loads(mem_path.read_text())
    assert loaded_mem["total_pnl"] == 395.55
    assert loaded_mem["wins"] == 3
    print(f"  OK: Day memory saved ({mem_path.stat().st_size} bytes)")

    print("\n[4/5] Testing memory reload...")
    agent2 = HERMESAgent()
    assert agent2.dna_weights.momentum == agent.dna_weights.momentum
    print(f"  OK: DNA weights reloaded from disk correctly")

    retrieved = agent2.load_memory(mem.date)
    assert retrieved is not None
    assert retrieved["total_trades"] == 4
    print(f"  OK: Day memory reloaded: {retrieved['date']} | {retrieved['total_trades']} trades")

    all_mems = agent2.get_all_memories()
    assert len(all_mems) >= 1
    print(f"  OK: get_all_memories() returns {len(all_mems)} day(s)")

    print("\n[5/5] Testing morning briefing...")
    assert len(mem.morning_briefing) > 50
    print(f"  OK: Morning briefing generated ({len(mem.morning_briefing)} chars)")
    print(f"  Preview:\n{mem.morning_briefing[:200]}")

    print("\n" + "="*60)
    print("  Day 5 Smoke Test PASSED")
    print("="*60 + "\n")

    # Cleanup test dir
    shutil.rmtree("memory_test", ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(test_hermes())
