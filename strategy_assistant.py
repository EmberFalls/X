"""
strategy_assistant.py
Offline keyword-based strategy suggestion engine.
No external AI API. No ML model. Fully deterministic.
"""
from __future__ import annotations
from typing import Any, Dict

_CATALOGUE: Dict[str, Dict[str, Any]] = {
    "safe": {
        "strategy_id": "golden_cross",
        "market_mode": "trend_following",
        "risk_profile": "low",
        "entry_logic": {"fast_ma": 50, "slow_ma": 200, "rsi_buy": None, "rsi_sell": None, "mr_k": None, "rsi_confirm": False, "macd_confirm": False},
        "exit_logic": {"stop_loss_pct": 2.0, "take_profit_pct": 6.0, "trailing_stop_pct": None},
        "execution_rules": {"initial_capital": 100000, "risk_percent": 1.0, "slippage_pct": 0.1, "transaction_cost_pct": 0.05},
        "rationale": "Classic Golden Cross (EMA50/EMA200). Low trade frequency, tight risk management — best for long-term investors.",
    },
    "aggressive": {
        "strategy_id": "momentum_breakout",
        "market_mode": "momentum",
        "risk_profile": "high",
        "entry_logic": {"fast_ma": 10, "slow_ma": 30, "rsi_buy": None, "rsi_sell": None, "mr_k": None, "rsi_confirm": False, "macd_confirm": False},
        "exit_logic": {"stop_loss_pct": 3.0, "take_profit_pct": 10.0, "trailing_stop_pct": None},
        "execution_rules": {"initial_capital": 100000, "risk_percent": 3.0, "slippage_pct": 0.1, "transaction_cost_pct": 0.05},
        "rationale": "Momentum Breakout on short MAs. High-frequency entries capturing strong moves — for active traders with higher risk tolerance.",
    },
    "mean": {
        "strategy_id": "mean_reversion",
        "market_mode": "mean_reversion",
        "risk_profile": "medium",
        "entry_logic": {"fast_ma": 20, "slow_ma": 50, "rsi_buy": None, "rsi_sell": None, "mr_k": 2.0, "rsi_confirm": False, "macd_confirm": False},
        "exit_logic": {"stop_loss_pct": 1.5, "take_profit_pct": 4.0, "trailing_stop_pct": None},
        "execution_rules": {"initial_capital": 100000, "risk_percent": 2.0, "slippage_pct": 0.1, "transaction_cost_pct": 0.05},
        "rationale": "Bollinger Band mean reversion. Buys oversold, sells overbought — best in choppy/sideways markets.",
    },
    "trend": {
        "strategy_id": "golden_cross",
        "market_mode": "trend_following",
        "risk_profile": "medium",
        "entry_logic": {"fast_ma": 20, "slow_ma": 50, "rsi_buy": None, "rsi_sell": None, "mr_k": None, "rsi_confirm": False, "macd_confirm": False},
        "exit_logic": {"stop_loss_pct": 2.0, "take_profit_pct": 6.0, "trailing_stop_pct": None},
        "execution_rules": {"initial_capital": 100000, "risk_percent": 2.0, "slippage_pct": 0.1, "transaction_cost_pct": 0.05},
        "rationale": "Short-term Golden Cross (EMA20/EMA50). Faster signals on daily timeframe — balanced trend-following.",
    },
    "rsi": {
        "strategy_id": "rsi_strategy",
        "market_mode": "reversal",
        "risk_profile": "medium",
        "entry_logic": {"fast_ma": 14, "slow_ma": 50, "rsi_buy": 30.0, "rsi_sell": 70.0, "mr_k": None, "rsi_confirm": True, "macd_confirm": False},
        "exit_logic": {"stop_loss_pct": 2.0, "take_profit_pct": 5.0, "trailing_stop_pct": None},
        "execution_rules": {"initial_capital": 100000, "risk_percent": 2.0, "slippage_pct": 0.1, "transaction_cost_pct": 0.05},
        "rationale": "RSI Bounce strategy. Enters on oversold (< 30), exits on overbought (> 70) — good for volatile equities.",
    },
    "macd": {
        "strategy_id": "macd_crossover",
        "market_mode": "trend_following",
        "risk_profile": "medium",
        "entry_logic": {"fast_ma": 12, "slow_ma": 26, "rsi_buy": None, "rsi_sell": None, "mr_k": None, "rsi_confirm": False, "macd_confirm": True},
        "exit_logic": {"stop_loss_pct": 2.5, "take_profit_pct": 7.0, "trailing_stop_pct": None},
        "execution_rules": {"initial_capital": 100000, "risk_percent": 2.5, "slippage_pct": 0.1, "transaction_cost_pct": 0.05},
        "rationale": "MACD Crossover. Uses histogram transitions as entry/exit triggers — balances momentum and trend confirmation.",
    },
}

_RULES = [
    ("safe", ["safe", "long term", "long-term", "conservative", "low risk", "slow"]),
    ("aggressive", ["aggressive", "scalp", "momentum", "high frequency", "fast", "short term"]),
    ("mean", ["mean", "reversion", "bollinger", "range", "sideways", "choppy"]),
    ("rsi", ["rsi", "oversold", "overbought", "bounce", "reversal"]),
    ("macd", ["macd", "signal line", "histogram", "divergence"]),
]

def _classify(prompt: str) -> str:
    p = prompt.lower()
    for key, keywords in _RULES:
        if any(kw in p for kw in keywords):
            return key
    return "trend"

def suggest_strategy_from_prompt(prompt: str, ticker: str = "RELIANCE.NS", interval: str = "1d") -> Dict[str, Any]:
    key = _classify(prompt)
    cfg = _CATALOGUE[key]
    return {
        "user_intent": prompt,
        "strategy_id": cfg["strategy_id"],
        "ticker": ticker,
        "exchange": "AUTO",
        "interval": interval,
        "market_mode": cfg["market_mode"],
        "risk_profile": cfg["risk_profile"],
        "entry_logic": cfg["entry_logic"],
        "exit_logic": cfg["exit_logic"],
        "execution_rules": cfg["execution_rules"],
        "assistant_rationale": cfg["rationale"],
    }

def validate_strategy_payload(payload: Dict[str, Any]) -> None:
    required = ["strategy_id", "ticker", "entry_logic", "exit_logic", "execution_rules"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"Strategy payload missing keys: {missing}")
    valid_ids = {"golden_cross", "mean_reversion", "rsi_strategy", "macd_crossover", "momentum_breakout"}
    if payload["strategy_id"] not in valid_ids:
        raise ValueError(f"Unknown strategy_id: {payload['strategy_id']}")