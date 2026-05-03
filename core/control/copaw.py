"""
ATLAS CoPAW 
Cron-Operated Process Automation Wrapper
Handles scheduled background tasks without blocking the main trading loop.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import os
from loguru import logger

from core.execution import circuit_breakers as cb
from core.memory.hermes import HERMESAgent

class CoPAW:
    def __init__(self, engine, signal_history):
        self.engine = engine
        self.signal_history = signal_history
        self._running = False
        self.tasks = []
        
    async def _midnight_reset(self):
        """Runs at 00:00 UTC."""
        logger.info("[CoPAW] 🕛 Midnight Reset Triggered")
        
        # 1. Reset circuit breakers for the new day
        cb.reset_daily()
        
        # 2. Run HERMES post-mortem on yesterday's trades
        await self._trigger_hermes()
        
        # 3. Clear trade log for the new day
        self.engine.trade_log.clear()
        self.signal_history.clear()
        logger.info("[CoPAW] 🕛 Midnight Reset Complete")

    async def _trigger_hermes(self):
        hermes = HERMESAgent()
        try:
            await hermes.run_post_mortem(self.engine.trade_log, self.signal_history)
        except Exception as e:
            logger.error(f"[CoPAW] HERMES error during midnight reset: {e}")

    async def _morning_vix(self):
        """Runs at 09:00 UTC."""
        logger.info("[CoPAW] 🕘 Morning Routine: Fetching VIX")
        # VIX is fetched automatically in run_live.py's trading_loop

    async def _schedule_daily(self, hour, minute, coroutine):
        while self._running:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
                
            wait_seconds = (target - now).total_seconds()
            logger.info(f"[CoPAW] Scheduled task for {hour:02d}:{minute:02d} UTC (in {wait_seconds:.0f}s)")
            await asyncio.sleep(wait_seconds)
            
            if self._running:
                await coroutine()

    def setup_schedules(self):
        """Schedule the daily tasks via asyncio."""
        self.tasks.append(asyncio.create_task(self._schedule_daily(0, 0, self._midnight_reset)))
        self.tasks.append(asyncio.create_task(self._schedule_daily(9, 0, self._morning_vix)))
        logger.info("[CoPAW] Scheduled tasks wired (Midnight Reset, Morning VIX)")

    def start_background(self):
        """CoPAW tasks are now running in the main asyncio loop."""
        self._running = True
        logger.info("[CoPAW] Running in async loop.")

    def stop(self):
        self._running = False
        for t in self.tasks:
            t.cancel()
