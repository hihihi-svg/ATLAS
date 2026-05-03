"""
ATLAS FastAPI REST API
Control & monitoring endpoints used by the dashboard and external tools.
All write endpoints protected by X-API-Key header.

Endpoints:
  GET  /health          → system health check
  GET  /status          → full portfolio + circuit snapshot
  GET  /regime          → current market regime
  GET  /portfolio       → open positions + unrealized P&L
  GET  /signals         → last 20 trade signals
  GET  /circuit         → circuit breaker status
  GET  /trades          → today's closed trade log
  POST /halt            → manual trading halt
  POST /resume          → resume after halt
  POST /exitall         → close all positions now
  POST /vix             → update VIX level
"""

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, WebSocket, HTTPException, Depends, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from loguru import logger
from dotenv import load_dotenv

from core.execution import circuit_breakers as cb

load_dotenv()

API_KEY = os.getenv("API_KEY", "atlas-dev-key")   # Set in .env for production

# Chart data cache (refreshed every 2 min to avoid hammering yfinance)
_chart_cache    = {"data": None, "ts": 0}
_CHART_TTL_SECS = 120


# These are injected at runtime
_execution_engine = None
_regime_cache     = {}
_signal_history   = []


def inject_dependencies(engine, regime_cache_ref, signal_history_ref):
    global _execution_engine, _regime_cache, _signal_history
    _execution_engine = engine
    _regime_cache     = regime_cache_ref
    _signal_history   = signal_history_ref


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "ATLAS Trading API",
    description = "Control and monitoring API for ATLAS autonomous trading system",
    version     = "1.0.0",
)
app.mount("/reports", StaticFiles(directory="simulation/reports"), name="reports")

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],   # Tighten in production
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)


