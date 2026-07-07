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


def build_tables(cfg_path: str | None = None) -> None:
    cfg = load_experiment_config(cfg_path)
    paths = get_runtime_paths(cfg)
    log_dir = Path(paths["log_dir"])
    output_dir = Path(paths["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    tech = pd.DataFrame(_read_ndjson(log_dir / "technical_eval.ndjson"))
    trade = pd.DataFrame(_read_ndjson(log_dir / "trading_eval.ndjson"))
    use = pd.DataFrame(_read_ndjson(log_dir / "usability_eval.ndjson"))

    if not tech.empty:
        tech.to_csv(output_dir / "technical_eval_raw.csv", index=False)
        agg_spec = {
            "schema_valid": "mean",
            "backtest_completed": "mean",
            "latency_ms": "mean",
        }
        if "strategy_match" in tech.columns:
            agg_spec["strategy_match"] = "mean"
        summary = tech.groupby(["mapping_source"], dropna=False).agg(agg_spec).reset_index()
        summary.rename(columns={
            "schema_valid": "valid_output_rate",
            "backtest_completed": "backtest_completion_rate",
            "strategy_match": "strategy_match_rate",
            "latency_ms": "avg_latency_ms",
        }, inplace=True)
        summary.to_csv(output_dir / "technical_eval_summary.csv", index=False)

    if not trade.empty:
        trade.to_csv(output_dir / "trading_eval_raw.csv", index=False)
        summary_t = trade.groupby(["mapping_source"], dropna=False).agg({
            "total_return_pct": "mean",
            "sharpe_ratio": "mean",
            "max_drawdown_pct": "mean",
            "win_rate_pct": "mean",
            "total_trades": "mean",
        }).reset_index()
        summary_t.to_csv(output_dir / "trading_eval_summary.csv", index=False)

    if not use.empty:
        use.to_csv(output_dir / "usability_eval_raw.csv", index=False)
        summary_u = use.groupby(["flow_type"], dropna=False).agg({
            "time_to_submit_sec": "mean",
            "form_errors": "mean",
            "backtest_triggered": "mean",
        }).reset_index()
        summary_u.rename(columns={"backtest_triggered": "backtest_trigger_rate"}, inplace=True)
        summary_u.to_csv(output_dir / "usability_eval_summary.csv", index=False)


if __name__ == "__main__":
    build_tables()