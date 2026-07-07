from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "experiment_config.json"


def load_experiment_config(path: str | None = None) -> Dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Experiment config file not found: {config_path}")
    return json.loads(config_path.read_text(encoding="utf-8"))


def env_or_default(name: str, default: Any) -> Any:
    return os.getenv(name, default)


def get_runtime_paths(config: Dict[str, Any]) -> Dict[str, str]:
    proto = config.get("evaluation_protocol", {})
    return {
        "log_dir": str(env_or_default("SIMUTRADE_LOG_DIR", proto.get("log_dir", "logs"))),
        "output_dir": str(env_or_default("SIMUTRADE_OUTPUT_DIR", proto.get("output_dir", "outputs"))),
        "benchmark_prompt_file": str(proto.get("benchmark_prompt_file", "benchmark_prompts.json")),
        "benchmark_ticker_file": str(proto.get("benchmark_ticker_file", "benchmark_tickers.json")),
    }


def get_runtime_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    proto = config.get("evaluation_protocol", {})
    return {
        "start_date": proto.get("start_date", "2023-01-01"),
        "end_date": proto.get("end_date", "2024-12-31"),
        "interval": env_or_default("SIMUTRADE_DEFAULT_INTERVAL", proto.get("default_interval", "1d")),
        "exchange": env_or_default("SIMUTRADE_DEFAULT_EXCHANGE", proto.get("exchange", "NSE")),
        "methods": proto.get("methods", ["heuristic_fallback", "llm"]),
    }


def get_execution_defaults() -> Dict[str, float]:
    return {
        "initial_capital": float(env_or_default("SIMUTRADE_DEFAULT_INITIAL_CAPITAL", 100000)),
        "risk_percent": float(env_or_default("SIMUTRADE_DEFAULT_RISK_PERCENT", 2.0)),
        "stop_loss_pct": float(env_or_default("SIMUTRADE_DEFAULT_STOP_LOSS_PCT", 2.0)),
        "take_profit_pct": float(env_or_default("SIMUTRADE_DEFAULT_TAKE_PROFIT_PCT", 6.0)),
        "slippage_pct": float(env_or_default("SIMUTRADE_DEFAULT_SLIPPAGE_PCT", 0.1)),
        "transaction_cost_pct": float(env_or_default("SIMUTRADE_DEFAULT_TRANSACTION_COST_PCT", 0.05)),
    }