# ── Auth ──────────────────────────────────────────────────────────────────────
def verify_api_key(x_api_key: str = Header(default=None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key


# ── Pydantic Models ───────────────────────────────────────────────────────────
class VixUpdate(BaseModel):
    vix: float

class HaltRequest(BaseModel):
    reason: Optional[str] = "API manual halt"


# ── Read Endpoints ────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status":    "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system":    "ATLAS v1.0",
        "mode":      "paper" if os.getenv("PAPER_TRADING", "true") == "true" else "live",
    }


@app.get("/config")
async def get_config():
    """Returns dashboard config including API key — local dev use only."""
    return {
        "api_key":     API_KEY,
        "trading_pair": os.getenv("TRADING_PAIR", "ETH/USDT"),
        "paper_mode":  os.getenv("PAPER_TRADING", "true") == "true",
        "capital_usd": float(os.getenv("CAPITAL_USD", "10000")),
    }


@app.get("/status")
async def get_status():
    """Full system status — for dashboard main view."""
    engine  = _execution_engine
    circuit = cb.status_summary()
    regime  = _regime_cache if isinstance(_regime_cache, dict) else {}

    pos_list = []
    total_unrealized = 0.0
    current_price = 0
    if engine:
        try:
            current_price = engine._get_current_price() or 0
            for sym, pos in engine.open_positions.items():
                pnl = engine._calc_pnl(pos, current_price, pos.quantity_remaining)
                total_unrealized += pnl
                pos_list.append({
                    "symbol":       sym,
                    "direction":    pos.direction,
                    "entry":        pos.entry_price,
                    "current":      current_price,
                    "qty":          pos.quantity_remaining,
                    "unrealized":   round(pnl, 2),
                    "stop":         pos.current_stop,
                    "target_1":     pos.target_1,
                    "target_2":     pos.target_2,
                    "break_even":   pos.break_even_triggered,
                    "hours_held":   round((datetime.now(timezone.utc) - pos.entry_time).total_seconds() / 3600, 2),
                    "position_usd": round(pos.quantity_remaining * current_price, 2),
                })
        except Exception as e:
            logger.warning(f"[API] Position status error: {e}")

    # Build last signal with full trade action details
    last_sig = _signal_history[-1] if _signal_history else None
    capital = float(os.getenv('CAPITAL_USD', '10000'))

    return {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "regime":           regime,
        "circuit":          circuit,
        "positions":        pos_list,
        "open_count":       len(pos_list),
        "signal_count":     len(_signal_history),
        "last_signal":      last_sig,
        "current_price":    current_price,
        "total_unrealized":  round(total_unrealized, 2),
        "total_pnl":        round(circuit.get('daily_pnl_usd', 0) + total_unrealized, 2),
        "capital":          capital,
    }


@app.get("/regime")
async def get_regime():
    return _regime_cache if isinstance(_regime_cache, dict) else {}


@app.get("/portfolio")
async def get_portfolio():
    if not _execution_engine:
        return {"positions": [], "unrealized_pnl": 0}
    return _execution_engine.portfolio_status()


@app.get("/signals")
async def get_signals(limit: int = 20):
    return {"signals": _signal_history[-limit:][::-1]}


@app.get("/circuit")
async def get_circuit():
    return cb.status_summary()


@app.get("/trades")
async def get_trades():
    if not _execution_engine:
        return {"trades": []}
    return {"trades": _execution_engine.trade_log}


# ── Write Endpoints (API key required) ───────────────────────────────────────
@app.post("/halt")
async def halt_trading(body: HaltRequest, key: str = Depends(verify_api_key)):
    s = cb.get_state()
    s.trading_halted = True
    s.halt_reason    = body.reason
    logger.warning(f"[API] Trading halted via API: {body.reason}")
    return {"status": "halted", "reason": body.reason}


@app.post("/resume")
async def resume_trading(key: str = Depends(verify_api_key)):
    cb.manual_resume("API manual resume")
    return {"status": "resumed"}


@app.post("/exitall")
async def exit_all(key: str = Depends(verify_api_key)):
    if not _execution_engine:
        raise HTTPException(status_code=503, detail="Execution engine not connected")
    count = len(_execution_engine.open_positions)
    _execution_engine.close_all("api_exitall")
    return {"status": "closed", "positions_closed": count}


@app.post("/vix")
async def update_vix(body: VixUpdate, key: str = Depends(verify_api_key)):
    cb.update_vix(body.vix)
    return {"status": "updated", "vix": body.vix, "size_multiplier": cb.get_size_multiplier()}


@app.get("/authenticity-report")
async def get_authenticity_report():
    """Redirect to the latest 60-day authenticity report."""
    return RedirectResponse(url="/reports/backtest_20260503_172305.html")

@app.get("/audit-report")
async def get_audit_report():
    """Redirect to the latest 365-day performance audit."""
    return RedirectResponse(url="/reports/ATLAS_1YEAR_AUDIT.html")

@app.get("/transformation-report")
async def get_transformation_report():
    """Redirect to the manual-vs-AI transformation audit."""
    return RedirectResponse(url="/reports/TRANSFORMATION_AUDIT.html")

@app.post("/hermes")
async def trigger_hermes(key: str = Depends(verify_api_key)):
    from core.memory.hermes import HERMESAgent
    hermes = HERMESAgent()
    try:
        # Pass live market data to HERMES for the 4-graph report
        market_data = dict(_regime_cache) if _regime_cache else None
        mem = await hermes.run_post_mortem(_execution_engine.trade_log, _signal_history, market_data)
        if mem:
            return {
                "status": "success", 
                "date": mem.date, 
                "trades": mem.total_trades, 
                "grade": mem.lessons.get("performance_grade", "?"),
                "briefing": mem.lessons.get("daily_market_report", mem.morning_briefing),
                "top_insight": mem.lessons.get("top_insight", "")
            }
        return {"status": "skipped", "message": "No trades to analyze today."}
    except Exception as e:
        logger.error(f"[API] HERMES error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/vix-live")
async def get_live_vix():
    """Returns the current VIX value stored in circuit breaker (auto-fetched from yfinance on startup)."""
    s = cb.get_state()
    mult = cb.get_size_multiplier()
    zone = "calm" if s.current_vix < 20 else "caution" if s.current_vix < 30 else "fearful"
    return {
        "vix":              round(s.current_vix, 2),
        "size_multiplier":  round(mult, 2),
        "zone":             zone,
        "label":            f"VIX {s.current_vix:.1f} — {zone.upper()} (size: {mult*100:.0f}%)",
    }


# ── Gemini Real-Time Chart Inference ─────────────────────────────────────────
@app.get("/chart-inference")
async def get_chart_inference():
    """
    Calls Gemini Flash to generate plain-English XAI insight for each live indicator.
    Cached 60s so rapid refreshes don't burn quota.
    """
    import json, urllib.request, time

    hf_key = os.getenv("HF_TOKEN", "hf_key_not_set")

    r = dict(_regime_cache)
    if not r.get("close"):
        return {"error": "No market data yet — wait for first trading loop cycle"}

    prompt = f"""[INST] You are a trading assistant analyzing ETH/USD live charts. Write ONE short sentence (max 18 words) for each indicator. Be direct. No jargon.
Current data:
- Price: ${r.get('close',0):.2f}
- RSI(14): {r.get('rsi',50):.1f} (0-100, >70=overbought, <30=oversold, 50=neutral)
- MACD Histogram: {r.get('macd_hist',0):.4f} (positive=bullish momentum, negative=bearish)
- ATR (volatility): ${r.get('atr',0):.2f} (higher=bigger candles expected)
- RVOL: {r.get('rvol',1):.2f}x (>1.5=strong volume, <0.5=low interest)
- Regime: {r.get('regime','chop').upper()} (BULL/BEAR/CHOP)

Return ONLY a single valid JSON object, no markdown, no other text. Keys required: price, rsi, atr, macd, rvol, summary. [/INST]"""

    payload = json.dumps({
        "inputs": prompt,
        "parameters": {"max_new_tokens": 300, "temperature": 0.3, "return_full_text": False}
    }).encode()

    url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"

    try:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json", "Authorization": f"Bearer {hf_key}"}
        )
        resp = urllib.request.urlopen(req, timeout=12)
        data = json.loads(resp.read())
        text = data[0]["generated_text"].strip()
        
        # Strip markdown code fences if Hugging Face model adds them
        if "```" in text:
            parts = text.split("```")
            text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
            
        # Ensure it starts with {
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1:
            text = text[start:end]

        result = json.loads(text)
        result["_ts"] = datetime.now(timezone.utc).isoformat()
        return result
    except Exception as e:
        logger.error(f"[API] Hugging Face inference error: {e}")
        # Robust fallback based on indicators
        rsi_val = r.get('rsi', 50)
        mhist = r.get('macd_hist', 0)
        rvol = r.get('rvol', 1.0)
        
        rsi_desc = "Neutral momentum."
        if rsi_val > 70: rsi_desc = "Overbought. Potential reversal zone."
        elif rsi_val > 60: rsi_desc = "Strong bullish momentum."
        elif rsi_val < 30: rsi_desc = "Oversold. Possible bounce area."
        elif rsi_val < 40: rsi_desc = "Strong bearish momentum."
        
        macd_desc = "Bullish momentum increasing." if mhist > 0 else "Bearish momentum prevailing."
        vol_desc = "High volume confirming move." if rvol > 1.3 else "Low volume, be cautious."
        
        return {
            "price": f"Trading at ${r.get('close',0):.2f}.",
            "rsi": rsi_desc,
            "atr": f"Daily range around ${r.get('atr',0):.2f}.",
            "macd": macd_desc,
            "rvol": vol_desc,
            "summary": f"Market is in {r.get('regime','chop').upper()} regime with {rsi_desc.lower()}",
            "_fallback": True
        }


