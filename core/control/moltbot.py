"""
ATLAS MOLTBOT — Telegram Control Interface
Extends existing MOLTBOT with full trading system control.
All commands gated by TELEGRAM_CHAT_ID for security.

Commands:
  /status     → portfolio snapshot + circuit status
  /regime     → current market regime + active policy
  /pnl        → today's P&L summary
  /signals    → last 5 trade signals
  /circuit    → full circuit breaker status
  /halt       → manual trading halt
  /resume     → manual trading resume
  /exitall    → close ALL open positions immediately
  /vix <n>    → manually update VIX level
  /help       → command list
"""

import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from loguru import logger

from core.execution import circuit_breakers as cb

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENABLED          = bool(TELEGRAM_TOKEN and TELEGRAM_TOKEN != "your_telegram_bot_token")

# These are injected at runtime by main.py
_execution_engine = None
_regime_cache     = {"regime": "unknown", "policy": "?", "score": 0}
_signal_history   = []   # Rolling list of last 20 TradeSignal dicts


def inject_dependencies(engine, regime_getter=None):
    """Called by main.py to give MOLTBOT access to live state."""
    global _execution_engine, _regime_cache
    _execution_engine = engine
    if regime_getter:
        _regime_cache = regime_getter


def add_signal_to_history(signal):
    """Called by signal pipeline after each evaluation."""
    global _signal_history
    _signal_history.append({
        "symbol":     signal.symbol,
        "direction":  signal.direction,
        "decision":   signal.decision,
        "confidence": signal.confidence,
        "strategy":   signal.strategy_dna,
        "regime":     signal.regime,
        "price":      signal.entry_price,
        "ts":         datetime.now(timezone.utc).isoformat(),
    })
    if len(_signal_history) > 20:
        _signal_history.pop(0)


async def send_alert(message: str, parse_mode: str = "HTML"):
    """
    Send message to configured Telegram chat.
    Called by circuit breakers and execution engine for alerts.
    """
    if not ENABLED:
        logger.info(f"[MOLTBOT] (mock) Alert: {message[:80]}")
        return

    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id    = TELEGRAM_CHAT_ID,
            text       = message,
            parse_mode = parse_mode
        )
    except Exception as e:
        logger.error(f"[MOLTBOT] Failed to send alert: {e}")


async def send_trade_signal_alert(signal):
    """Rich trade signal notification."""
    emoji = "🟢" if signal.direction == "LONG" else "🔴" if signal.direction == "SHORT" else "⚪"
    action_emoji = "⚡" if signal.decision == "EXECUTE" else "⏭️"

    msg = (
        f"{action_emoji} <b>ATLAS SIGNAL</b>\n\n"
        f"{emoji} <b>{signal.direction} {signal.symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Decision:    <b>{signal.decision}</b>\n"
        f"Confidence:  <b>{signal.confidence:.2f}/10</b>\n"
        f"Entry:       <code>${signal.entry_price:,.2f}</code>\n"
        f"Stop Loss:   <code>${signal.stop_loss:,.2f}</code>\n"
        f"Target 1:    <code>${signal.target_1:,.2f}</code>\n"
        f"Target 2:    <code>${signal.target_2:,.2f}</code>\n"
        f"Size:        <code>${signal.position_size_usd:.0f} ({signal.size_multiplier*100:.0f}%)</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Regime:  {signal.regime.upper()} | Policy: {signal.active_policy} | DNA: {signal.strategy_dna}\n"
        f"<i>{signal.reasoning_summary[:120]}</i>"
    )
    await send_alert(msg)


async def send_circuit_alert(alert_type: str, message: str):
    """Circuit breaker alert."""
    emojis = {
        "halt":        "🛑",
        "daily_halt":  "🛑",
        "weekly_halt": "❌",
        "size_reduction": "⚠️",
        "single_loss_alert": "⚠️",
        "flash_crash": "💥",
    }
    emoji = emojis.get(alert_type, "⚠️")
    await send_alert(f"{emoji} <b>CIRCUIT BREAKER: {alert_type.upper()}</b>\n{message}")


