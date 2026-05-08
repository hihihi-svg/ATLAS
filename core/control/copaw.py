"""
ATLAS CoPAW 
Cron-Operated Process Automation Wrapper — Powered by Alibaba AgentScope
Handles scheduled background tasks using an intelligent agentic workflow.
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
import os
from loguru import logger

# Alibaba AgentScope Imports
import agentscope
from agentscope.agent import AgentBase
from agentscope.message import Msg

from core.execution import circuit_breakers as cb
from core.memory.hermes import HERMESAgent

# Load API keys for AgentScope
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

class AtlasAutomationAgent(AgentBase):
    """An Alibaba AgentScope-based agent that manages ATLAS background tasks."""
    
    def __init__(self, name, model_config_name):
        super().__init__(
            name=name,
            sys_prompt="You are the ATLAS Automation Manager. Your role is to oversee the 24/7 autonomous operations of the trading system, including resets, reports, and risk refreshes.",
            model_config_name=model_config_name
        )

    def reply(self, x: dict = None) -> dict:
        """Required implementation for AgentBase."""
        return x

class CoPAW:
    def __init__(self, engine, signal_history):
        self.engine = engine
        self.signal_history = signal_history
        self._running = False
        self.tasks = []
        
        # Initialize AgentScope
        config_path = os.path.join(os.path.dirname(__file__), "agentscope_config.json")
        try:
            # Update placeholder in config with actual key
            with open(config_path, "r") as f:
                config = json.load(f)
                config[0]["api_key"] = OPENAI_API_KEY
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)
                
            agentscope.init(model_configs=config_path)
            self.agent = AtlasAutomationAgent(
                name="CoPAW_Manager",
                model_config_name="atlas_copaw_config"
            )
            logger.info("[CoPAW] Alibaba AgentScope initialized successfully.")
        except Exception as e:
            logger.error(f"[CoPAW] Failed to initialize AgentScope: {e}. Falling back to basic mode.")
            self.agent = None

    async def _midnight_reset(self):
        """Runs at 00:00 UTC."""
        logger.info("[CoPAW] 🕛 Midnight Reset Triggered")
        
        if self.agent:
            # Use AgentScope for intelligent reasoning before reset if needed
            msg = Msg(name="System", content="It is now midnight. Execute the daily reset protocol.")
            # self.agent(msg) # Optional: get agent thoughts
        
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
            logger.info(f"[CoPAW] CoPAW Agent scheduled task for {hour:02d}:{minute:02d} UTC (in {wait_seconds:.0f}s)")
            await asyncio.sleep(wait_seconds)
            
            if self._running:
                await coroutine()

    def setup_schedules(self):
        """Schedule the daily tasks via asyncio."""
        self.tasks.append(asyncio.create_task(self._schedule_daily(0, 0, self._midnight_reset)))
        self.tasks.append(asyncio.create_task(self._schedule_daily(9, 0, self._morning_vix)))
        logger.info("[CoPAW] Agentic schedules wired (Midnight Reset, Morning VIX)")

    def start_background(self):
        self._running = True
        logger.info("[CoPAW] Alibaba AgentScope manager running in async loop.")

    def stop(self):
        self._running = False
        for t in self.tasks:
            t.cancel()
