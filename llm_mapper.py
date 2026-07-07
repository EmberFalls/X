"""
llm_mapper.py
LLM-backed NLP-to-Parameters mapper for SimuTrade (Version 2).
Uses Groq API (Llama 3) to replace the heuristic mapper.
Enforces strict JSON output matching the fixed StrategyPayload schema.
Paper framing: "translation system" for retail users — NOT a prediction engine.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

# --- Groq client (pip install groq) ---
try:
    from groq import Groq
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False

# ---------------------------------------------------------------------------
# Fixed registry and schema constants
# ---------------------------------------------------------------------------
VALID_STRATEGY_IDS = {
    "golden_cross",
    "mean_reversion",
    "rsi_strategy",
    "macd_crossover",
    "momentum_breakout",
}

VALID_MARKET_MODES = {"trend_following", "mean_reversion", "momentum", "reversal"}
VALID_RISK_PROFILES = {"low", "medium", "high"}
VALID_INTERVALS = {"1m", "5m", "15m", "1h", "1d"}
VALID_EXCHANGES = {"NSE", "BSE", "AUTO"}

# ---------------------------------------------------------------------------
# System prompt — strict JSON enforcement
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """
You are a quantitative strategy mapping engine for a retail algorithmic trading research system called SimuTrade.
Your ONLY job is to translate a user's natural language trading intent into a structured, executable JSON strategy specification.

You are NOT a market predictor. You do NOT forecast prices or returns.
You ARE a "translation system" — you map user intent to a valid, backtestable strategy configuration.

You MUST return ONLY a single JSON object — no markdown, no commentary, no explanation outside the JSON.
The JSON MUST conform exactly to this schema:

{
  "user_intent": "<original user prompt verbatim>",
  "strategy_id": "<one of: golden_cross | mean_reversion | rsi_strategy | macd_crossover | momentum_breakout>",
  "ticker": "<ticker symbol, e.g. RELIANCE.NS, TCS.NS, INFY.NS>",
  "exchange": "<one of: NSE | BSE | AUTO>",
  "interval": "<one of: 1m | 5m | 15m | 1h | 1d>",
  "market_mode": "<one of: trend_following | mean_reversion | momentum | reversal>",
  "risk_profile": "<one of: low | medium | high>",
  "entry_logic": {
    "fast_ma": <integer or null>,
    "slow_ma": <integer or null>,
    "rsi_buy": <float or null>,
    "rsi_sell": <float or null>,
    "mr_k": <float or null>,
    "rsi_confirm": <true | false>,
    "macd_confirm": <true | false>
  },
  "exit_logic": {
    "stop_loss_pct": <float>,
    "take_profit_pct": <float>,
    "trailing_stop_pct": <float or null>
  },
  "execution_rules": {
    "initial_capital": <float>,
    "risk_percent": <float>,
    "slippage_pct": <float>,
    "transaction_cost_pct": <float>
  },
  "assistant_rationale": "<1-2 sentence plain-English explanation of why this strategy fits the user's intent>"
}

Strategy selection rules:
- "golden_cross" → trend-following, safe/long-term, moving-average crossover intent
- "mean_reversion" → sideways/choppy market, bollinger bands, buy dip/sell rally intent
- "rsi_strategy" → RSI-based, oversold/overbought, reversal/bounce intent
- "macd_crossover" → MACD, signal-line, histogram, momentum-with-confirmation intent
- "momentum_breakout" → breakout, aggressive, high-frequency, scalping intent

Risk defaults by risk_profile:
- low:    stop_loss_pct=2.0, take_profit_pct=6.0,  risk_percent=1.0
- medium: stop_loss_pct=2.5, take_profit_pct=7.0,  risk_percent=2.0
- high:   stop_loss_pct=3.0, take_profit_pct=10.0, risk_percent=3.0

If the user does not specify a ticker, default to "RELIANCE.NS" and exchange "NSE".
If the user does not specify an interval, default to "1d".
If the user does not specify capital, default initial_capital to 100000.
Always set slippage_pct=0.1 and transaction_cost_pct=0.05 unless user specifies otherwise.

