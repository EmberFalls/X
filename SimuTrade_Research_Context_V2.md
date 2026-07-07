# SimuTrade: Research Variant - Master Context Document

## 📌 Project Overview & Thesis
**SimuTrade** is being developed into a research paper targeting an IEEE student conference or an A-grade journal (e.g., IJCRT). 
**Paper Thesis:** *"Bridging the Gap in Retail Quantitative Finance: A Heuristic NLP-to-Parameters Mapping System for Algorithmic Trading."*

The academic novelty is **NOT** execution speed/latency or market prediction. The novelty is **Retail Accessibility & Decision Support**—translating unstructured natural language intent (e.g., "safe trend-following for large caps") into a structured, executable JSON strategy specification, which is then validated via a backtester and visualized for interpretability.

## 📂 Current Codebase State (Do NOT Rebuild)
The base infrastructure is perfectly functional and must not be cosmetically rebuilt:
- **Backend (FastAPI):** `main.py`, `backtester.py`, `market_data.py`, `optimizer.py`, `schemas.py`, `strategy_assistant.py` (Version 1 heuristic mapper).
- **Frontend (Vanilla JS/HTML/CSS):** Fully styled dashboard mapping prompts to the backtest form, live chart polling, and metrics display.

## 🚀 Version Plan & Scope
### **Version 1 (Currently Implemented):**
- Fixed Data Source (yfinance/local OHLCV cache).
- Fixed Strategy Registry: `golden_cross`, `mean_reversion`, `rsi_strategy`, `macd_crossover`, `momentum_breakout`.
- Rule-based / Heuristic NLP mapping (`strategy_assistant.py`).

### **Version 2 (Immediate Next Steps for the AI):**
- **LLM-Backed NLP Mapper:** Integrate **Groq API** or **HuggingFace API (Llama 3)** to replace/augment the heuristic mapper.
- **Prompt Engineering:** System prompt must enforce strict structured output matching the parameter schema below.
- **Live Chart Interpretability Layer:** Upgrade the live chart to show real-time strategy rationale, generated visual overlays (e.g., EMA lines, RSI bands), and side-by-side prompt-to-chart traceability.

## 🧩 Fixed Parameter Schema (Target Output for LLM)
The LLM integration must output EXACTLY this JSON structure:
```json
{
  "user_intent": "low risk trend-following strategy for large cap stocks",
  "strategy_id": "golden_cross",
  "ticker": "RELIANCE",
  "exchange": "NSE",
  "interval": "1d",
  "market_mode": "trend_following",
  "risk_profile": "low",
  "entry_logic": {
    "fast_ma": 20,
    "slow_ma": 50,
    "rsi_confirm": false,
    "macd_confirm": false
  },
  "exit_logic": {
    "stop_loss_pct": 2.0,
    "take_profit_pct": 6.0,
    "trailing_stop_pct": null
  },
  "execution_rules": {
    "initial_capital": 100000,
    "risk_percent": 2.0,
    "slippage_pct": 0.1,
    "transaction_cost_pct": 0.05
  },
  "assistant_rationale": "Selected a moving-average crossover because the prompt suggests a lower-risk trend-following approach."
}
```

## 📊 Experiment & Evaluation Plan (What we are measuring)
The paper requires empirical evaluation across 3 domains. Future coding tasks must help generate data for:
1. **Technical Evaluation:** Valid output rate, JSON schema compliance, backtest completion rate.
2. **Trading Evaluation:** Total return, Sharpe ratio, Max drawdown, Win rate across a fixed basket of NSE large-caps.
3. **Usability Evaluation:** Manual setup vs. Heuristic NLP vs. LLM NLP comparison (time taken, error reduction).

## 🤖 Instructions for AI in the New Chat
1. **Context Assumption:** The base backtester, UI, and data pipelines work. Do NOT refactor CSS, HTML, or basic API routes.
2. **Focus:** Only write code that implements the **Groq/Llama-3 LLM Endpoint**, the **Live Chart Interpretability Overlays/Rationale**, or scripts for **Experiment Data Logging**.
3. **Framing:** Always treat this as a "translation system" for retail users, not a "prediction engine".
