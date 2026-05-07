# ATLAS System Design

## 1. Architecture Overview
ATLAS (Autonomous Trading Logic & Advisory System) is a multi-agent crypto trading engine. Uses FastAPI backend and vanilla web frontend. 5 AI agents vote on trade signals.

## 2. Core Modules
- **Data Layer (`core/data`)**: Fetch live crypto prices via CCXT/yfinance. Calculate indicators using Pandas-TA.
- **Agent Layer (`core/agents`)**:
  - `Technician`: Tech analysis (RSI, MACD, EMAs).
  - `Analyst`: News/sentiment scrape (GPT-4o).
  - `Risk`: Stop-loss / position size (ATR).
  - `Contrarian`: Anti-herd logic.
  - `RL Strategist`: Stable-Baselines3 PPO model for pattern recognition.
- **Consensus Engine (`core/control`)**: Aggregates agent votes. Requires threshold to execute trade.
- **Memory/HERMES (`core/memory`)**: Stores trade history (`memory_*.json`, `meta_weights.json`). Adjusts strategy weights daily.
- **Execution (`core/execution`)**: Paper/live trade execution, stop manager, circuit breakers.

## 3. Data Flow
1. Cron/Schedule triggers tick.
2. Market data fetched → indicators calculated.
3. State passed to 5 Agents.
4. Agents output signals (Long/Short/Hold + Confidence).
5. Consensus Engine aggregates votes based on HERMES DNA weights.
6. Execution Engine routes to Paper/Live API.
7. Post-trade analysis by HERMES.

## 4. Tech Stack
- **API/Server**: Python, FastAPI, Uvicorn, Asyncio.
- **AI Models**: GPT-4o, PPO.
- **Frontend**: HTML5, CSS3 (Glassmorphism), JS (WebSockets). Served by `core/control/api.py`.
- **State/Cache**: Redis + Local JSON files.