# ── Chart Data Endpoint ───────────────────────────────────────────────────────
@app.get("/chart-data")
async def get_chart_data(bars: int = 80):
    """
    Returns last N 15m candles of ETH/USD with indicators for the dashboard chart.
    Cached for 2 minutes to avoid excessive yfinance calls.
    """
    import time
    now = time.time()

    # Return cached data if fresh
    if _chart_cache["data"] and (now - _chart_cache["ts"]) < _CHART_TTL_SECS:
        return _chart_cache["data"]

    try:
        import yfinance as yf
        import ta
        import pandas as pd

        df = yf.download("ETH-USD", period="5d", interval="15m",
                         auto_adjust=True, progress=False)
        df = df.rename(columns={"Open":"open","High":"high","Low":"low",
                                 "Close":"close","Volume":"volume"})
        df.dropna(inplace=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        c = df["close"].squeeze()
        h = df["high"].squeeze()
        l = df["low"].squeeze()
        v = df["volume"].squeeze()

        df["ema9"]      = ta.trend.EMAIndicator(c, 9).ema_indicator()
        df["ema21"]     = ta.trend.EMAIndicator(c, 21).ema_indicator()
        df["ema50"]     = ta.trend.EMAIndicator(c, 50).ema_indicator()
        df["rsi"]       = ta.momentum.RSIIndicator(c, 14).rsi()
        df["atr"]       = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
        df["macd_hist"] = ta.trend.MACD(c).macd_diff()

        bb = ta.volatility.BollingerBands(c, 20, 2)
        df["bb_upper"]  = bb.bollinger_hband()
        df["bb_lower"]  = bb.bollinger_lband()
        df["bb_mid"]    = bb.bollinger_mavg()

        avg_v = v.rolling(20).mean()
        df["rvol"] = v / avg_v.where(avg_v > 0, 1)
        df.dropna(inplace=True)

        def _f(x):
            try:
                v = float(x)
                return round(v, 4)
            except Exception:
                return None

        tail = df.tail(bars)
        result = []
        for ts, row in tail.iterrows():
            result.append({
                "t":        ts.isoformat(),
                "close":    _f(row["close"]),
                "high":     _f(row["high"]),
                "low":      _f(row["low"]),
                "open":     _f(row["open"]),
                "volume":   _f(row["volume"]),
                "ema9":     _f(row["ema9"]),
                "ema21":    _f(row["ema21"]),
                "ema50":    _f(row["ema50"]),
                "bb_upper": _f(row["bb_upper"]),
                "bb_lower": _f(row["bb_lower"]),
                "bb_mid":   _f(row["bb_mid"]),
                "rsi":      _f(row["rsi"]),
                "atr":      _f(row["atr"]),
                "macd_hist":_f(row["macd_hist"]),
                "rvol":     _f(row["rvol"]),
            })

        payload = {"bars": result, "count": len(result),
                   "updated_at": datetime.now(timezone.utc).isoformat()}
        _chart_cache["data"] = payload
        _chart_cache["ts"]   = now
        return payload

    except Exception as e:
        logger.error(f"[API] Chart data error: {e}")
        return {"bars": [], "count": 0, "error": str(e)}


# ── Dashboard File ────────────────────────────────────────────────────────────
@app.get("/")
async def serve_dashboard():
    import os
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path, media_type="text/html")
    return JSONResponse({"message": "Dashboard HTML not found. Run from project root."})

@app.get("/catalog")
async def serve_catalog():
    import os
    catalog_path = os.path.join(os.path.dirname(__file__), "catalog.html")
    if os.path.exists(catalog_path):
        return FileResponse(catalog_path, media_type="text/html")
    return JSONResponse({"message": "Catalog HTML not found."})