def _build_status_message() -> str:
    """Build rich portfolio status message."""
    engine  = _execution_engine
    cb_stat = cb.status_summary()
    regime  = _regime_cache if isinstance(_regime_cache, dict) else {"regime": "?", "policy": "?", "score": 0}

    trade_icon = "✅" if cb_stat["can_trade"] else "🛑"
    regime_icon = {"bull": "🐂", "bear": "🐻", "chop": "〰️", "volatile": "⚡", "crisis": "💥"}.get(
        regime.get("regime", ""), "❓"
    )

    pnl = cb_stat["daily_pnl_usd"]
    pnl_icon = "📈" if pnl >= 0 else "📉"

    pos_count = len(engine.open_positions) if engine else 0

    lines = [
        "<b>ATLAS Status</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Trading:   {trade_icon} {'ACTIVE' if cb_stat['can_trade'] else 'HALTED'}",
        f"Regime:    {regime_icon} {regime.get('regime', '?').upper()} → Policy {regime.get('policy', '?')}",
        f"Positions: {pos_count} open",
        f"Daily P&L: {pnl_icon} <code>${pnl:+.2f} ({cb_stat['daily_pnl_pct']*100:+.2f}%)</code>",
        f"Win/Loss:  {cb_stat['wins_today']}W / {cb_stat['losses_today']}L",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Streak:    {cb_stat['consecutive_losses']} consecutive losses",
        f"Size Mult: {cb_stat['size_multiplier']*100:.0f}%",
        f"VIX:       {cb_stat['vix']:.1f} (mult={cb_stat['vix_mult']:.2f}x)",
    ]

    if not cb_stat["can_trade"]:
        lines.append(f"\n🛑 <b>HALT REASON:</b> {cb_stat['halt_reason']}")

    # Add open positions
    if engine and engine.open_positions:
        lines.append("\n<b>Open Positions:</b>")
        for sym, pos in engine.open_positions.items():
            lines.append(f"  {sym} {pos.direction} x{pos.quantity_remaining:.4f} @ ${pos.entry_price:,.2f}")

    return "\n".join(lines)


def _build_circuit_message() -> str:
    s = cb.status_summary()
    lines = [
        "<b>Circuit Breaker Status</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Can Trade:        {'✅ YES' if s['can_trade'] else '🛑 NO'}",
        f"Daily P&L:        ${s['daily_pnl_usd']:+.2f} ({s['daily_pnl_pct']*100:+.2f}%)",
        f"Weekly P&L:       ${s['weekly_pnl_usd']:+.2f}",
        f"Consec Losses:    {s['consecutive_losses']}/{5}",
        f"Size Multiplier:  {s['size_multiplier']*100:.0f}%",
        f"Reduced Trades:   {s['reduced_size_trades']} remaining",
        f"VIX Level:        {s['vix']:.1f} (×{s['vix_mult']:.2f})",
        f"Trades Today:     {s['trades_today']} ({s['wins_today']}W/{s['losses_today']}L)",
    ]
    if not s["can_trade"]:
        lines.append(f"\n🛑 {s['halt_reason']}")
    return "\n".join(lines)


