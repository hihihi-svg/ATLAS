"""
ATLAS Quick Signal Check
Run: python quick_signal.py
Gets live ETH/USD price, runs all 5 AI agents, outputs BUY/SELL/WAIT verdict.
"""
from dotenv import load_dotenv; load_dotenv()
import asyncio, warnings, sys
warnings.filterwarnings('ignore')

import yfinance as yf
import ta
import pandas as pd
from core.data.regime_detector import classify_regime, REGIME_POLICY_MAP
from core.agents.signal_pipeline import evaluate_trade_opportunity


def _f(v):
    if hasattr(v, 'iloc'): return float(v.iloc[0])
    if hasattr(v, 'item'): return float(v.item())
    return float(v)


def fetch_indicators():
    df = yf.download("ETH-USD", period="5d", interval="15m", auto_adjust=True, progress=False)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
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
    bb              = ta.volatility.BollingerBands(c, 20, 2)
    df["bb_upper"]  = bb.bollinger_hband()
    df["bb_lower"]  = bb.bollinger_lband()
    df["bb_mid"]    = bb.bollinger_mavg()
    avg_v           = v.rolling(20).mean()
    df["rvol"]      = v / avg_v.where(avg_v > 0, 1)
    df.dropna(inplace=True)

    row = df.iloc[-1]
    return {k: (_f(v2) if hasattr(v2,'iloc') or hasattr(v2,'item') else v2) for k,v2 in row.items()}


async def main():
    print()
    print("=" * 47)
    print("  ATLAS  —  ETH/USD Signal Check")
    print("=" * 47)

    print("  Fetching live ETH/USD data...")
    ind = fetch_indicators()

    price = ind["close"]
    rsi   = ind["rsi"]
    atr   = ind["atr"]
    rvol  = ind["rvol"]
    mh    = ind["macd_hist"]

    print(f"  Price  : ${price:,.2f}")
    print(f"  RSI    : {rsi:.1f}")
    print(f"  ATR    : ${atr:.2f}")
    print(f"  RVOL   : {rvol:.2f}x")
    print(f"  MACD H : {mh:+.4f}")
    print()

    regime_str, regime_score = classify_regime(ind, {})
    policy = REGIME_POLICY_MAP.get(regime_str, "C")
    print(f"  Regime : {regime_str.upper()} ({regime_score*100:.0f}% confidence)")
    print(f"  Policy : {policy}")
    print()
    print("  Running 5 AI agents (GPT-4o-mini)...")

    signal = await evaluate_trade_opportunity(
        indicators    = ind,
        regime        = regime_str,
        active_policy = policy,
        rl_confidence = 7.0,
        open_positions= 0,
    )

    print()
    print("=" * 47)

    if signal and signal.decision == "EXECUTE":
        if signal.direction == "LONG":
            verdict = "BUY  (LONG)"
            emoji   = "GREEN"
        else:
            verdict = "SELL (SHORT)"
            emoji   = "RED"

        stop_dist = atr * 1.5
        if signal.direction == "LONG":
            stop = price - stop_dist
            t1   = price + stop_dist * 2.0
            t2   = price + stop_dist * 3.5
        else:
            stop = price + stop_dist
            t1   = price - stop_dist * 2.0
            t2   = price - stop_dist * 3.5

        print(f"  VERDICT    : *** {verdict} ***")
        print(f"  Confidence : {signal.confidence:.2f}/10")
        print()
        print(f"  Entry      : ${price:,.2f}")
        print(f"  Stop Loss  : ${stop:,.2f}   (risk ${stop_dist:.2f})")
        print(f"  Target 1   : ${t1:,.2f}   (reward ${stop_dist*2:.2f})")
        print(f"  Target 2   : ${t2:,.2f}   (reward ${stop_dist*3.5:.2f})")
        print(f"  Risk/Reward: 1 : 2.0 / 1 : 3.5")
    else:
        conf = signal.confidence if signal else 0
        print(f"  VERDICT    : *** WAIT — No trade now ***")
        print(f"  Confidence : {conf:.2f}/10  (need >= 6.5)")
        print(f"  Reason     : {signal.reasoning_summary[:120] if signal else 'No signal'}")

    print()
    if signal:
        print(f"  Analyst    : {signal.analyst_score:.1f}/10")
        print(f"  Technician : {signal.tech_score:.1f}/10")
        print(f"  Contrarian : -{signal.contrarian_penalty:.1f} penalty")
        print()
        print(f"  AI says    : {signal.reasoning_summary[:180]}")
    print("=" * 47)
    print()


if __name__ == "__main__":
    asyncio.run(main())
