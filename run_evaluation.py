from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import backtester
from market_data import MarketDataProvider, YFinanceProvider
from llm_mapper import suggest_strategy_llm, VALID_STRATEGY_IDS
from strategy_assistant import suggest_strategy_from_prompt
from experiment_logger import log_technical, log_trading, log_usability, NSE_BASKET
from config_loader import (
    load_experiment_config,
    get_runtime_paths,
    get_runtime_defaults,
    get_execution_defaults,
)

provider: MarketDataProvider = YFinanceProvider()
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STRATEGY_REGISTRY = sorted(VALID_STRATEGY_IDS)


def resolve_strategy_registry(cfg: Dict[str, Any]) -> List[str]:
    registry = cfg.get("strategy_registry") or DEFAULT_STRATEGY_REGISTRY
    return [str(x) for x in registry]


def load_benchmarks(cfg: Dict[str, Any], paths: Dict[str, str]) -> Dict[str, Any]:
    bench_prompts = cfg.get("benchmark_prompts", [])
    bench_tickers = cfg.get("benchmark_tickers", cfg.get("nse_basket", NSE_BASKET))
    return {"prompts": bench_prompts, "tickers": bench_tickers}


def run_single_mapping(
        prompt: str,
        ticker: str,
        interval: str,
        method: str,
) -> Tuple[Dict[str, Any], float]:
    start = time.perf_counter()
    if method == "heuristic_fallback":
        payload = suggest_strategy_from_prompt(prompt, ticker, interval)
        payload["mapping_source"] = "heuristic_fallback"
    elif method == "llm":
        payload = suggest_strategy_llm(prompt, ticker, interval)
    else:
        raise ValueError(f"Unknown method: {method}")
    latency_ms = (time.perf_counter() - start) * 1000.0
    return payload, latency_ms


def payload_to_backtest_params(
        ticker: str,
        interval: str,
        start_date: str,
        end_date: str,
        payload: Dict[str, Any],
        exec_defaults: Dict[str, float],
) -> Tuple[Optional[str], Dict[str, Any]]:
    strategy_id = payload.get("strategy_id")
    if not strategy_id or strategy_id not in VALID_STRATEGY_IDS:
        return None, {}

    entry = payload.get("entry_logic", {}) or {}
    exit_l = payload.get("exit_logic", {}) or {}
    exec_r = payload.get("execution_rules", {}) or {}

    params = {
        "fastMA": entry.get("fast_ma") if entry.get("fast_ma") is not None else 20,
        "slowMA": entry.get("slow_ma") if entry.get("slow_ma") is not None else 50,
        "mrK": entry.get("mr_k") if entry.get("mr_k") is not None else 2.0,
        "atrPeriod": 14,
        "initialCapital": exec_r.get("initial_capital", exec_defaults["initial_capital"]),
        "riskPercent": exec_r.get("risk_percent", exec_defaults["risk_percent"]),
        "stopLoss": exit_l.get("stop_loss_pct", 2.0),
        "takeProfit": exit_l.get("take_profit_pct", exec_defaults["take_profit_pct"]),
        "slippage": exec_r.get("slippage_pct", exec_defaults["slippage_pct"]),
        "transactionCost": exec_r.get("transaction_cost_pct", exec_defaults["transaction_cost_pct"]),
        "ticker": ticker,
        "startDate": start_date,
        "endDate": end_date,
        "interval": interval,
    }
    return strategy_id, params