async def start_bot():
    """Start polling Telegram bot. Blocks — run in separate thread."""
    if not ENABLED:
        logger.warning("[MOLTBOT] Token not configured. Bot disabled. Set TELEGRAM_BOT_TOKEN in .env")
        return

    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes

    async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        await update.message.reply_html(_build_status_message())

    async def cmd_regime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        r = _regime_cache if isinstance(_regime_cache, dict) else {}
        icon = {"bull": "🐂", "bear": "🐻", "chop": "〰️", "volatile": "⚡"}.get(r.get("regime", ""), "❓")
        msg  = (
            f"{icon} <b>Regime: {r.get('regime','?').upper()}</b>\n"
            f"Score:    {r.get('score',0):.2f}\n"
            f"Policy:   {r.get('policy','?')}\n"
            f"RSI:      {r.get('rsi',0):.1f}\n"
            f"RVOL:     {r.get('rvol',0):.2f}x"
        )
        await update.message.reply_html(msg)

    async def cmd_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        s = cb.status_summary()
        pnl_icon = "📈" if s["daily_pnl_usd"] >= 0 else "📉"
        msg = (
            f"{pnl_icon} <b>P&L Report</b>\n\n"
            f"Today:    <code>${s['daily_pnl_usd']:+.2f} ({s['daily_pnl_pct']*100:+.2f}%)</code>\n"
            f"Weekly:   <code>${s['weekly_pnl_usd']:+.2f}</code>\n"
            f"Trades:   {s['trades_today']} | {s['wins_today']}W {s['losses_today']}L\n"
            f"Win Rate: {(s['wins_today']/max(s['trades_today'],1)*100):.0f}%"
        )
        await update.message.reply_html(msg)

    async def cmd_signals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        if not _signal_history:
            await update.message.reply_text("No signals yet today.")
            return
        lines = ["<b>Last 5 Signals:</b>", "━━━━━━━━━━━━━━━━━━━━"]
        for s in _signal_history[-5:][::-1]:
            icon = "⚡" if s["decision"] == "EXECUTE" else "⏭️"
            dir_icon = "🟢" if s["direction"] == "LONG" else "🔴" if s["direction"] == "SHORT" else "⚪"
            lines.append(f"{icon}{dir_icon} {s['symbol']} | {s['decision']} | {s['confidence']:.2f} | {s['regime']} | ${s['price']:,.0f}")
        await update.message.reply_html("\n".join(lines))

    async def cmd_circuit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        await update.message.reply_html(_build_circuit_message())

    async def cmd_halt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        s = cb.get_state()
        s.trading_halted = True
        s.halt_reason    = f"Manual halt via Telegram by admin"
        await update.message.reply_html("🛑 <b>Trading HALTED manually.</b> Use /resume to re-enable.")
        logger.warning("[MOLTBOT] Manual halt via Telegram.")

    async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        cb.manual_resume("Telegram admin /resume")
        await update.message.reply_html("✅ <b>Trading RESUMED.</b>")
        logger.info("[MOLTBOT] Trading resumed via Telegram.")

    async def cmd_exitall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        if not _execution_engine:
            await update.message.reply_text("Execution engine not connected.")
            return
        count = len(_execution_engine.open_positions)
        _execution_engine.close_all("telegram_exitall")
        await update.message.reply_html(f"⚡ <b>CLOSED {count} positions</b> via Telegram /exitall.")

    async def cmd_vix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        try:
            vix_val = float(ctx.args[0])
            cb.update_vix(vix_val)
            mult = cb.get_size_multiplier()
            await update.message.reply_html(
                f"📊 VIX updated to <b>{vix_val:.1f}</b>\n"
                f"Size multiplier: <b>{mult*100:.0f}%</b>"
            )
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: /vix <number>  e.g. /vix 28.5")

    async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        msg = (
            "<b>ATLAS Commands</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "/status   — full portfolio snapshot\n"
            "/regime   — current market regime\n"
            "/pnl      — today's P&L\n"
            "/signals  — last 5 signals\n"
            "/circuit  — circuit breaker status\n"
            "/halt     — manual halt\n"
            "/resume   — resume after halt\n"
            "/exitall  — close all positions NOW\n"
            "/vix &lt;n&gt; — set VIX level\n"
            "/help     — this message"
        )
        await update.message.reply_html(msg)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("regime",  cmd_regime))
    app.add_handler(CommandHandler("pnl",     cmd_pnl))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("circuit", cmd_circuit))
    app.add_handler(CommandHandler("halt",    cmd_halt))
    app.add_handler(CommandHandler("resume",  cmd_resume))
    app.add_handler(CommandHandler("exitall", cmd_exitall))
    app.add_handler(CommandHandler("vix",     cmd_vix))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("start",   cmd_help))

    logger.info("[MOLTBOT] Telegram bot started. Polling...")
    await app.run_polling(drop_pending_updates=True)


def _is_authorized(update) -> bool:
    """Only respond to configured chat ID."""
    if not TELEGRAM_CHAT_ID:
        return True   # Dev mode: accept all
    chat_id = str(update.effective_chat.id)
    if chat_id != TELEGRAM_CHAT_ID:
        logger.warning(f"[MOLTBOT] Unauthorized access from chat_id={chat_id}")
        return False
    return True
