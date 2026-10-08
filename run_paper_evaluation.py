"""Reproducible 50-prompt x 5-ticker x 2-repeat evaluation runner."""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import backtester
import yfinance as yf
from llm_mapper import suggest_strategy_llm
from market_data import YFinanceProvider
from schemas import StrategyPayload
from strategy_assistant import suggest_strategy_from_prompt


BASE = Path(__file__).resolve().parent
PROMPTS_PATH = BASE / "evaluation_prompts_50.json"
TICKERS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
START_DATE = "2023-01-01"
END_DATE = "2024-12-31"
INTERVAL = "1d"
EXEC_DEFAULTS = {"initial_capital": 100000, "risk_percent": 2.0, "slippage_pct": 0.1, "transaction_cost_pct": 0.05}

# Keep yfinance's SQLite-backed cache inside the writable project workspace.
YFINANCE_CACHE = BASE / "tmp" / "yfinance_cache"
YFINANCE_CACHE.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YFINANCE_CACHE))


def load_project_environment() -> None:
    """Load local project key-value settings without logging their contents."""
    env_path = BASE / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def map_prompt(prompt: str, ticker: str, method: str) -> tuple[Dict[str, Any], float]:
    start = time.perf_counter()
    if method == "heuristic_fallback":
        payload = suggest_strategy_from_prompt(prompt, ticker, INTERVAL)
        payload["mapping_source"] = "heuristic_fallback"
    else:
        payload = suggest_strategy_llm(prompt, ticker, INTERVAL)
    return payload, round((time.perf_counter() - start) * 1000.0, 2)


def prepare_data() -> Dict[str, Any]:
    provider = YFinanceProvider()
    cache: Dict[str, Any] = {}
    for ticker in TICKERS:
        raw = provider.get_history(ticker, START_DATE, END_DATE, INTERVAL)
        cache[ticker] = raw
        print(f"[DATA] {ticker}: {len(raw)} rows")
    return cache


def payload_to_backtest_params(payload: Dict[str, Any], ticker: str) -> tuple[str | None, Dict[str, Any]]:
    strategy_id = payload.get("strategy_id")
    if not strategy_id:
        return None, {}
    entry = payload.get("entry_logic", {}) or {}
    exit_logic = payload.get("exit_logic", {}) or {}
    execution = payload.get("execution_rules", {}) or {}
    return strategy_id, {
        "fastMA": entry.get("fast_ma") if entry.get("fast_ma") is not None else 20,
        "slowMA": entry.get("slow_ma") if entry.get("slow_ma") is not None else 50,
        "mrK": entry.get("mr_k") if entry.get("mr_k") is not None else 2.0,
        "atrPeriod": 14,
        "initialCapital": execution.get("initial_capital", EXEC_DEFAULTS["initial_capital"]),
        "riskPercent": execution.get("risk_percent", EXEC_DEFAULTS["risk_percent"]),
        "stopLoss": exit_logic.get("stop_loss_pct", 2.0),
        "takeProfit": exit_logic.get("take_profit_pct", 6.0),
        "slippage": execution.get("slippage_pct", EXEC_DEFAULTS["slippage_pct"]),
        "transactionCost": execution.get("transaction_cost_pct", EXEC_DEFAULTS["transaction_cost_pct"]),
        "ticker": ticker, "startDate": START_DATE, "endDate": END_DATE, "interval": INTERVAL,
    }


def run_backtest(payload: Dict[str, Any], ticker: str, data: Any) -> tuple[Dict[str, Any], str | None]:
    strategy_id, params = payload_to_backtest_params(payload, ticker)
    if not strategy_id:
        return {}, "invalid_or_missing_strategy_id"
    if data.empty:
        return {}, "no_market_data"
    prepared = backtester.add_indicators(data.copy(), params).dropna(subset=["Close"])
    if len(prepared) < 20:
        return {}, "insufficient_indicator_history"
    equity, trades, final_cash, bh_shares, last_price = backtester.run_strategy(strategy_id, prepared, params)
    return backtester.calculate_metrics(equity, trades, params["initialCapital"], bh_shares, last_price), None


def write_evaluation_row(writer: csv.DictWriter, repeat: int, spec: Dict[str, Any], ticker: str, method: str, payload: Dict[str, Any] | None, latency: float | None, mapping_error: str | None, data: Any) -> None:
    base = {"evaluation_id": f"{method}_{repeat}_{spec['id']}_{ticker}", "requested_mapping_path": method, "repeat": repeat, "prompt_id": spec["id"], "prompt": spec["prompt"], "category": spec["category"], "difficulty": spec["difficulty"], "ticker": ticker, "interval": INTERVAL, "expected_strategy": spec["expected_strategy"], "expected_risk_profile": spec["expected_risk_profile"]}
    if mapping_error or payload is None:
        writer.writerow({**base, "schema_valid": False, "backtest_completed": False, "backtest_error": mapping_error})
        return
    strategy_id = payload.get("strategy_id")
    try:
        StrategyPayload.model_validate({key: payload[key] for key in StrategyPayload.model_fields if key in payload})
        schema_valid = True
    except Exception:
        schema_valid = False
    metrics, error = run_backtest(payload, ticker, data)
    writer.writerow({**base, "actual_mapping_source": payload.get("mapping_source", method), "produced_strategy": strategy_id, "produced_risk_profile": payload.get("risk_profile"), "strategy_match": strategy_id == spec["expected_strategy"], "risk_profile_match": payload.get("risk_profile") == spec["expected_risk_profile"], "schema_valid": schema_valid, "backtest_completed": bool(metrics), "latency_ms": latency, "fallback_reason": payload.get("fallback_reason"), "llm_model": payload.get("llm_model"), "backtest_error": error, "total_return_pct": metrics.get("totalReturn"), "max_drawdown_pct": metrics.get("maxDrawdown"), "sharpe_ratio": metrics.get("sharpeRatio"), "win_rate_pct": metrics.get("winRate"), "total_trades": metrics.get("totalTrades"), "final_value": metrics.get("finalValue"), "buy_hold_value": metrics.get("buyHoldValue")})


