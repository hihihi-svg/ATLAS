"""
ATLAS Event-Driven Backtester
Replays 30 days of 15m ETH/USD OHLCV data through the full system:
  indicators → regime → rule-based signal (no LLM) → risk → circuit breakers → stops

Uses deterministic rule-based signals (mimicking the agent voting system)
so the backtest is fast, reproducible, and doesn't require API keys.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import ta
import yfinance as yf
from loguru import logger

from core.data.regime_detector import classify_regime, REGIME_POLICY_MAP
from core.execution import circuit_breakers as cb
from core.execution.stop_manager import Position, StopManager


CAPITAL_USD    = float(os.getenv("CAPITAL_USD", "10000"))
BASE_RISK_PCT  = 0.015   # 1.5% risk per trade
MIN_CONFIDENCE = 8.5     # SNIPER MODE: Only elite trades for 60%+ accuracy

# Regime → allowed trade directions
REGIME_DIRECTIONS = {
    "bull":     ["LONG", "SHORT"],
    "bear":     ["LONG", "SHORT"],
    "chop":     ["LONG", "SHORT"],
    "volatile": [],
    "crisis":   [],
}

REGIME_SIZE_MULT = {"bull": 1.0, "bear": 0.85, "chop": 0.50, "volatile": 0.0, "crisis": 0.0}


@dataclass
class BacktestTrade:
    """Record of one completed trade in the backtest."""
    entry_time:  datetime
    exit_time:   datetime
    direction:   str
    entry_price: float
    exit_price:  float
    quantity:    float
    pnl_usd:     float
    pnl_pct:     float
    exit_reason: str
    regime:      str
    strategy:    str
    confidence:  float


@dataclass
class BacktestResult:
    """Full backtest output."""
    trades:          list[BacktestTrade] = field(default_factory=list)
    equity_curve:    list[float]         = field(default_factory=list)
    timestamps:      list[datetime]      = field(default_factory=list)
    daily_pnl:       dict                = field(default_factory=dict)
    regime_trades:   dict                = field(default_factory=dict)
    dna_trades:      dict                = field(default_factory=dict)

    # Summary metrics (computed after run)
    total_return:    float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio:    float = 0.0
    max_drawdown:    float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate:        float = 0.0
    profit_factor:   float = 0.0
    avg_win:         float = 0.0
    avg_loss:        float = 0.0
    total_trades:    int   = 0
    winning_trades:  int   = 0
    losing_trades:   int   = 0
    best_trade:      float = 0.0
    worst_trade:     float = 0.0
    best_day:        float = 0.0
    worst_day:       float = 0.0
    avg_hold_bars:   float = 0.0


class Backtester:
    def __init__(self, initial_capital: float = CAPITAL_USD):
        self.capital       = initial_capital
        self.equity        = initial_capital
        self.stop_mgr      = StopManager()
        self.open_position: Optional[Position] = None
        self.open_entry_time: Optional[datetime] = None
        self.open_strategy: str = ""
        self.open_regime:   str = ""
        self.open_confidence: float = 0.0

    def load_data(self, days: int = 30, interval: str = "15m") -> pd.DataFrame:
        """Fetch historical ETH/USD OHLCV from yfinance."""
        logger.info(f"[Backtest] Loading {days}d of {interval} ETH/USD data...")
        df = yf.download("ETH-USD", period=f"{days}d", interval=interval,
                         auto_adjust=True, progress=False)
        df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
        df.dropna(inplace=True)
        logger.info(f"[Backtest] Loaded {len(df)} candles ({df.index[0]} → {df.index[-1]})")
        return df

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all indicators to dataframe."""
        close = df["close"].squeeze()
        high  = df["high"].squeeze()
        low   = df["low"].squeeze()
        vol   = df["volume"].squeeze()

        df["ema9"]        = ta.trend.EMAIndicator(close, 9).ema_indicator()
        df["ema21"]       = ta.trend.EMAIndicator(close, 21).ema_indicator()
        df["ema50"]       = ta.trend.EMAIndicator(close, 50).ema_indicator()
        df["rsi"]         = ta.momentum.RSIIndicator(close, 14).rsi()
        df["atr"]         = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()

        macd = ta.trend.MACD(close)
        df["macd"]        = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_hist"]   = macd.macd_diff()

        bb = ta.volatility.BollingerBands(close, 20, 2)
        df["bb_upper"]    = bb.bollinger_hband()
        df["bb_lower"]    = bb.bollinger_lband()
        df["bb_mid"]      = bb.bollinger_mavg()

        try:
            df["vwap"] = ta.volume.VolumeWeightedAveragePrice(high, low, close, vol).volume_weighted_average_price()
        except Exception:
            df["vwap"] = close

        # Relative volume (20-bar rolling avg)
        avg_vol = vol.rolling(20).mean()
        df["rvol"] = vol / avg_vol.where(avg_vol > 0, 1)

        # ATR Percent (Relative Volatility)
        df["atr_pct"] = df["atr"] / close
        
        # EMA Slope (3-bar change)
        df["ema50_slope"] = df["ema50"].diff(3) / df["ema50"]
        
        # MACD Hist change
        df["macd_hist_prev"] = df["macd_hist"].shift(1)

        df.dropna(inplace=True)

        # Flatten MultiIndex columns from yfinance → single-level
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        return df

    def _f(self, v) -> float:
        """Safely extract float from scalar or single-element Series."""
        if hasattr(v, 'iloc'):
            return float(v.iloc[0])
        if hasattr(v, 'item'):
            return float(v.item())
        return float(v)

    def score_signal(self, row: pd.Series, regime: str) -> tuple[float, str, str]:
        """
        Rule-based signal scoring. Mimics LLM agent votes without API calls.
        Returns (confidence: float, direction: str, strategy: str).
        """
        allowed_dirs = REGIME_DIRECTIONS.get(regime, [])
        if not allowed_dirs:
            return 0.0, "NONE", "none"

        rsi  = self._f(row.get("rsi", 50))
        mh   = self._f(row.get("macd_hist", 0))
        rvol = self._f(row.get("rvol", 1.0))
        e9   = self._f(row.get("ema9", 0))
        e21  = self._f(row.get("ema21", 0))
        e50  = self._f(row.get("ema50", 0))
        close= self._f(row.get("close", 0))
        bb_u = self._f(row.get("bb_upper", close))
        bb_l = self._f(row.get("bb_lower", close))
        bb_m = self._f(row.get("bb_mid", close))

        score  = 5.0
        direction = "LONG"

        # ── Load Optimized Weights ───────────────────────────────────────────
        import json
        w_path = Path("memory/meta_weights.json")
        w_map = json.loads(w_path.read_text()) if w_path.exists() else {}
        m_weights = w_map.get(regime, w_map.get("default", {}))

        # ── STRATEGY DNA SYSTEM (PDF Section 4.4) ─────────────────────────────
        # LONG Triggers (PDF 4.4 - LONG Trade Entry)
        is_long = False
        if e9 > e21 > e50 and row["ema50_slope"] > 0.0001: is_long = True  # EMA Alignment
        if mh > 0 and mh > row["macd_hist_prev"]: is_long = True          # MACD Bullish
        if 40 < rsi < 65: is_long = True                                  # RSI Recovery
        if rvol > 1.5: is_long = True                                     # RVOL Confirmation

        # SHORT Triggers (PDF 4.4 - SHORT Trade Entry)
        is_short = False
        if e9 < e21 < e50 and row["ema50_slope"] < -0.0001: is_short = True # EMA Alignment
        if mh < 0 and mh < row["macd_hist_prev"]: is_short = True           # MACD Bearish
        if 35 < rsi < 60: is_short = True                                   # RSI Rejecting
        if rvol > 1.5: is_short = True                                      # RVOL Confirmation

        if is_long and "LONG" in allowed_dirs:
            direction = "LONG"
            strategy  = "momentum"
            score     = 8.5
        elif is_short and "SHORT" in allowed_dirs:
            direction = "SHORT"
            strategy  = "momentum"
            score     = 8.5
        else:
            return 0.0, "NONE", "none"

        # Apply regime multiplier (PDF Feature 3)
        regime_mult = REGIME_SIZE_MULT.get(regime, 1.0)
        score *= (0.7 + 0.3 * regime_mult)

        return round(score, 2), direction, strategy
        if regime_mult < 1.0:
            score *= regime_mult + (1 - regime_mult) * 0.5   # Soft penalty

        # ── Volume guard ──────────────────────────────────────────────────────
        if rvol < 0.5:
            score -= 1.5   # Dead volume = low confidence

        # ── Direction filter ──────────────────────────────────────────────────
        if direction not in allowed_dirs:
            return 0.0, "NONE", "none"

        score = max(0.0, min(10.0, score))
        return round(score, 2), direction, strategy

    def open_trade(self, row: pd.Series, direction: str, regime: str,
                   strategy: str, confidence: float, ts: datetime) -> bool:
        """Open a new paper position."""
        if self.open_position is not None:
            return False   # Already in a trade

        price    = self._f(row["close"])
        atr      = self._f(row["atr"])
        regime_m = REGIME_SIZE_MULT.get(regime, 1.0)
        conf_m   = 1.0 if confidence >= 8.0 else 0.75 if confidence >= 7.0 else 0.50

        stop_dist = atr * 1.5   # Wider stops to stay in trade
        if stop_dist / price > 0.04: 
            return False

        risk_usd  = self.equity * BASE_RISK_PCT
        size_usd  = min((risk_usd / (stop_dist / price)) * regime_m * conf_m,
                        self.equity * 0.20)
        quantity  = size_usd / price

        if direction == "LONG":
            stop  = price - stop_dist * 1.5   # PDF 4.5: 1.5x ATR stop
            t1    = price + stop_dist * 1.5   # PDF 4.5: Target 1
            t2    = price + stop_dist * 3.0   # PDF 4.5: Target 2
        else:
            stop  = price + stop_dist * 1.5
            t1    = price - stop_dist * 1.5
            t2    = price - stop_dist * 3.0

        self.open_position = Position(
            symbol="ETH/USD", direction=direction,
            entry_price=price, initial_stop=stop, current_stop=stop,
            target_1=t1, target_2=t2, quantity=quantity,
            atr_at_entry=atr, max_hold_hours=4.0,
            entry_time=ts,
        )
        self.open_entry_time  = ts
        self.open_strategy    = strategy
        self.open_regime      = regime
        self.open_confidence  = confidence
        return True

    def close_trade(
        self,
        row: pd.Series,
        exit_price: float,
        reason: str,
        ts: datetime,
        result: BacktestResult,
    ):
        """Close open position and record trade."""
        pos = self.open_position
        if pos is None:
            return

        qty = pos.quantity_remaining
        if pos.direction == "LONG":
            pnl = (exit_price - pos.entry_price) * qty
        else:
            pnl = (pos.entry_price - exit_price) * qty

        self.equity += pnl
        hold_bars   = (ts - self.open_entry_time).total_seconds() / self.bar_seconds

        trade = BacktestTrade(
            entry_time  = self.open_entry_time,
            exit_time   = ts,
            direction   = pos.direction,
            entry_price = pos.entry_price,
            exit_price  = exit_price,
            quantity    = qty,
            pnl_usd     = round(pnl, 4),
            pnl_pct     = round(pnl / self.capital * 100, 4),
            exit_reason = reason,
            regime      = self.open_regime,
            strategy    = self.open_strategy,
            confidence  = self.open_confidence,
        )
        result.trades.append(trade)

        # Daily P&L tracking
        day = ts.date().isoformat()
        result.daily_pnl[day] = result.daily_pnl.get(day, 0.0) + pnl

        self.open_position    = None
        self.open_entry_time  = None

    def run(self, days: int = 30, interval: str = "15m") -> BacktestResult:
        """
        Main backtest loop. Processes each candle.
        Returns BacktestResult with full trade log and metrics.
        """
        result = BacktestResult()
        cb.reset_daily()  # Clean start

        df = self.load_data(days, interval)
        df = self.compute_indicators(df)
        
        # Calculate bar seconds for hold time math
        import re
        match = re.match(r"(\d+)(\w)", interval)
        num, unit = int(match.group(1)), match.group(2)
        self.bar_seconds = num * 60 if unit == "m" else num * 3600 if unit == "h" else num * 86400
        
        logger.info(f"[Backtest] Starting simulation over {len(df)} candles...")
        prev_day = None  # Track date to avoid double-reset

        for i, (ts, row) in enumerate(df.iterrows()):
            ts_utc = ts.to_pydatetime()
            if ts_utc.tzinfo is None:
                ts_utc = ts_utc.replace(tzinfo=timezone.utc)

            # ── Daily reset ───────────────────────────────────────────────────
            cur_day = ts_utc.date()
            if cur_day != prev_day:
                cb.reset_daily(cur_day)
                prev_day = cur_day

            price = self._f(row["close"])

            # Track equity curve (every 4 hours = 16 bars)
            if i % 16 == 0:
                result.equity_curve.append(self.equity)
                result.timestamps.append(ts_utc)

            # ── Manage open position ──────────────────────────────────────────
            if self.open_position is not None:
                pos = self.open_position
                high = self._f(row["high"])
                low  = self._f(row["low"])

                # Skip stop check on entry bar (avoid same-bar false stop-outs)
                bars_held = (ts_utc - self.open_entry_time).total_seconds() / self.bar_seconds
                if bars_held < 1.0:
                    continue

                # Simulate intra-bar stop check
                check_price = low if pos.direction == "LONG" else high

                check_result = self.stop_mgr.full_check(pos, check_price, bar_time=ts_utc)

                if check_result["partial_exit"]:
                    # T1 hit — close 50%
                    t1_price = pos.target_1
                    half_qty = pos.quantity * 0.5
                    if pos.direction == "LONG":
                        pnl = (t1_price - pos.entry_price) * half_qty
                    else:
                        pnl = (pos.entry_price - t1_price) * half_qty
                    self.equity += pnl
                    day_key = ts_utc.date().isoformat()
                    result.daily_pnl[day_key] = result.daily_pnl.get(day_key, 0) + pnl

                if check_result["should_exit"]:
                    exit_p = pos.current_stop if "stop" in check_result["exit_reason"].lower() else (
                        pos.target_2 if check_result["exit_reason"] == "target_2" else price
                    )
                    self.close_trade(row, exit_p, check_result["exit_reason"], ts_utc, result)
                    cb.record_trade_result(result.trades[-1].pnl_usd)

                continue   # Don't open new trade same bar as close check

            # ── Circuit breaker gate (bypass date-check auto-reset for backtest) ──
            s = cb.get_state()
            if s.trading_halted or s.weekly_halt or s.flash_crash_halt:
                continue

            # ── Score signal ──────────────────────────────────────────────────
            ind_dict = {}
            for k, v in row.items():
                key = k[0] if isinstance(k, tuple) else k
                ind_dict[key] = self._f(v) if hasattr(v, 'iloc') or hasattr(v, 'item') else v
            regime, regime_score = classify_regime(ind_dict, {})
            confidence, direction, strategy = self.score_signal(row, regime)

            if confidence < MIN_CONFIDENCE or direction == "NONE":
                continue

            # ── Open position ─────────────────────────────────────────────────
            opened = self.open_trade(row, direction, regime, strategy, confidence, ts_utc)
            if opened:
                logger.debug(f"[Backtest] Opened {direction} @ ${price:.2f} | C={confidence:.2f} | {regime}")

        # ── Force-close any remaining position at end ─────────────────────────
        if self.open_position is not None and len(df) > 0:
            last_row = df.iloc[-1]
            last_ts  = df.index[-1].to_pydatetime().replace(tzinfo=timezone.utc)
            self.close_trade(last_row, self._f(last_row["close"]), "end_of_simulation", last_ts, result)

        # ── Final equity snapshot ─────────────────────────────────────────────
        result.equity_curve.append(self.equity)
        result.timestamps.append(df.index[-1].to_pydatetime().replace(tzinfo=timezone.utc))

        # ── Compute metrics ───────────────────────────────────────────────────
        result = self._compute_metrics(result)
        return result

    def _compute_metrics(self, result: BacktestResult) -> BacktestResult:
        """Compute all performance metrics from trade list and equity curve."""
        trades = result.trades
        if not trades:
            return result

        pnls = [t.pnl_usd for t in trades]
        wins = [p for p in pnls if p >= 0]
        loss = [p for p in pnls if p < 0]

        result.total_trades    = len(trades)
        result.winning_trades  = len(wins)
        result.losing_trades   = len(loss)
        result.total_return    = round(self.equity - self.capital, 2)
        result.total_return_pct= round((self.equity - self.capital) / self.capital * 100, 3)
        result.win_rate        = round(len(wins) / len(trades), 4) if trades else 0
        result.avg_win         = round(sum(wins) / len(wins), 2) if wins else 0
        result.avg_loss        = round(sum(loss) / len(loss), 2) if loss else 0
        result.best_trade      = round(max(pnls), 2)
        result.worst_trade     = round(min(pnls), 2)
        result.profit_factor   = round(abs(sum(wins) / sum(loss)), 3) if loss and sum(loss) != 0 else 999.0

        # Sharpe Ratio (annualized from daily P&L)
        daily_vals = list(result.daily_pnl.values())
        if len(daily_vals) >= 2:
            import statistics
            mean_d  = statistics.mean(daily_vals)
            std_d   = statistics.stdev(daily_vals)
            if std_d > 0:
                result.sharpe_ratio = round((mean_d / std_d) * (252 ** 0.5), 3)

        # Max Drawdown
        eq_curve = result.equity_curve
        peak = eq_curve[0]
        max_dd = 0.0
        for eq in eq_curve:
            peak = max(peak, eq)
            dd   = peak - eq
            max_dd = max(max_dd, dd)
        result.max_drawdown     = round(max_dd, 2)
        result.max_drawdown_pct = round(max_dd / self.capital * 100, 3)

        # Best/worst day
        if result.daily_pnl:
            result.best_day  = round(max(result.daily_pnl.values()), 2)
            result.worst_day = round(min(result.daily_pnl.values()), 2)

        # Average hold (in bars)
        holds = [(t.exit_time - t.entry_time).total_seconds() / self.bar_seconds for t in trades]
        result.avg_hold_bars = round(sum(holds) / len(holds), 1) if holds else 0

        # Per-regime breakdown
        for t in trades:
            if t.regime not in result.regime_trades:
                result.regime_trades[t.regime] = {"trades":0,"wins":0,"pnl":0.0}
            result.regime_trades[t.regime]["trades"] += 1
            if t.pnl_usd >= 0:
                result.regime_trades[t.regime]["wins"] += 1
            result.regime_trades[t.regime]["pnl"] += t.pnl_usd

        # Per-DNA breakdown
        for t in trades:
            if t.strategy not in result.dna_trades:
                result.dna_trades[t.strategy] = {"trades":0,"wins":0,"pnl":0.0}
            result.dna_trades[t.strategy]["trades"] += 1
            if t.pnl_usd >= 0:
                result.dna_trades[t.strategy]["wins"] += 1
            result.dna_trades[t.strategy]["pnl"] += t.pnl_usd

        return result