RETURN ONLY THE JSON. NO OTHER TEXT.
"""

# ---------------------------------------------------------------------------
# Fallback: import heuristic mapper as safety net
# ---------------------------------------------------------------------------
from strategy_assistant import suggest_strategy_from_prompt as _heuristic_mapper


# ---------------------------------------------------------------------------
# Core LLM mapping function
# ---------------------------------------------------------------------------
def suggest_strategy_llm(
    prompt: str,
    ticker: str = "RELIANCE.NS",
    interval: str = "1d",
    groq_api_key: str | None = None,
) -> Dict[str, Any]:
    """
    Maps a natural-language trading intent to a StrategyPayload JSON using Groq/Llama-3.

    Falls back to the heuristic mapper if:
    - Groq is not available (package not installed)
    - API key is missing
    - LLM response fails schema validation after retries
    Returns a payload dict identical in shape to the heuristic mapper output,
    plus a 'mapping_source' key ("llm" | "heuristic_fallback") for experiment logging.
    """
    api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")

    if not _GROQ_AVAILABLE or not api_key:
        payload = _heuristic_mapper(prompt, ticker, interval)
        payload["mapping_source"] = "heuristic_fallback"
        payload["fallback_reason"] = "groq_unavailable_or_no_api_key"
        return payload

    client = Groq(api_key=api_key)
    user_message = f"User trading intent: {prompt}\nTicker hint: {ticker}\nInterval hint: {interval}"

    last_error = None
    for attempt in range(3):  # up to 3 retries for malformed output
        try:
            chat = client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT.strip()},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,          # low temp → deterministic, schema-compliant output
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            raw = chat.choices[0].message.content.strip()
            payload = _parse_and_validate(raw, prompt, ticker, interval)
            payload["mapping_source"] = "llm"
            payload["llm_model"] = "llama3-70b-8192"
            return payload

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            last_error = str(e)
            continue
        except Exception as e:
            # API error (rate limit, network, etc.) — break and fallback
            last_error = str(e)
            break

    # All retries exhausted → heuristic fallback
    payload = _heuristic_mapper(prompt, ticker, interval)
    payload["mapping_source"] = "heuristic_fallback"
    payload["fallback_reason"] = last_error or "llm_validation_failed"
    return payload


# ---------------------------------------------------------------------------
# JSON parsing + schema validation
# ---------------------------------------------------------------------------
def _parse_and_validate(
    raw: str,
    original_prompt: str,
    ticker: str,
    interval: str,
) -> Dict[str, Any]:
    """
    Parse raw LLM output and validate against the fixed StrategyPayload schema.
    Raises ValueError with a descriptive message on any schema mismatch.
    """
    # Strip markdown code fences if the model returns them despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()

    data: Dict[str, Any] = json.loads(raw)

    # --- Top-level required keys ---
    required_top = [
        "user_intent", "strategy_id", "ticker", "exchange", "interval",
        "market_mode", "risk_profile", "entry_logic", "exit_logic",
        "execution_rules", "assistant_rationale",
    ]
    missing = [k for k in required_top if k not in data]
    if missing:
        raise ValueError(f"LLM output missing top-level keys: {missing}")

    # --- Enum validation ---
    if data["strategy_id"] not in VALID_STRATEGY_IDS:
        raise ValueError(f"Invalid strategy_id: {data['strategy_id']}")
    if data["market_mode"] not in VALID_MARKET_MODES:
        raise ValueError(f"Invalid market_mode: {data['market_mode']}")
    if data["risk_profile"] not in VALID_RISK_PROFILES:
        raise ValueError(f"Invalid risk_profile: {data['risk_profile']}")
    if data["interval"] not in VALID_INTERVALS:
        raise ValueError(f"Invalid interval: {data['interval']}")
    if data["exchange"] not in VALID_EXCHANGES:
        raise ValueError(f"Invalid exchange: {data['exchange']}")

    # --- Nested key validation ---
    entry_required = ["fast_ma", "slow_ma", "rsi_buy", "rsi_sell", "mr_k", "rsi_confirm", "macd_confirm"]
    exit_required = ["stop_loss_pct", "take_profit_pct", "trailing_stop_pct"]
    exec_required = ["initial_capital", "risk_percent", "slippage_pct", "transaction_cost_pct"]

    for key in entry_required:
        if key not in data["entry_logic"]:
            raise ValueError(f"entry_logic missing key: {key}")
    for key in exit_required:
        if key not in data["exit_logic"]:
            raise ValueError(f"exit_logic missing key: {key}")
    for key in exec_required:
        if key not in data["execution_rules"]:
            raise ValueError(f"execution_rules missing key: {key}")

    # --- Type coercion safety ---
    el = data["entry_logic"]
    xl = data["exit_logic"]
    er = data["execution_rules"]

    el["fast_ma"] = int(el["fast_ma"]) if el["fast_ma"] is not None else None
    el["slow_ma"] = int(el["slow_ma"]) if el["slow_ma"] is not None else None
    el["rsi_buy"] = float(el["rsi_buy"]) if el["rsi_buy"] is not None else None
    el["rsi_sell"] = float(el["rsi_sell"]) if el["rsi_sell"] is not None else None
    el["mr_k"] = float(el["mr_k"]) if el["mr_k"] is not None else None
    el["rsi_confirm"] = bool(el["rsi_confirm"])
    el["macd_confirm"] = bool(el["macd_confirm"])

    xl["stop_loss_pct"] = float(xl["stop_loss_pct"])
    xl["take_profit_pct"] = float(xl["take_profit_pct"])
    xl["trailing_stop_pct"] = float(xl["trailing_stop_pct"]) if xl["trailing_stop_pct"] is not None else None

    er["initial_capital"] = float(er["initial_capital"])
    er["risk_percent"] = float(er["risk_percent"])
    er["slippage_pct"] = float(er["slippage_pct"])
    er["transaction_cost_pct"] = float(er["transaction_cost_pct"])

    # Ensure user_intent always reflects the original prompt (non-negotiable for paper traceability)
    data["user_intent"] = original_prompt

    return data