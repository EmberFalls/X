"""Clean, resumable SimuTrade evaluation pipeline.

This script deliberately separates 50 prompt-level semantic mappings from
ticker-expanded deterministic backtests. It never routes a failed direct LLM
request to the heuristic mapper.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

import backtester
import yfinance as yf
from groq import Groq

from llm_mapper import GROQ_MODEL, _SYSTEM_PROMPT, _parse_and_validate
from market_data import YFinanceProvider
from schemas import StrategyPayload
from strategy_assistant import suggest_strategy_from_prompt


BASE = Path(__file__).resolve().parent
CLEAN = BASE / "paper_evaluation_clean"
PROMPTS_PATH = BASE / "evaluation_prompts_50.json"
TICKERS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
START_DATE, END_DATE, INTERVAL = "2023-01-01", "2024-12-31", "1d"
BACKTEST_REPETITIONS = 2
INITIAL_BACKOFF_SECONDS, MAX_BACKOFF_SECONDS, MAX_PROVIDER_ATTEMPTS = 15, 120, 8
INTER_REQUEST_DELAY_SECONDS = 5
EXEC_DEFAULTS = {"initial_capital": 100000, "risk_percent": 2.0, "slippage_pct": 0.1, "transaction_cost_pct": 0.05}
YFINANCE_CACHE = BASE / "tmp" / "yfinance_cache"

SEMANTIC_FIELDS = [
    "mapping_eval_id", "mapper", "prompt_id", "prompt_family", "difficulty", "prompt_text",
    "expected_strategy", "produced_strategy", "strategy_match", "expected_risk", "produced_risk",
    "risk_match", "schema_valid", "mapping_latency_ms", "provider_attempt_count",
    "provider_wait_ms", "model_name", "error_type", "error_message", "created_at",
]
BACKTEST_FIELDS = [
    "backtest_eval_id", "mapper", "prompt_id", "prompt_family", "difficulty", "expected_strategy",
    "produced_strategy", "strategy_match", "expected_risk", "produced_risk", "risk_match",
    "schema_valid", "mapped_ticker", "backtest_ticker", "run", "interval", "start_date", "end_date",
    "starting_capital", "transaction_fee", "slippage", "backtest_completed", "backtest_error",
    "total_return_pct", "max_drawdown_pct", "sharpe_ratio", "win_rate_pct", "total_trades",
    "final_value", "buy_and_hold_value",
]


class IncompleteProviderQuota(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_project_environment() -> None:
    env_path = BASE / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def ensure_csv(path: Path, fields: list[str]) -> None:
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def append_csv(path: Path, fields: list[str], row: dict[str, Any]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writerow({field: row.get(field, "") for field in fields})
        f.flush()
        os.fsync(f.fileno())


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def jsonl_by_prompt(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            record = json.loads(raw)
            prompt_id = record.get("prompt_id")
            if prompt_id:
                result[prompt_id] = record
    return result


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fields} for row in rows])


def prompt_spec(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_id": raw["id"], "prompt_family": raw["category"], "difficulty": raw["difficulty"],
        "prompt_text": raw["prompt"], "expected_strategy": raw["expected_strategy"],
        "expected_risk_profile": raw["expected_risk_profile"],
    }


def validate_and_freeze_prompts() -> list[dict[str, Any]]:
    prompts = [prompt_spec(p) for p in json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))]
    if len(prompts) != 50 or len({p["prompt_id"] for p in prompts}) != 50:
        raise ValueError("Benchmark must contain exactly 50 unique prompt IDs.")
    family_counts = Counter(p["prompt_family"] for p in prompts)
    if family_counts != Counter({"trend": 10, "mean_reversion": 10, "reversal": 10, "macd": 10, "breakout": 10}):
        raise ValueError(f"Unexpected prompt-family balance: {family_counts}")
    allowed = {"golden_cross", "mean_reversion", "rsi_strategy", "macd_crossover", "momentum_breakout"}
    if any(not p["expected_strategy"] or p["expected_strategy"] not in allowed or not p["expected_risk_profile"] for p in prompts):
        raise ValueError("Every prompt needs valid expected strategy and risk labels.")
    write_csv(CLEAN / "prompt_set.csv", ["prompt_id", "prompt_family", "difficulty", "prompt_text", "expected_strategy", "expected_risk_profile"], prompts)
    return prompts


def semantic_row(prompt: dict[str, Any], mapper: str, payload: dict[str, Any] | None, latency_ms: float | None,
                 attempts: int, wait_ms: int, model_name: str | None, error_type: str = "", error_message: str = "") -> dict[str, Any]:
    strategy = (payload or {}).get("strategy_id", "")
    risk = (payload or {}).get("risk_profile", "")
    schema_valid = False
    if payload:
        try:
            StrategyPayload.model_validate({key: payload[key] for key in StrategyPayload.model_fields if key in payload})
            schema_valid = True
        except Exception as exc:
            error_type = error_type or "schema_invalid"
            error_message = error_message or str(exc)
    return {
        "mapping_eval_id": f"{mapper}_{prompt['prompt_id']}", "mapper": mapper, **prompt,
        "expected_risk": prompt["expected_risk_profile"], "produced_strategy": strategy,
        "strategy_match": bool(strategy and strategy == prompt["expected_strategy"]), "produced_risk": risk,
        "risk_match": bool(risk and risk == prompt["expected_risk_profile"]), "schema_valid": schema_valid,
        "mapping_latency_ms": round(latency_ms, 2) if latency_ms is not None else "", "provider_attempt_count": attempts,
        "provider_wait_ms": wait_ms, "model_name": model_name or "", "error_type": error_type,
        "error_message": error_message, "created_at": now(),
    }


def run_heuristic(prompts: list[dict[str, Any]]) -> None:
    cache_path, semantic_path = CLEAN / "heuristic_mapping_cache.jsonl", CLEAN / "semantic_mapping_results.csv"
    cached = jsonl_by_prompt(cache_path)
    done = {r["mapping_eval_id"] for r in read_csv(semantic_path)}
    for prompt in prompts:
        if prompt["prompt_id"] in cached and f"heuristic_{prompt['prompt_id']}" in done:
            continue
        started = time.perf_counter()
        payload = suggest_strategy_from_prompt(prompt["prompt_text"], "RELIANCE.NS", INTERVAL)
        latency = (time.perf_counter() - started) * 1000
        record = {"prompt_id": prompt["prompt_id"], "actual_mapping_source": "heuristic", "parsed_config": payload, "created_at": now()}
        append_jsonl(cache_path, record)
        append_csv(semantic_path, SEMANTIC_FIELDS, semantic_row(prompt, "heuristic", payload, latency, 0, 0, None))
        print(f"[HEURISTIC] {prompt['prompt_id']} persisted", flush=True)


def retryable_provider_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("429", "rate limit", "timeout", "timed out", "connection", "503", "502", "504", "service unavailable", "temporarily unavailable"))


def provider_delay_seconds(exc: Exception, attempt: int) -> int:
    # Groq's client does not consistently expose Retry-After across exception versions;
    # use conservative exponential backoff when a usable header is unavailable.
    return min(INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)


def direct_llm_payload(client: Groq, prompt: dict[str, Any]) -> tuple[dict[str, Any] | None, str, float, str, str]:
    user_message = f"User trading intent: {prompt['prompt_text']}\nTicker hint: RELIANCE.NS\nInterval hint: {INTERVAL}"
    started = time.perf_counter()
    chat = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "system", "content": _SYSTEM_PROMPT.strip()}, {"role": "user", "content": user_message}],
        temperature=0.2,
        max_tokens=800,
    )
    latency = (time.perf_counter() - started) * 1000
    raw = (chat.choices[0].message.content or "").strip()
    try:
        payload = _parse_and_validate(raw, prompt["prompt_text"], "RELIANCE.NS", INTERVAL)
        return payload, raw, latency, "", ""
    except Exception as exc:
        # A completed response is a single genuine semantic observation, even when invalid.
        return None, raw, latency, "schema_or_parse_failure", str(exc)


def run_direct_llm(prompts: list[dict[str, Any]]) -> None:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise IncompleteProviderQuota("INCOMPLETE_PROVIDER_QUOTA: GROQ_API_KEY is unavailable; no fallback was used.")
    cache_path, log_path = CLEAN / "llm_mapping_cache.jsonl", CLEAN / "llm_request_log.jsonl"
    semantic_path, pending_path = CLEAN / "semantic_mapping_results.csv", CLEAN / "pending_provider_failures.jsonl"
    cached = jsonl_by_prompt(cache_path)
    done = {r["mapping_eval_id"] for r in read_csv(semantic_path)}
    client = Groq(api_key=api_key, timeout=35.0, max_retries=0)
    for index, prompt in enumerate(prompts, start=1):
        pid = prompt["prompt_id"]
        if pid in cached and f"llm_{pid}" in done:
            continue
        provider_wait_ms = 0
        for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
            try:
                payload, raw, latency, error_type, error_message = direct_llm_payload(client, prompt)
                cache_record = {
                    "prompt_id": pid, "actual_mapping_source": "llm", "model_name": GROQ_MODEL,
                    "raw_response": raw, "parsed_config": payload, "inference_latency_ms": round(latency, 2),
                    "provider_attempt_count": attempt, "provider_wait_ms": provider_wait_ms,
                    "error_type": error_type, "error_message": error_message, "created_at": now(),
                }
                append_jsonl(cache_path, cache_record)
                append_jsonl(log_path, {"prompt_id": pid, "attempt": attempt, "event": "completed_model_response", "at": now(), "inference_latency_ms": round(latency, 2)})
                append_csv(semantic_path, SEMANTIC_FIELDS, semantic_row(prompt, "llm", payload, latency, attempt, provider_wait_ms, GROQ_MODEL, error_type, error_message))
                print(f"[LLM {index}/50] {pid} persisted (schema_valid={bool(payload)})", flush=True)
                if index < len(prompts):
                    time.sleep(INTER_REQUEST_DELAY_SECONDS)
                break
            except Exception as exc:
                if not retryable_provider_error(exc):
                    append_jsonl(log_path, {"prompt_id": pid, "attempt": attempt, "event": "non_retryable_provider_error", "error": str(exc), "at": now()})
                    raise IncompleteProviderQuota(f"INCOMPLETE_PROVIDER_QUOTA: non-retryable provider error for {pid}: {exc}") from exc
                if attempt == MAX_PROVIDER_ATTEMPTS:
                    pending = {"prompt_id": pid, "attempts": attempt, "error": str(exc), "status": "INCOMPLETE_PROVIDER_QUOTA", "at": now()}
                    append_jsonl(pending_path, pending)
                    append_jsonl(log_path, {**pending, "event": "provider_attempts_exhausted"})
                    raise IncompleteProviderQuota(f"INCOMPLETE_PROVIDER_QUOTA: provider attempts exhausted for {pid}; resume later.") from exc
                delay = provider_delay_seconds(exc, attempt)
                provider_wait_ms += delay * 1000
                append_jsonl(log_path, {"prompt_id": pid, "attempt": attempt, "event": "retryable_provider_error", "error": str(exc), "wait_seconds": delay, "at": now()})
                print(f"[LLM {index}/50] {pid}: retryable provider error; waiting {delay}s", flush=True)
                time.sleep(delay)


def load_config(mapper: str, prompt_id: str) -> dict[str, Any] | None:
    path = CLEAN / ("heuristic_mapping_cache.jsonl" if mapper == "heuristic" else "llm_mapping_cache.jsonl")
    return jsonl_by_prompt(path).get(prompt_id, {}).get("parsed_config")


def payload_to_backtest_params(payload: dict[str, Any], ticker: str) -> tuple[str | None, dict[str, Any]]:
    entry, exit_logic, execution = payload.get("entry_logic", {}) or {}, payload.get("exit_logic", {}) or {}, payload.get("execution_rules", {}) or {}
    return payload.get("strategy_id"), {
        "fastMA": entry.get("fast_ma") if entry.get("fast_ma") is not None else 20,
        "slowMA": entry.get("slow_ma") if entry.get("slow_ma") is not None else 50,
        "mrK": entry.get("mr_k") if entry.get("mr_k") is not None else 2.0, "atrPeriod": 14,
        "initialCapital": execution.get("initial_capital", EXEC_DEFAULTS["initial_capital"]),
        "riskPercent": execution.get("risk_percent", EXEC_DEFAULTS["risk_percent"]),
        "stopLoss": exit_logic.get("stop_loss_pct", 2.0), "takeProfit": exit_logic.get("take_profit_pct", 6.0),
        "slippage": execution.get("slippage_pct", EXEC_DEFAULTS["slippage_pct"]),
        "transactionCost": execution.get("transaction_cost_pct", EXEC_DEFAULTS["transaction_cost_pct"]), "ticker": ticker,
    }


def do_backtest(payload: dict[str, Any], ticker: str, data: Any) -> tuple[dict[str, Any], str]:
    strategy_id, params = payload_to_backtest_params(payload, ticker)
    if not strategy_id: return {}, "invalid_or_missing_strategy_id"
    prepared = backtester.add_indicators(data.copy(), params).dropna(subset=["Close"])
    if len(prepared) < 20: return {}, "insufficient_indicator_history"
    equity, trades, final_cash, bh_shares, last_price = backtester.run_strategy(strategy_id, prepared, params)
    return backtester.calculate_metrics(equity, trades, params["initialCapital"], bh_shares, last_price), ""


def run_backtests(prompts: list[dict[str, Any]]) -> None:
    path = CLEAN / "backtest_results.csv"
    existing = {r["backtest_eval_id"] for r in read_csv(path)}
    provider = YFinanceProvider(); yf.set_tz_cache_location(str(YFINANCE_CACHE)); data = {t: provider.get_history(t, START_DATE, END_DATE, INTERVAL) for t in TICKERS}
    semantic = {(r["mapper"], r["prompt_id"]): r for r in read_csv(CLEAN / "semantic_mapping_results.csv")}
    for mapper in ("heuristic", "llm"):
        for prompt in prompts:
            semantic_row_data = semantic[(mapper, prompt["prompt_id"])]
            payload = load_config(mapper, prompt["prompt_id"])
            for ticker in TICKERS:
                for repeat in range(1, BACKTEST_REPETITIONS + 1):
                    eid = f"{mapper}_{prompt['prompt_id']}_{ticker}_r{repeat}"
                    if eid in existing: continue
                    metrics, error = ({}, "mapping_config_unavailable") if not payload else do_backtest(payload, ticker, data[ticker])
                    row = {"backtest_eval_id": eid, "mapper": mapper, "prompt_id": prompt["prompt_id"], "prompt_family": prompt["prompt_family"], "difficulty": prompt["difficulty"], "expected_strategy": prompt["expected_strategy"], "produced_strategy": semantic_row_data["produced_strategy"], "strategy_match": semantic_row_data["strategy_match"], "expected_risk": prompt["expected_risk_profile"], "produced_risk": semantic_row_data["produced_risk"], "risk_match": semantic_row_data["risk_match"], "schema_valid": semantic_row_data["schema_valid"], "mapped_ticker": (payload or {}).get("ticker", ""), "backtest_ticker": ticker, "run": repeat, "interval": INTERVAL, "start_date": START_DATE, "end_date": END_DATE, "starting_capital": 100000, "transaction_fee": 0.05, "slippage": 0.1, "backtest_completed": bool(metrics), "backtest_error": error, "total_return_pct": metrics.get("totalReturn", ""), "max_drawdown_pct": metrics.get("maxDrawdown", ""), "sharpe_ratio": metrics.get("sharpeRatio", ""), "win_rate_pct": metrics.get("winRate", ""), "total_trades": metrics.get("totalTrades", ""), "final_value": metrics.get("finalValue", ""), "buy_and_hold_value": metrics.get("buyHoldValue", "")}
                    append_csv(path, BACKTEST_FIELDS, row); print(f"[BACKTEST] {eid}", flush=True)


def number(value: str) -> float | None:
    try: return float(value)
    except (TypeError, ValueError): return None


def build_aggregates_and_notes(prompts: list[dict[str, Any]]) -> None:
    semantic = sorted(read_csv(CLEAN / "semantic_mapping_results.csv"), key=lambda r: (r["prompt_id"], r["mapper"]))
    backtests = read_csv(CLEAN / "backtest_results.csv")
    overall, per_family = [], []
    for mapper in ("heuristic", "llm"):
        rows = [r for r in semantic if r["mapper"] == mapper]
        def rate(key: str) -> tuple[int, float]:
            n = sum(r[key].lower() == "true" for r in rows); return n, n * 100 / len(rows)
        strat, strat_pct = rate("strategy_match"); risk, risk_pct = rate("risk_match"); valid, valid_pct = rate("schema_valid")
        latencies = [number(r["mapping_latency_ms"]) for r in rows if number(r["mapping_latency_ms"]) is not None]
        overall.append({"Mapper": "Heuristic" if mapper == "heuristic" else "LLM", "Prompts": len(rows), "Correct Strategy": strat, "Strategy Accuracy (%)": round(strat_pct, 1), "Risk Accuracy (%)": round(risk_pct, 1), "Schema Valid (%)": round(valid_pct, 1), "Mean Latency (ms)": round(mean(latencies), 2), "Median Latency (ms)": round(median(latencies), 2)})
        for family in ("trend", "mean_reversion", "reversal", "macd", "breakout"):
            fr = [r for r in rows if r["prompt_family"] == family]; fl = [number(r["mapping_latency_ms"]) for r in fr if number(r["mapping_latency_ms"]) is not None]
            per_family.append({"Mapper": "Heuristic" if mapper == "heuristic" else "LLM", "Prompt Family": family, "Prompts": len(fr), "Correct Strategy": sum(r["strategy_match"].lower() == "true" for r in fr), "Strategy Match (%)": round(sum(r["strategy_match"].lower() == "true" for r in fr) * 100 / len(fr), 1), "Correct Risk": sum(r["risk_match"].lower() == "true" for r in fr), "Risk Match (%)": round(sum(r["risk_match"].lower() == "true" for r in fr) * 100 / len(fr), 1), "Schema Valid (%)": round(sum(r["schema_valid"].lower() == "true" for r in fr) * 100 / len(fr), 1), "Mean Latency (ms)": round(mean(fl), 2)})
    back_summary = []
    for mapper in ("heuristic", "llm"):
        for family in ("trend", "mean_reversion", "reversal", "macd", "breakout"):
            rows = [r for r in backtests if r["mapper"] == mapper and r["prompt_family"] == family]; completed = [r for r in rows if r["backtest_completed"].lower() == "true"]
            def avg(field: str) -> float:
                vals = [number(r[field]) for r in completed if number(r[field]) is not None]; return round(mean(vals), 3) if vals else 0.0
            back_summary.append({"Mapper": "Heuristic" if mapper == "heuristic" else "LLM", "Intended Strategy Family": family, "Backtests": len(rows), "Backtest Completion (%)": round(len(completed) * 100 / len(rows), 1), "Avg Return (%)": avg("total_return_pct"), "Avg Sharpe": avg("sharpe_ratio"), "Avg Max Drawdown (%)": avg("max_drawdown_pct"), "Avg Win Rate (%)": avg("win_rate_pct"), "Avg Trades": avg("total_trades")})
    write_csv(CLEAN / "paper_tables.csv", list(overall[0]) if overall else [], overall)
    write_csv(CLEAN / "per_family_mapping_table.csv", list(per_family[0]), per_family)
    write_csv(CLEAN / "backtesting_summary_table.csv", list(back_summary[0]), back_summary)
    strategies = ["golden_cross", "mean_reversion", "rsi_strategy", "macd_crossover", "momentum_breakout"]
    for mapper in ("heuristic", "llm"):
        rows = [r for r in semantic if r["mapper"] == mapper]
        matrix = [{"expected_strategy": expected, **{actual: sum(r["expected_strategy"] == expected and r["produced_strategy"] == actual for r in rows) for actual in strategies}} for expected in strategies]
        write_csv(CLEAN / f"confusion_matrix_{mapper}.csv", ["expected_strategy", *strategies], matrix)
    failures = [r for r in semantic if r["strategy_match"].lower() != "true" or r["risk_match"].lower() != "true" or r["schema_valid"].lower() != "true"]
    text = ["# Updated Experimental Results", "", "## Evaluation Design", "- 50 unique prompts; 10 prompts per supported strategy family.", "- 50 heuristic semantic mappings and 50 direct LLM semantic mappings.", "- 5 NSE tickers and 2 deterministic backtest repetitions; 1,000 downstream backtest executions.", "", "## Overall Mapping Results"]
    for row in overall: text.append(f"- {row['Mapper']}: strategy {row['Correct Strategy']}/{row['Prompts']} ({row['Strategy Accuracy (%)']}%); risk {row['Risk Accuracy (%)']}%; schema {row['Schema Valid (%)']}%; mean/median latency {row['Mean Latency (ms)']}/{row['Median Latency (ms)']} ms.")
    text.extend(["", "## Per-Family Results"] + [f"- {r['Mapper']} — {r['Prompt Family']}: strategy {r['Correct Strategy']}/{r['Prompts']} ({r['Strategy Match (%)']}%), risk {r['Correct Risk']}/{r['Prompts']} ({r['Risk Match (%)']}%)." for r in per_family] + ["", "## Failure Analysis"])
    text.extend([f"- {r['mapper']} {r['prompt_id']}: expected {r['expected_strategy']}/{r['expected_risk']}; produced {r['produced_strategy'] or 'none'}/{r['produced_risk'] or 'none'}." for r in failures] or ["- No incorrect, risk-mismatch, or schema-invalid observations."])
    text.extend(["", "## Backtesting Summary", "- Downstream backtesting results are reported separately from semantic accuracy. They reuse cached mappings across tickers and repetitions.", "", "## Paper-Safe Interpretation", "- On the evaluated 50-prompt benchmark, results quantify this benchmark only; they do not establish universal semantic correctness. Ticker-expanded backtests are not additional independent prompts."])
    (CLEAN / "paper_update_notes.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def final_validate(prompts: list[dict[str, Any]]) -> None:
    semantic, backtests = read_csv(CLEAN / "semantic_mapping_results.csv"), read_csv(CLEAN / "backtest_results.csv")
    assert len(semantic) == 100, f"Expected 100 semantic rows, found {len(semantic)}"
    for mapper in ("heuristic", "llm"):
        rows = [r for r in semantic if r["mapper"] == mapper]
        assert len(rows) == 50 and len({r["prompt_id"] for r in rows}) == 50, f"Invalid {mapper} semantic set"
    assert len(backtests) == 1000, f"Expected 1000 backtest rows, found {len(backtests)}"
    assert not any(r["mapper"] == "llm" and r.get("actual_mapping_source") == "heuristic_fallback" for r in semantic)
    (CLEAN / "validation_passed.txt").write_text("All prompt, semantic-mapping, and backtest row-count checks passed.\n", encoding="utf-8")


def write_manifest(status: str, prompts: list[dict[str, Any]], error: str = "") -> None:
    try: commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception: commit = "unavailable"
    manifest = {"run_id": "simutrade_clean_semantic_v1", "run_updated_at": now(), "status": status, "error": error, "code_version_or_commit": commit, "llm_provider": "Groq", "llm_model": GROQ_MODEL, "llm_temperature": 0.2, "prompt_count": len(prompts), "prompt_sha256": hashlib.sha256((CLEAN / "prompt_set.csv").read_bytes()).hexdigest(), "market_data_period": {"start": START_DATE, "end": END_DATE, "interval": INTERVAL}, "tickers": TICKERS, "backtest_repetitions": BACKTEST_REPETITIONS, "starting_capital": 100000, "transaction_fee_pct": 0.05, "slippage_pct": 0.1, "rate_limit_retry_policy": {"initial_backoff_seconds": INITIAL_BACKOFF_SECONDS, "maximum_backoff_seconds": MAX_BACKOFF_SECONDS, "maximum_attempts": MAX_PROVIDER_ATTEMPTS, "inter_request_delay_seconds": INTER_REQUEST_DELAY_SECONDS}}
    (CLEAN / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> int:
    CLEAN.mkdir(parents=True, exist_ok=True); YFINANCE_CACHE.mkdir(parents=True, exist_ok=True); load_project_environment()
    ensure_csv(CLEAN / "semantic_mapping_results.csv", SEMANTIC_FIELDS); ensure_csv(CLEAN / "backtest_results.csv", BACKTEST_FIELDS)
    prompts = validate_and_freeze_prompts(); write_manifest("RUNNING", prompts)
    try:
        run_heuristic(prompts); run_direct_llm(prompts); run_backtests(prompts); build_aggregates_and_notes(prompts); final_validate(prompts); write_manifest("COMPLETE", prompts)
        print("CLEAN_EVALUATION_COMPLETE", flush=True); return 0
    except IncompleteProviderQuota as exc:
        append_jsonl(CLEAN / "run_errors.log", {"at": now(), "status": "INCOMPLETE_PROVIDER_QUOTA", "error": str(exc)})
        write_manifest("INCOMPLETE_PROVIDER_QUOTA", prompts, str(exc)); print(str(exc), flush=True); return 2
    except Exception as exc:
        append_jsonl(CLEAN / "run_errors.log", {"at": now(), "status": "FAILED", "error": repr(exc)})
        write_manifest("FAILED", prompts, repr(exc)); raise


if __name__ == "__main__":
    raise SystemExit(main())
