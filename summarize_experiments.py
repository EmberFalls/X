from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from config_loader import load_experiment_config, get_runtime_paths

BASE_DIR = Path(__file__).resolve().parent


def _read_ndjson(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def summarize(cfg_path: str | None = None) -> None:
    cfg = load_experiment_config(cfg_path)
    paths = get_runtime_paths(cfg)
    log_dir = Path(paths["log_dir"])

    tech = pd.DataFrame(_read_ndjson(log_dir / "technical_eval.ndjson"))
    trade = pd.DataFrame(_read_ndjson(log_dir / "trading_eval.ndjson"))
    use = pd.DataFrame(_read_ndjson(log_dir / "usability_eval.ndjson"))

    print("=== SimuTrade Experiment Summary ===")

    if tech.empty:
        print("No technical_eval.ndjson found.")
    else:
        print(f"Technical records: {len(tech)}")
        cols = ["schema_valid", "backtest_completed", "latency_ms"]
        if "strategy_match" in tech.columns:
            cols.append("strategy_match")
        by_method = tech.groupby("mapping_source")[cols].mean().reset_index()
        print("\nTechnical metrics by method:")
        print(by_method.to_string(index=False))

    if trade.empty:
        print("\nNo trading_eval.ndjson found.")
    else:
        print(f"\nTrading records: {len(trade)}")
        by_method_t = trade.groupby("mapping_source").agg({
            "total_return_pct": "mean",
            "sharpe_ratio": "mean",
            "max_drawdown_pct": "mean",
            "win_rate_pct": "mean",
            "total_trades": "mean",
        }).reset_index()
        print("\nTrading metrics by method:")
        print(by_method_t.to_string(index=False))

    if use.empty:
        print("\nNo usability_eval.ndjson found.")
    else:
        print(f"\nUsability records: {len(use)}")
        by_flow = use.groupby("flow_type").agg({
            "time_to_submit_sec": "mean",
            "form_errors": "mean",
            "backtest_triggered": "mean",
        }).reset_index()
        print("\nUsability metrics by flow:")
        print(by_flow.to_string(index=False))


if __name__ == "__main__":
    summarize()