"""
ATLAS Live Trading Loop
Runs alongside FastAPI dashboard. Every 30s:
  1. Fetch real ETH/USD price from yfinance
  2. Classify regime
  3. Run 5-agent signal pipeline (real GPT-4o-mini)
  4. Execute / manage positions via paper engine
  5. Inject live state into API for dashboard

Start with:
  python run_live.py
  (opens dashboard at http://localhost:8000)
"""

import asyncio
import os
import threading
import time
import random
import webbrowser
from datetime import datetime, timezone

import uvicorn
import yfinance as yf
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ── Shared state (thread-safe via asyncio.Queue / dict) ──────────────────────
_regime_cache    = {"regime": "unknown", "policy": "?", "score": 0.0}
_signal_history  = []
_execution_engine = None

# ── Imports ───────────────────────────────────────────────────────────────────
from core.control.api import app, inject_dependencies
from core.data.regime_detector import classify_regime
from core.agents.signal_pipeline import evaluate_trade_opportunity
from core.execution.execution_engine import PaperExecutionEngine
from core.execution import circuit_breakers as cb
import ta
import pandas as pd

SYMBOL        = os.getenv("TRADING_PAIR", "ETH/USDT")
LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL_SECONDS", "30"))
MAX_SIGNALS   = 50
VIX_REFRESH_CYCLES = 60   # Refresh VIX every 60 loops ≈ 30 minutes


def fetch_and_apply_vix() -> float:
    """Fetch live VIX from Yahoo Finance and auto-apply to circuit breaker."""
    try:
        vix_df = yf.download("^VIX", period="1d", interval="1h",
                             auto_adjust=True, progress=False)
        if vix_df.empty:
            logger.warning("[VIX] Could not fetch ^VIX — keeping current value")
            return cb.get_state().current_vix
        # Get last close
        close_col = [c for c in vix_df.columns if "close" in str(c).lower()]
        if close_col:
            vix_val = float(vix_df[close_col[0]].iloc[-1])
        else:
            vix_val = float(vix_df.iloc[-1, 0])
        cb.update_vix(vix_val)
        logger.info(f"[VIX] Auto-updated VIX → {vix_val:.2f}")
        return vix_val
    except Exception as e:
        logger.warning(f"[VIX] Fetch failed: {e}")
        return cb.get_state().current_vix


def fetch_market_data() -> dict | None:
    """Fetch latest ETH/USD OHLCV + compute indicators. Returns indicator dict or None."""
    try:
        df = yf.download("ETH-USD", period="5d", interval="15m",
                         auto_adjust=True, progress=False)
        df = df.rename(columns={"Open": "open", "High": "high",
                                 "Low": "low", "Close": "close", "Volume": "volume"})
        df.dropna(inplace=True)

        # Flatten MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        close = df["close"].squeeze()
        high  = df["high"].squeeze()
        low   = df["low"].squeeze()
        vol   = df["volume"].squeeze()

        df["ema9"]      = ta.trend.EMAIndicator(close, 9).ema_indicator()
        df["ema21"]     = ta.trend.EMAIndicator(close, 21).ema_indicator()
        df["ema50"]     = ta.trend.EMAIndicator(close, 50).ema_indicator()
        df["rsi"]       = ta.momentum.RSIIndicator(close, 14).rsi()
        df["atr"]       = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()

        macd = ta.trend.MACD(close)
        df["macd_hist"] = macd.macd_diff()

        bb = ta.volatility.BollingerBands(close, 20, 2)
        df["bb_upper"]  = bb.bollinger_hband()
        df["bb_lower"]  = bb.bollinger_lband()
        df["bb_mid"]    = bb.bollinger_mavg()

        df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
        avg_vol = vol.rolling(20).mean()
        df["rvol"] = vol / avg_vol.where(avg_vol > 0, 1)

        df.dropna(inplace=True)

        if df.empty:
            return None

        row = df.iloc[-1]

        def _f(v):
            if hasattr(v, 'iloc'): return float(v.iloc[0])
            if hasattr(v, 'item'): return float(v.item())
            return float(v)

        return {
            "symbol":    "ETH/USD",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "close":     _f(row["close"]),
            "high":      _f(row["high"]),
            "low":       _f(row["low"]),
            "volume":    _f(row["volume"]),
            "ema9":      _f(row["ema9"]),
            "ema21":     _f(row["ema21"]),
            "ema50":     _f(row["ema50"]),
            "rsi":       _f(row["rsi"]),
            "atr":       _f(row["atr"]),
            "macd_hist": _f(row["macd_hist"]),
            "bb_upper":  _f(row["bb_upper"]),
            "bb_lower":  _f(row["bb_lower"]),
            "bb_mid":    _f(row["bb_mid"]),
            "rvol":      _f(row["rvol"]),
            "vwap":      _f(row["vwap"]),
        }
    except Exception as e:
        logger.error(f"[LiveLoop] Market data fetch failed: {e}")
        return None