def run_backtest_for_payload(
        ticker: str,
        interval: str,
        start_date: str,
        end_date: str,
        payload: Dict[str, Any],
        exec_defaults: Dict[str, float],
) -> Tuple[Dict[str, Any], Optional[str]]:
    strategy_id, params = payload_to_backtest_params(
        ticker=ticker,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
        payload=payload,
        exec_defaults=exec_defaults,
    )
    if not strategy_id:
        return {}, "invalid_or_missing_strategy_id"

    raw = provider.get_history(ticker, start_date, end_date, interval)
    if raw.empty:
        return {}, "no_market_data"

    data = backtester.add_indicators(raw.copy(), params).dropna(subset=["Close"])
    if len(data) < 20:
        return {}, "insufficient_indicator_history"

    equity, trades, final_cash, bh_shares, last_price = backtester.run_strategy(strategy_id, data, params)
    metrics = backtester.calculate_metrics(equity, trades, params["initialCapital"], bh_shares, last_price)
    return metrics, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SimuTrade evaluation suite.")
    parser.add_argument("--config", type=str, default=None, help="Path to experiment_config.json")
    parser.add_argument("--method", type=str, choices=["heuristic_fallback", "llm", "both"], default="both")
    parser.add_argument("--start", type=str, default=None, help="Override start date")
    parser.add_argument("--end", type=str, default=None, help="Override end date")
    parser.add_argument("--log-usability", action="store_true", help="Log automated usability timing records")
    args = parser.parse_args()

    cfg = load_experiment_config(args.config)
    paths = get_runtime_paths(cfg)
    defaults = get_runtime_defaults(cfg)
    exec_defaults = get_execution_defaults()
    strategy_registry = resolve_strategy_registry(cfg)

    start_date = args.start or defaults["start_date"]
    end_date = args.end or defaults["end_date"]
    interval = defaults["interval"]

    bench = load_benchmarks(cfg, paths)
    prompts: List[Dict[str, Any]] = bench["prompts"]
    tickers: List[str] = bench["tickers"]

    if args.method == "both":
        methods: List[str] = list(defaults["methods"])
    else:
        methods = [args.method]

    print(f"Running evaluation from {start_date} to {end_date}, interval={interval}")
    print(f"Methods: {methods}")
    print(f"Benchmarks: {len(prompts)} prompts, {len(tickers)} tickers")

    total_runs = 0
    exact_match_runs = 0

    for prompt_spec in prompts:
        prompt = prompt_spec["prompt"]
        prompt_id = prompt_spec.get("id", "unknown_prompt")
        expected_strategy = prompt_spec.get("expected_strategy")

        for ticker in tickers:
            for method in methods:
                print(f"\n[RUN] method={method} ticker={ticker} prompt='{prompt_id}'")
                total_runs += 1
                try:
                    payload, latency_ms = run_single_mapping(prompt, ticker, interval, method)
                    strategy_id = payload.get("strategy_id")
                    mapping_source = payload.get("mapping_source", method)
                    schema_valid = strategy_id in strategy_registry
                    strategy_match = bool(expected_strategy and strategy_id == expected_strategy)
                    if strategy_match:
                        exact_match_runs += 1

                    metrics, backtest_error = run_backtest_for_payload(
                        ticker=ticker,
                        interval=interval,
                        start_date=start_date,
                        end_date=end_date,
                        payload=payload,
                        exec_defaults=exec_defaults,
                    )
                    backtest_completed = bool(metrics)

                    record_id = log_technical(
                        prompt=prompt,
                        mapping_source=mapping_source,
                        schema_valid=schema_valid,
                        backtest_completed=backtest_completed,
                        latency_ms=latency_ms,
                        fallback_reason=payload.get("fallback_reason"),
                        llm_model=payload.get("llm_model"),
                        error=backtest_error,
                        expected_strategy=expected_strategy,
                        produced_strategy=strategy_id,
                        strategy_match=strategy_match,
                        ticker=ticker,
                        interval=interval,
                    )

                    if args.log_usability:
                        log_usability(
                            flow_type=mapping_source,
                            prompt=prompt,
                            time_to_submit_sec=latency_ms / 1000.0,
                            form_errors=0 if schema_valid else 1,
                            apply_button_used=True,
                            backtest_triggered=backtest_completed,
                            user_id="automated_benchmark",
                        )

                    if backtest_completed:
                        log_trading(
                            record_id=record_id,
                            ticker=ticker,
                            strategy_id=strategy_id or "unknown",
                            mapping_source=mapping_source,
                            metrics=metrics,
                            params_snapshot=payload,
                        )

                    print(
                        f"[OK] strategy={strategy_id} schema_valid={schema_valid} "
                        f"match={strategy_match} backtest_completed={backtest_completed} "
                        f"latency_ms={latency_ms:.2f}"
                    )
                except Exception as e:
                    print(f"[ERROR] {e}")

    if total_runs and any(p.get("expected_strategy") for p in prompts):
        accuracy = exact_match_runs / total_runs
        print(f"\nStrategy match accuracy: {exact_match_runs}/{total_runs} = {accuracy:.3f}")


if __name__ == "__main__":
    main()
