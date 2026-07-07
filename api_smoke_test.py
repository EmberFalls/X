from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict

import requests


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" -> {detail}" if detail else ""))
    return ok


def post_json(url: str, payload: Dict[str, Any], timeout: int = 60):
    return requests.post(url, json=payload, timeout=timeout)


def get_url(url: str, timeout: int = 60):
    return requests.get(url, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description="SimuTrade API smoke tests")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--ticker", default="RELIANCE.NS")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--groq-api-key", default=None)
    args = parser.parse_args()

    base = args.base.rstrip("/")
    ok_all = True

    r = get_url(f"{base}/api/health")
    ok_all &= check("health endpoint", r.ok, r.text[:200])

    assistant_payload = {
        "prompt": "low risk trend-following strategy for large cap stocks",
        "ticker": args.ticker,
        "interval": args.interval,
    }
    if args.groq_api_key:
        assistant_payload["groq_api_key"] = args.groq_api_key

    assistant_route = "/api/assistant/suggest_llm" if args.use_llm else "/api/assistant/suggest"
    r = post_json(f"{base}{assistant_route}", assistant_payload)
    ok_all &= check("assistant endpoint", r.ok, r.text[:300])
    data = r.json() if r.ok else {}

    required_keys = [
        "user_intent", "strategy_id", "ticker", "interval",
        "market_mode", "risk_profile", "entry_logic",
        "exit_logic", "execution_rules", "assistant_rationale"
    ]
    missing = [k for k in required_keys if k not in data]
    ok_all &= check("assistant schema keys", len(missing) == 0, f"missing={missing}")

    backtest_payload = {
        "strategy": data.get("strategy_id", "golden_cross"),
        "ticker": args.ticker,
        "startDate": "2024-01-01",
        "endDate": "2024-12-31",
        "fastMA": data.get("entry_logic", {}).get("fast_ma") or 20,
        "slowMA": data.get("entry_logic", {}).get("slow_ma") or 50,
        "mrK": data.get("entry_logic", {}).get("mr_k") or 2.0,
        "initialCapital": data.get("execution_rules", {}).get("initial_capital") or 100000,
        "riskPercent": data.get("execution_rules", {}).get("risk_percent") or 2.0,
        "atrPeriod": 14,
        "stopLoss": data.get("exit_logic", {}).get("stop_loss_pct") or 2.0,
        "takeProfit": data.get("exit_logic", {}).get("take_profit_pct") or 6.0,
        "slippage": data.get("execution_rules", {}).get("slippage_pct") or 0.1,
        "transactionCost": data.get("execution_rules", {}).get("transaction_cost_pct") or 0.05,
        "interval": args.interval,
    }

    r = post_json(f"{base}/api/backtest", backtest_payload, timeout=120)
    ok_all &= check("backtest endpoint", r.ok, r.text[:300])
    bt = r.json() if r.ok else {}
    ok_all &= check("backtest metrics present", "metrics" in bt and isinstance(bt.get("metrics"), dict), str(bt.get("metrics", {}))[:300])

    r = get_url(f"{base}/api/live-chart/{args.ticker}?interval=5m", timeout=120)
    ok_all &= check("live chart v1", r.ok, r.text[:200])

    if args.use_llm:
        strategy_id = data.get("strategy_id", "golden_cross")
        r = get_url(f"{base}/api/live-chart-v2/{args.ticker}?interval=5m&strategy_id={strategy_id}", timeout=120)
        ok_all &= check("live chart v2", r.ok, r.text[:300])
        if r.ok:
            live_v2 = r.json()
            ok_all &= check("interpretability present", "interpretability" in live_v2, json.dumps(live_v2)[:300])

    usability_payload = {
        "flow_type": "llm" if args.use_llm else "heuristic_fallback",
        "prompt": assistant_payload["prompt"],
        "time_to_submit_sec": 2.4,
        "form_errors": 0,
        "apply_button_used": True,
        "backtest_triggered": True,
        "user_id": "local-smoke-test"
    }
    r = post_json(f"{base}/api/log/usability", usability_payload)
    ok_all &= check("usability log endpoint", r.ok, r.text[:200])

    print("\nOVERALL:", "PASS" if ok_all else "FAIL")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()