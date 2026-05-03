# 🏛️ ATLAS: Autonomous Trading Logic & Advisory System
**Hackathon Edition — 100% Agent-Driven Decision Engine**

ATLAS is a next-generation AI trading advisory system built for the crypto markets. Unlike traditional bots that follow rigid rules, ATLAS uses a **Multi-Agent Consensus Model** to navigate market volatility with human-like reasoning and machine-level speed.

---

## 🚀 Key Features

### 1. 🤖 5-Agent Consensus Pipeline
Every trade signal is the result of a rigorous voting process between five specialized AI agents:
*   **The Technician**: Analyzes RSI, MACD, and EMAs for momentum and trend.
*   **The Analyst**: Scrapes live news and social sentiment to gauge market "mood".
*   **The Risk Agent**: Mathematically calculates Stop-Loss and Position Sizing based on ATR (Volatility).
*   **The Contrarian**: Acts as the skeptic, challenging the group to prevent "herd mentality" errors.
*   **The RL Strategist**: Uses a PPO Reinforcement Learning model to find hidden patterns in price action.

### 2. 🧠 HERMES Memory Agent
The system doesn't just trade; it **learns**. At the end of every day, the `HERMES` hindsight agent:
*   Analyzes every trade taken.
*   Generates a comprehensive **Daily Market Report**.
*   Evolves the system's "Strategy DNA" to adapt to tomorrow's market.

### 3. 📊 Real-Time Dashboard
A premium, dark-mode interface providing:
*   Live 5-agent voting logs.
*   Interactive chart indicators (RSI, MACD, Volume).
*   One-click **HERMES Authenticity Reports**.

---

## 🛠️ Technology Stack
*   **Backend**: Python, FastAPI, Asyncio
*   **AI/ML**: OpenAI GPT-4o, Stable-Baselines3 (PPO), Hugging Face Inference API
*   **Data**: CCXT (Binance/Coinbase), Pandas-TA, Redis
*   **Frontend**: Vanilla HTML5, CSS3 (Glassmorphism), JavaScript (Real-time WebSockets/Polling)

---

## 🏁 Quick Start

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   Rename `.env.example` to `.env` and add your `OPENAI_API_KEY`.

3. **Launch the System**:
   ```bash
   python run_live.py
   ```
   Access the dashboard at: `http://localhost:8000`

---

## 📈 Authenticity Verification
To verify the system's performance on real historical trends, run the 60-day backtest simulation:
```bash
python tests/test_day6.py
```
This generates a full performance report demonstrating ATLAS's edge in real-world market conditions.
