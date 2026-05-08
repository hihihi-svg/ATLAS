# 🤖 AI & Model Disclosure

This document provides a comprehensive disclosure of all Artificial Intelligence models, autonomous agents, and automated decision-making engines used within the **ATLAS (Autonomous Trading Logic & Advisory System)** ecosystem.

---

## 🧠 1. Core Language Models (LLMs)
ATLAS leverages state-of-the-art LLMs for reasoning, sentiment analysis, and executive decision-making.

| Model | Role | Implementation |
| :--- | :--- | :--- |
| **OpenAI GPT-4o-mini** | Primary Reasoning Engine | Powering the `Analyst` agent (news/social sentiment) and the `Judge` (consensus logic). |
| **OpenAI GPT-4o** | Executive Strategy | Used by **HERMES** for daily post-mortem analysis and strategy evolution. |
| **Mistral-7B-Instruct-v0.3** | Real-Time XAI | Running via Hugging Face Inference API to provide plain-English "XAI" explanations for technical indicators on the dashboard. |
| **Gemini 1.5 Flash** | Live Market Inference | (Optional/Experimental) Used for real-time regime-specific reasoning and visual chart interpretation. |

---

## 🤖 2. Autonomous Agent Pipeline
ATLAS utilizes a **Multi-Agent Consensus Model** where specialized agents deliberate on every trade signal.

1.  **The Technician**: A deterministic agent using **Pandas-TA** to analyze momentum (RSI), trend (EMA), and volatility (Bollinger Bands).
2.  **The Analyst**: An LLM-driven agent that processes live news feeds and social sentiment to gauge market "mood."
3.  **The Risk Agent**: A mathematical agent calculating ATR-based Stop-Losses and dynamic Position Sizing.
4.  **The Contrarian**: A "Skeptic" agent that challenges the consensus to prevent herd mentality and ensures volume (RVOL) confirmation.
5.  **The RL Strategist**: A Reinforcement Learning agent using a **PPO (Proximal Policy Optimization)** model trained on historical price action.
6.  **HERMES (Hindsight Agent)**: An autonomous memory agent that audits daily performance and updates the "Strategy DNA" weights.

---

## 📈 3. Machine Learning Frameworks
*   **Stable-Baselines3**: Used for training and executing the Reinforcement Learning (PPO) models in the `RL Strategist`.
*   **Scikit-learn**: (Internal) Used for basic regime clustering and signal normalization.
*   **Pandas-TA**: Used for high-fidelity technical indicator generation.

---

## 🛡️ 4. Safety & Ethics
*   **Circuit Breakers**: Automated safety protocols that halt trading during extreme volatility (VIX spikes) or excessive daily loss.
*   **Human-in-the-Loop**: The dashboard provides a manual "Emergency Halt" button for user override.
*   **Transparency (XAI)**: Every AI decision is logged with the specific reasoning used by the agents, visible on the live dashboard.

---

**Disclosure Status**: *Hackathon Ready / Verified*
**Last Updated**: 2026-05-08
