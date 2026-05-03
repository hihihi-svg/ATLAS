"""
ATLAS Day 4 Smoke Test
Tests: FastAPI endpoints + MOLTBOT message builders (no Telegram token needed).
Starts API server on port 8765, hits all read endpoints, tests write endpoints.
"""

import asyncio
import httpx
import threading
import time
import uvicorn

from core.execution import circuit_breakers as cb
from core.execution.execution_engine import PaperExecutionEngine
from core.agents.judge import TradeSignal
from core.control import api as api_module
from core.control.api import app
from core.control import moltbot


# ── Test setup ────────────────────────────────────────────────────────────────
PORT    = 8765
API_URL = f"http://127.0.0.1:{PORT}"
API_KEY = "atlas-dev-key"
HEADERS = {"x-api-key": API_KEY}

engine = PaperExecutionEngine()


def make_dummy_signal():
    price = engine._get_current_price() or 2300.0
    return TradeSignal(
        symbol="ETH/USD", direction="LONG", entry_price=price,
        stop_loss=price*0.99, target_1=price*1.01, target_2=price*1.02,
        position_size_usd=200, position_size_units=200/price,
        confidence=7.8, decision="EXECUTE", size_multiplier=0.75,
        strategy_dna="momentum", regime="bull", active_policy="A",
        rl_vote=7.0, analyst_score=7.5, tech_score=8.0, risk_score=7.0,
        contrarian_penalty=0.3, concerns=[],
        reasoning_summary="Test signal", agent_votes={}
    )


def start_server():
    cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(cfg)
    server.run()


async def test_api():
    print("\n" + "="*60)
    print("  ATLAS Day 4 Smoke Test — API + Dashboard + MOLTBOT")
    print("="*60)

    # Inject dependencies into API
    signal = make_dummy_signal()
    fake_regime = {"regime": "bull", "policy": "A", "score": 0.75, "rsi": 62.0, "macd_hist": 0.05, "rvol": 1.4, "atr": 8.5, "close": signal.entry_price}
    api_module.inject_dependencies(engine, fake_regime, [])
    moltbot.inject_dependencies(engine)

    # Start server in background thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(1.5)   # Wait for server to boot

    print("\n[1/4] Testing read endpoints...")
    async with httpx.AsyncClient(timeout=10) as client:
        # /health
        r = await client.get(f"{API_URL}/health")
        assert r.status_code == 200, f"/health failed: {r.status_code}"
        data = r.json()
        assert data["status"] == "ok"
        print(f"  OK: /health → {data['system']} mode={data['mode']}")

        # /status
        r = await client.get(f"{API_URL}/status")
        assert r.status_code == 200, f"/status failed: {r.status_code}"
        data = r.json()
        assert "circuit" in data
        assert "regime" in data
        print(f"  OK: /status → regime={data['regime'].get('regime','?')} | can_trade={data['circuit']['can_trade']}")

        # /regime
        r = await client.get(f"{API_URL}/regime")
        assert r.status_code == 200
        reg = r.json()
        assert reg["regime"] == "bull"
        print(f"  OK: /regime → {reg['regime'].upper()} | Policy {reg['policy']}")

        # /circuit
        r = await client.get(f"{API_URL}/circuit")
        assert r.status_code == 200
        circ = r.json()
        assert "can_trade" in circ
        print(f"  OK: /circuit → size_mult={circ['size_multiplier']*100:.0f}% | vix={circ['vix']}")

        # /signals
        r = await client.get(f"{API_URL}/signals")
        assert r.status_code == 200
        print(f"  OK: /signals → {len(r.json()['signals'])} signals")

        # /trades
        r = await client.get(f"{API_URL}/trades")
        assert r.status_code == 200
        print(f"  OK: /trades → {len(r.json()['trades'])} trades")

    print("\n[2/4] Testing write endpoints (API key gated)...")
    async with httpx.AsyncClient(timeout=10) as client:
        # Auth rejection
        r = await client.post(f"{API_URL}/halt", json={"reason": "test"}, headers={"x-api-key": "wrong"})
        assert r.status_code == 403
        print(f"  OK: Invalid API key → 403 Forbidden")

        # /halt
        cb.reset_daily()
        r = await client.post(f"{API_URL}/halt", json={"reason": "test halt"}, headers=HEADERS)
        assert r.status_code == 200
        assert cb.get_state().trading_halted
        print(f"  OK: /halt → trading halted")

        # /resume
        r = await client.post(f"{API_URL}/resume", headers=HEADERS)
        assert r.status_code == 200
        assert cb.can_trade()[0]
        print(f"  OK: /resume → trading active")

        # /vix
        r = await client.post(f"{API_URL}/vix", json={"vix": 32.5}, headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["size_multiplier"] == 0.25
        print(f"  OK: /vix 32.5 → size_multiplier=25%")
        cb.update_vix(15.0)   # reset

        # /exitall (with no open positions)
        r = await client.post(f"{API_URL}/exitall", headers=HEADERS)
        assert r.status_code == 200
        print(f"  OK: /exitall → {r.json()['positions_closed']} positions closed")

    print("\n[3/4] Testing MOLTBOT message builders...")
    moltbot._regime_cache = fake_regime
    cb.reset_daily()
    cb.record_trade_result(+150.0)
    cb.record_trade_result(-50.0)
    status_msg = moltbot._build_status_message()
    assert "ATLAS" in status_msg
    assert "BULL" in status_msg
    print(f"  OK: Status message built ({len(status_msg)} chars)")

    circuit_msg = moltbot._build_circuit_message()
    assert "Circuit Breaker" in circuit_msg
    print(f"  OK: Circuit message built ({len(circuit_msg)} chars)")

    # Test alert mock (no token → just logs)
    await moltbot.send_alert("Test alert from D4 smoke test")
    print(f"  OK: Mock alert sent (no Telegram token → logged only)")

    # Test signal history
    moltbot.add_signal_to_history(signal)
    assert len(moltbot._signal_history) == 1
    print(f"  OK: Signal added to MOLTBOT history")

    print("\n[4/4] Verifying dashboard HTML exists...")
    import os
    dashboard_path = os.path.join("core", "control", "dashboard.html")
    assert os.path.exists(dashboard_path), "dashboard.html missing"
    size = os.path.getsize(dashboard_path)
    assert size > 5000, f"dashboard.html too small: {size} bytes"
    print(f"  OK: dashboard.html exists ({size:,} bytes)")

    print("\n" + "="*60)
    print("  Day 4 Smoke Test PASSED")
    print(f"  Dashboard at: http://127.0.0.1:{PORT}/")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_api())