def run_parallel_llm(prompts: List[Dict[str, Any]], repeats: int, output: Path, fields: List[str], data_cache: Dict[str, Any], workers: int) -> None:
    tasks = [(repeat, spec, ticker) for repeat in range(1, repeats + 1) for spec in prompts for ticker in TICKERS]
    results: List[tuple[int, Dict[str, Any], str, Dict[str, Any] | None, float | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(map_prompt, spec["prompt"], ticker, "llm"): (repeat, spec, ticker) for repeat, spec, ticker in tasks}
        for index, future in enumerate(as_completed(pending), start=1):
            repeat, spec, ticker = pending[future]
            try:
                payload, latency = future.result()
                results.append((repeat, spec, ticker, payload, latency, None))
            except Exception as exc:
                results.append((repeat, spec, ticker, None, None, str(exc)))
            if index % 25 == 0 or index == len(tasks):
                print(f"[MAPPING] {index}/{len(tasks)} LLM calls completed", flush=True)
    results.sort(key=lambda item: (item[0], item[1]["id"], item[2]))
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, (repeat, spec, ticker, payload, latency, mapping_error) in enumerate(results, start=1):
            write_evaluation_row(writer, repeat, spec, ticker, "llm", payload, latency, mapping_error, data_cache[ticker])
            if index % 25 == 0 or index == len(results):
                print(f"[BACKTEST] {index}/{len(results)} rows completed", flush=True)
    print(f"Wrote {len(results)} evaluation rows to {output}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["heuristic_fallback", "llm"], required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_project_environment()
    prompts: List[Dict[str, Any]] = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    if len(prompts) != 50:
        raise ValueError("The evaluation protocol requires exactly 50 prompts.")
    data_cache = prepare_data()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["evaluation_id", "requested_mapping_path", "actual_mapping_source", "repeat", "prompt_id", "prompt", "category", "difficulty", "ticker", "interval", "expected_strategy", "expected_risk_profile", "produced_strategy", "produced_risk_profile", "strategy_match", "risk_profile_match", "schema_valid", "backtest_completed", "latency_ms", "fallback_reason", "llm_model", "backtest_error", "total_return_pct", "max_drawdown_pct", "sharpe_ratio", "win_rate_pct", "total_trades", "final_value", "buy_hold_value"]
    if args.method == "llm" and args.workers > 1:
        run_parallel_llm(prompts, args.repeats, args.output, fields, data_cache, args.workers)
        return
    count = 0
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for repeat in range(1, args.repeats + 1):
            for spec in prompts:
                for ticker in TICKERS:
                    count += 1
                    try:
                        payload, latency = map_prompt(spec["prompt"], ticker, args.method)
                        strategy_id = payload.get("strategy_id")
                        try:
                            StrategyPayload.model_validate({key: payload[key] for key in StrategyPayload.model_fields if key in payload})
                            schema_valid = True
                        except Exception:
                            schema_valid = False
                        metrics, error = run_backtest(payload, ticker, data_cache[ticker])
                        writer.writerow({
                            "evaluation_id": f"{args.method}_{repeat}_{spec['id']}_{ticker}", "requested_mapping_path": args.method,
                            "actual_mapping_source": payload.get("mapping_source", args.method), "repeat": repeat,
                            "prompt_id": spec["id"], "prompt": spec["prompt"], "category": spec["category"], "difficulty": spec["difficulty"],
                            "ticker": ticker, "interval": INTERVAL, "expected_strategy": spec["expected_strategy"],
                            "expected_risk_profile": spec["expected_risk_profile"], "produced_strategy": strategy_id,
                            "produced_risk_profile": payload.get("risk_profile"), "strategy_match": strategy_id == spec["expected_strategy"],
                            "risk_profile_match": payload.get("risk_profile") == spec["expected_risk_profile"], "schema_valid": schema_valid,
                            "backtest_completed": bool(metrics), "latency_ms": latency, "fallback_reason": payload.get("fallback_reason"),
                            "llm_model": payload.get("llm_model"), "backtest_error": error, "total_return_pct": metrics.get("totalReturn"),
                            "max_drawdown_pct": metrics.get("maxDrawdown"), "sharpe_ratio": metrics.get("sharpeRatio"),
                            "win_rate_pct": metrics.get("winRate"), "total_trades": metrics.get("totalTrades"),
                            "final_value": metrics.get("finalValue"), "buy_hold_value": metrics.get("buyHoldValue"),
                        })
                        print(f"[RUN {count}/500] {spec['id']} {ticker} repeat={repeat} strategy={strategy_id} valid={schema_valid} complete={bool(metrics)}")
                    except Exception as exc:
                        writer.writerow({"evaluation_id": f"{args.method}_{repeat}_{spec['id']}_{ticker}", "requested_mapping_path": args.method, "repeat": repeat, "prompt_id": spec["id"], "prompt": spec["prompt"], "category": spec["category"], "difficulty": spec["difficulty"], "ticker": ticker, "interval": INTERVAL, "expected_strategy": spec["expected_strategy"], "expected_risk_profile": spec["expected_risk_profile"], "schema_valid": False, "backtest_completed": False, "backtest_error": str(exc)})
                        print(f"[ERROR {count}/500] {spec['id']} {ticker}: {exc}")
    print(f"Wrote {count} evaluation rows to {args.output}")


if __name__ == "__main__":
    main()
