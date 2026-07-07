from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

LOG_DIR = Path(os.getenv("SIMUTRADE_LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

NSE_BASKET = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BAJFINANCE.NS", "KOTAKBANK.NS",
]

MappingSource = Literal["llm", "heuristic_fallback", "manual"]

_TECH_LOG = LOG_DIR / "technical_eval.ndjson"
_TRADING_LOG = LOG_DIR / "trading_eval.ndjson"
_USABILITY_LOG = LOG_DIR / "usability_eval.ndjson"


def _write(path: Path, record: Dict[str, Any]) -> None:
    record.setdefault("logged_at", datetime.now(timezone.utc).isoformat())
    record.setdefault("session_id", os.getenv("SIMUTRADE_SESSION_ID", "default"))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def log_technical(
    prompt: str,
    mapping_source: MappingSource,
    schema_valid: bool,
    backtest_completed: bool,
    latency_ms: float,
    fallback_reason: Optional[str] = None,
    llm_model: Optional[str] = None,
    error: Optional[str] = None,
    expected_strategy: Optional[str] = None,
    produced_strategy: Optional[str] = None,
    strategy_match: Optional[bool] = None,
    ticker: Optional[str] = None,
    interval: Optional[str] = None,
) -> str:
    record_id = str(uuid.uuid4())[:8]
    _write(_TECH_LOG, {
        "record_id": record_id,
        "prompt": prompt,
        "mapping_source": mapping_source,
        "schema_valid": schema_valid,
        "backtest_completed": backtest_completed,
        "latency_ms": round(latency_ms, 2),
        "fallback_reason": fallback_reason,
        "llm_model": llm_model,
        "error": error,
        "expected_strategy": expected_strategy,
        "produced_strategy": produced_strategy,
        "strategy_match": strategy_match,
        "ticker": ticker,
        "interval": interval,
    })
    return record_id


def log_trading(
    record_id: str,
    ticker: str,
    strategy_id: str,
    mapping_source: MappingSource,
    metrics: Dict[str, Any],
    params_snapshot: Optional[Dict[str, Any]] = None,
) -> None:
    _write(_TRADING_LOG, {
        "record_id": record_id,
        "ticker": ticker,
        "strategy_id": strategy_id,
        "mapping_source": mapping_source,
        "total_return_pct": metrics.get("totalReturn"),
        "max_drawdown_pct": metrics.get("maxDrawdown"),
        "sharpe_ratio": metrics.get("sharpeRatio"),
        "win_rate_pct": metrics.get("winRate"),
        "total_trades": metrics.get("totalTrades"),
        "final_value": metrics.get("finalValue"),
        "buy_hold_value": metrics.get("buyHoldValue"),
        "params_snapshot": params_snapshot,
    })


def log_usability(
    flow_type: MappingSource,
    prompt: str,
    time_to_submit_sec: float,
    form_errors: int,
    apply_button_used: bool,
    backtest_triggered: bool,
    user_id: Optional[str] = None,
) -> None:
    _write(_USABILITY_LOG, {
        "flow_type": flow_type,
        "prompt": prompt,
        "time_to_submit_sec": round(time_to_submit_sec, 3),
        "form_errors": form_errors,
        "apply_button_used": apply_button_used,
        "backtest_triggered": backtest_triggered,
        "user_id": user_id or "anonymous",
    })


class TimedBlock:
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.ms = (time.perf_counter() - self._start) * 1000

    @property
    def seconds(self) -> float:
        return self.ms / 1000