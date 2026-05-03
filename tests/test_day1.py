"""
Quick smoke-test for Day 1 data pipeline.
Tests: yfinance fetch → indicators → regime classification (no DB/Redis needed).
Uses yfinance to avoid Windows aiodns conflict with ccxt async.
"""

import os
import pandas as pd
import ta
import yfinance as yf

from core.data.regime_detector import classify_regime


def test_data_pipeline():
    print("\n" + "="*60)
    print("  ATLAS Day 1 Smoke Test")
    print("="*60)

    # 1. Fetch OHLCV from Yahoo Finance (free, no auth, no async issues)
    print(f"\n[1/4] Fetching ETH-USD candles from Yahoo Finance...")
    df = yf.download("ETH-USD", period="30d", interval="15m", auto_adjust=True, progress=False)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    print(f"      ✓ Got {len(df)} candles. Latest close: ${float(df['close'].iloc[-1]):,.2f}")

    # 2. Compute indicators
    print("\n[2/4] Computing technical indicators...")
    close = df["close"].squeeze()
    high  = df["high"].squeeze()
    low   = df["low"].squeeze()
    vol   = df["volume"].squeeze()

    df["rsi"]       = ta.momentum.RSIIndicator(close, window=14).rsi()
    macd_ind        = ta.trend.MACD(close)
    df["macd"]      = macd_ind.macd()
    df["macd_hist"] = macd_ind.macd_diff()
    df["ema9"]      = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    df["ema21"]     = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    df["ema50"]     = ta.trend.EMAIndicator(close, window=50).ema_indicator()
    df["atr"]       = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    vol_avg         = vol.rolling(20).mean()
    df["rvol"]      = vol / vol_avg

    latest = df.iloc[-1]
    print(f"      ✓ RSI:       {float(latest['rsi']):.2f}")
    print(f"      ✓ MACD Hist: {float(latest['macd_hist']):.6f}")
    print(f"      ✓ EMA9:      ${float(latest['ema9']):,.2f}")
    print(f"      ✓ EMA21:     ${float(latest['ema21']):,.2f}")
    print(f"      ✓ EMA50:     ${float(latest['ema50']):,.2f}")
    print(f"      ✓ ATR:       ${float(latest['atr']):,.2f}")
    print(f"      ✓ RVOL:      {float(latest['rvol']):.2f}x")

    # 3. Regime classification
    print("\n[3/4] Running Regime Detector...")
    def _v(col, default=0):
        """Safe scalar extraction from possibly multi-level yfinance columns."""
        val = latest[col]
        if hasattr(val, "item"):
            val = val.item()
        try:
            return float(val) if val == val else default  # NaN check
        except Exception:
            return default

    ind = {
        "rsi":       _v("rsi",       50),
        "macd_hist": _v("macd_hist", 0),
        "ema9":      _v("ema9",      0),
        "ema21":     _v("ema21",     0),
        "ema50":     _v("ema50",     0),
        "rvol":      _v("rvol",      1),
        "atr":       _v("atr",       0),
        "close":     _v("close",     0),
    }
    regime, score = classify_regime(ind, {})
    from core.data.regime_detector import REGIME_POLICY_MAP
    policy = REGIME_POLICY_MAP.get(regime, "C")
    print(f"      ✓ Regime:     {regime.upper()} (confidence={score:.2f})")
    print(f"      ✓ Policy:     {policy}")

    # 4. ATR-based stop loss
    print("\n[4/4] Sample ATR Stop Loss calc...")
    entry = _v("close", 0)
    atr   = _v("atr",   entry * 0.01)
    if atr == 0:
        atr = entry * 0.01
    stop  = entry - (1.5 * atr)
    tgt1  = entry + (2.0 * atr)
    tgt2  = entry + (3.5 * atr)
    rr    = (tgt1 - entry) / (entry - stop)
    print(f"      Entry:  ${entry:,.2f}")
    print(f"      Stop:   ${stop:,.2f}  (−{(entry-stop)/entry*100:.2f}%)")
    print(f"      T1:     ${tgt1:,.2f}  (+{(tgt1-entry)/entry*100:.2f}%)")
    print(f"      T2:     ${tgt2:,.2f}  (+{(tgt2-entry)/entry*100:.2f}%)")
    print(f"      R:R     1:{rr:.2f}")

    print("\n" + "="*60)
    print("  ✅ Day 1 Smoke Test PASSED")
    print("="*60 + "\n")


if __name__ == "__main__":
    test_data_pipeline()
