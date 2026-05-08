# 📝 AI Usage Declaration Form

## 1. Team Details
**Team Name**: Team hihihi-svg
**Project / Product Name**: ATLAS (Autonomous Trading Logic & Advisory System)
**Organization / Institution (if any)**: Samsung PRISM Hackathon
**Submission Date**: 2026-05-08

---

## 2. AI Usage Declaration
**Did your team use any Artificial Intelligence (AI) in developing this project?** **YES**

---

## 3. Purpose of AI Usage (Brief Details)
*   **Idea generation / brainstorming**: Used to conceptualize the "Multi-Agent Consensus" model and HERMES architecture.
*   **Code generation or assistance**: Extensive use of Antigravity (Gemini 3 Flash) for backend logic, FastAPI endpoints, and documentation.
*   **UI / UX design**: AI-assisted styling for the Dark-Mode Glassmorphism dashboard.
*   **Content creation**: GPT-4o generates the daily "HERMES Post-Mortem" reports.
*   **Data analysis**: PPO (Reinforcement Learning) models and Mistral-7B provide live market sentiment and indicator interpretation.
*   **Testing / debugging**: AI-driven simulation scripts used to audit 365-day historical performance.

---

## 4. Feature Origin Classification

### Feature 1: 5-Agent Consensus Engine
*   **Origin**: **Both**
*   **Description**: 
    *   **Tools**: OpenAI GPT-4o-mini, Mistral-7B.
    *   **Prompt**: *"Analyze these 5 technical indicators and news sentiment. Provide a trade recommendation with a confidence score and detailed reasoning."*
    *   **Output**: Structured JSON containing trade decision, agent scores, and rationale.
    *   **Other**: Automated Telegram bot integration (Moltbot) and background agentic workflow management using the **Alibaba AgentScope (CoPaw)** framework.
    *   **Modification**: Integrated into a custom voting-weight system (Strategy DNA) that evolves over time.

### Feature 2: HERMES Hindsight Agent
*   **Origin**: **AI-Generated**
*   **Description**: 
    *   **Tools**: OpenAI GPT-4o.
    *   **Prompt**: *"Review these 20 trades from today. Identify the top 3 lessons learned and suggest how to adjust the technician and analyst weights for tomorrow."*
    *   **Output**: Comprehensive markdown report and weight updates for the consensus engine.
    *   **Modification**: Constrained by local capital and risk management boundaries.

### Feature 3: RL Strategist (PPO Model)
*   **Origin**: **AI-Generated**
*   **Description**: 
    *   **Tools**: Stable-Baselines3 (PPO), Python.
    *   **Prompt**: N/A (Standard RL training loop on historical price data).
    *   **Output**: Serialized model file that outputs action probabilities (Buy/Sell/Hold).
    *   **Modification**: Added a custom reward function that penalizes drawdown more heavily than missed profit.

### Feature 4: Live XAI Dashboard (Explainable AI)
*   **Origin**: **Both**
*   **Description**: 
    *   **Tools**: Mistral-7B-Instruct (via Hugging Face), Gemini Flash.
    *   **Prompt**: *"You are a trading assistant. Explain these indicators (RSI: 33, MACD: -1.2) to a non-technical user in one sentence."*
    *   **Output**: Live, plain-English tooltips and status updates.
    *   **Modification**: Tailored to crypto-specific terminology and 15-minute chart intervals.

---

## 5. Ethical & Compliance Confirmation
*   **AI usage complies with guidelines and policies**: **YES**
*   **No proprietary or copyrighted data misused**: **I AGREE**

---

## 6. Declaration & Sign-Off
**Name of Team Representative**: [Lalantika hihihi-svg]
**Role**: Lead Developer / Architect
**Signature**: *Digitally Signed (ATLAS-AUTH-2026)*
**Date**: 2026-05-08