async def trading_loop():
    """Main async trading loop — runs every LOOP_INTERVAL seconds."""
    global _regime_cache, _signal_history, _execution_engine

    logger.info(f"[LiveLoop] Starting. Interval={LOOP_INTERVAL}s | Symbol={SYMBOL}")
    logger.info(f"[LiveLoop] Dashboard → http://localhost:8000")

    # Fetch VIX once on startup
    fetch_and_apply_vix()
    vix_cycle_counter = 0

    while True:
        try:
            # ── Auto-refresh VIX every VIX_REFRESH_CYCLES loops (~30min) ──────
            vix_cycle_counter += 1
            if vix_cycle_counter >= VIX_REFRESH_CYCLES:
                fetch_and_apply_vix()
                vix_cycle_counter = 0
            # ── 1. Fetch market data ─────────────────────────────────────────
            logger.info("[LiveLoop] Fetching ETH/USD market data...")
            indicators = fetch_market_data()

            if not indicators:
                logger.warning("[LiveLoop] No market data. Skipping cycle.")
                await asyncio.sleep(LOOP_INTERVAL)
                continue

            price = indicators["close"]
            logger.info(f"[LiveLoop] ETH/USD = ${price:.2f} | RSI={indicators['rsi']:.1f} | RVOL={indicators['rvol']:.2f}")

            # ── 1.5. Monitor open positions (check stops/targets) ────────────
            if _execution_engine and _execution_engine.open_positions:
                await _execution_engine._check_all_positions()

            # ── 2. Classify regime ────────────────────────────────────────────
            regime_str, regime_score = classify_regime(indicators, {})
            from core.data.regime_detector import REGIME_POLICY_MAP
            policy = REGIME_POLICY_MAP.get(regime_str, "C")

            _regime_cache.update({
                "regime":    regime_str,
                "policy":    policy,
                "score":     round(regime_score, 3),
                "rsi":       indicators["rsi"],
                "macd_hist": indicators["macd_hist"],
                "rvol":      indicators["rvol"],
                "atr":       indicators["atr"],
                "close":     price,
                "ema9":      indicators["ema9"],
                "ema21":     indicators["ema21"],
                "ema50":     indicators["ema50"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

            logger.info(f"[LiveLoop] Regime: {regime_str.upper()} (score={regime_score:.2f}) → Policy {policy}")

            # ── 3. Skip if circuit breaker halted ────────────────────────────
            state = cb.get_state()
            if state.trading_halted:
                logger.warning(f"[LiveLoop] Trading HALTED: {state.halt_reason}. Skipping signal evaluation.")
                await asyncio.sleep(LOOP_INTERVAL)
                continue

            # ── 4. Run 5-agent signal pipeline ────────────────────────────────
            open_count = len(_execution_engine.open_positions) if _execution_engine else 0
            logger.info(f"[LiveLoop] Running agent pipeline... (open positions: {open_count})")

            # Dynamic RL confidence based on market conditions
            rsi_val = indicators.get('rsi', 50)
            rvol_val = indicators.get('rvol', 1.0)
            regime_bonus = {'bull': 1.0, 'bear': -0.5, 'chop': 0.0, 'volatile': -0.3, 'crisis': -1.5}
            base_rl = 5.5
            # RSI contribution: 50=neutral, 70=+1.5, 30=-1.5
            rsi_adj = (rsi_val - 50) / 20 * 1.5
            # Volume confirmation
            vol_adj = min(0.5, (rvol_val - 1.0) * 0.5) if rvol_val > 1.0 else -0.3
            # Regime fit
            reg_adj = regime_bonus.get(regime_str, 0)
            
            dynamic_rl = max(1.0, min(9.5, base_rl + rsi_adj + vol_adj + reg_adj))

            signal = await evaluate_trade_opportunity(
                indicators    = indicators,
                regime        = regime_str,
                active_policy = policy,
                rl_confidence = round(dynamic_rl, 2),
                open_positions= open_count,
            )

            if signal:
                # Build signal record for dashboard
                sig_record = {
                    "id":         len(_signal_history) + 1,
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                    "symbol":     "ETH/USD",
                    "direction":  signal.direction,
                    "decision":   signal.decision,
                    "confidence": round(signal.confidence, 2),
                    "price":      price,
                    "regime":     regime_str,
                    "strategy":   signal.strategy_dna,
                    "analyst":    round(signal.analyst_score, 2),
                    "tech":       round(signal.tech_score, 2),
                    "rl":         round(signal.rl_vote, 2),
                    "risk":       round(signal.risk_score, 2),
                    "contrarian": round(signal.contrarian_penalty, 2),
                    "reasoning":  signal.reasoning_summary[:200],
                }
                _signal_history.append(sig_record)
                if len(_signal_history) > MAX_SIGNALS:
                    _signal_history.pop(0)

                logger.info(
                    f"[LiveLoop] Signal: {signal.decision} | dir={signal.direction} "
                    f"conf={signal.confidence:.2f} | {signal.reasoning_summary[:80]}"
                )

                # ── 5. Execute if EXECUTE decision ────────────────────────────
                if signal.decision == "EXECUTE" and _execution_engine:
                    _execution_engine.place_trade(signal)
                    logger.info(f"[LiveLoop] Opened paper position: {signal.direction} ETH/USD @ ${price:.2f}")

            # ── 6. Manage open positions ──────────────────────────────────────
            if _execution_engine and _execution_engine.open_positions:
                await _execution_engine._check_all_positions()

        except Exception as e:
            logger.error(f"[LiveLoop] Loop error: {e}", exc_info=True)

        await asyncio.sleep(LOOP_INTERVAL)


def start_trading_loop(engine):
    """Run trading loop in asyncio event loop on background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(trading_loop())


async def main():
    global _execution_engine

    # ── Init paper engine ─────────────────────────────────────────────────────
    _execution_engine = PaperExecutionEngine()
    logger.info(f"[Main] Paper engine initialized. Capital: ${float(os.getenv('CAPITAL_USD','10000')):,.0f}")

    # ── Wire API dependencies ─────────────────────────────────────────────────
    inject_dependencies(_execution_engine, _regime_cache, _signal_history)

    # ── Start trading loop in background ──────────────────────────────────────
    trading_task = asyncio.create_task(trading_loop())
    logger.info("[Main] Trading loop started in background.")

    # ── Start CoPAW (Cron Wrapper) ────────────────────────────────────────────
    from core.control.copaw import CoPAW
    copaw = CoPAW(_execution_engine, _signal_history)
    copaw.setup_schedules()
    copaw.start_background()

    # ── Start FastAPI ─────────────────────────────────────────────────────────
    logger.info("[Main] Starting FastAPI dashboard at http://localhost:8000")

    # Open browser after 2s delay
    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:8000")
    threading.Thread(target=open_browser, daemon=True).start()

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    
    try:
        await server.serve()
    finally:
        logger.info("\n[Main] System shutting down. Triggering HERMES post-mortem...")
        trading_task.cancel()
        
        try:
            from core.memory.hermes import HERMESAgent
            hermes = HERMESAgent()
            
            # If no trades were taken, HERMES will safely skip
            await hermes.run_post_mortem(_execution_engine.trade_log, _signal_history)
            
            logger.info("[Main] Shutdown complete.")
        except Exception as e:
            logger.error(f"[HERMES] Error during shutdown post-mortem: {e}")


if __name__ == "__main__":
    asyncio.run(main())
