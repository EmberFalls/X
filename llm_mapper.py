"""
llm_mapper.py
LLM-backed NLP-to-Parameters mapper for SimuTrade (Version 2).
Uses Groq API (Llama 3) to replace the heuristic mapper.
Enforces strict JSON output matching the StrategyPayload pydantic schema.
Paper framing: "translation system" for retail users — NOT a prediction engine.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from pydantic import ValidationError

from schemas import StrategyPayload

# --- Groq client (pip install groq) ---
try:
    from groq import Groq

    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False

# ---------------------------------------------------------------------------
# Fixed registry constants
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
GROQ_MODEL = os.getenv("SIMUTRADE_GROQ_MODEL", "openai/gpt-oss-20b")

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

    if not _GROQ_AVAILABLE:
        payload = _heuristic_mapper(prompt, ticker, interval)
        payload["mapping_source"] = "heuristic_fallback"
        payload["fallback_reason"] = "groq_unavailable"
        return payload

    if not api_key:
        payload = _heuristic_mapper(prompt, ticker, interval)
        payload["mapping_source"] = "heuristic_fallback"
        payload["fallback_reason"] = "missing_api_key"
        return payload

    client = Groq(api_key=api_key, timeout=30.0, max_retries=0)
    user_message = f"User trading intent: {prompt}\nTicker hint: {ticker}\nInterval hint: {interval}"

    last_error = None
    fallback_reason = None

    for attempt in range(3):
        try:
            chat = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT.strip()},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,
                max_tokens=800,
            )
            raw = chat.choices[0].message.content.strip()
            payload = _parse_and_validate(raw, prompt, ticker, interval)
            payload["mapping_source"] = "llm"
            payload["llm_model"] = GROQ_MODEL
            return payload

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            last_error = str(e)
            fallback_reason = "llm_validation_failed"
            continue

        except Exception as e:
            last_error = str(e).lower()

            if "rate limit" in last_error or "429" in last_error:
                fallback_reason = "groq_rate_limited"
            elif "timeout" in last_error:
                fallback_reason = "groq_timeout"
            elif "401" in last_error or "unauthorized" in last_error or "invalid api key" in last_error:
                fallback_reason = "invalid_api_key"
            elif "503" in last_error or "unavailable" in last_error:
                fallback_reason = "groq_unavailable"
            else:
                fallback_reason = "llm_request_error"
            break

    payload = _heuristic_mapper(prompt, ticker, interval)
    payload["mapping_source"] = "heuristic_fallback"
    payload["fallback_reason"] = fallback_reason or "llm_validation_failed"
    payload["llm_error"] = last_error
    return payload


# ---------------------------------------------------------------------------
# JSON parsing + schema validation (pydantic-backed)
# ---------------------------------------------------------------------------
def _parse_and_validate(
        raw: str,
        original_prompt: str,
        ticker: str,
        interval: str,
) -> Dict[str, Any]:
    """
    Parse raw LLM output and validate against the StrategyPayload pydantic schema.
    Raises ValueError with a descriptive message on any schema mismatch, so the
    retry/fallback logic in suggest_strategy_llm() catches it the same way it
    always has.
    """
    # Strip markdown code fences if the model returns them despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()

    try:
        data: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output was not valid JSON: {exc}") from exc

    # Ensure user_intent always reflects the original prompt (non-negotiable for paper traceability)
    data["user_intent"] = original_prompt

    try:
        payload = StrategyPayload(**data)
    except ValidationError as exc:
        raise ValueError(f"LLM output failed schema validation: {exc}") from exc

    return payload.dict()
