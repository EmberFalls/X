"""
optimizer.py
Grid-search parameter optimizer for SimuTrade.
Wraps backtester.run_strategy across a parameter grid and returns ranked results.
Called by /api/optimize in main.py — no changes to that route needed.
"""
from __future__ import annotations

from itertools import product
from typing import Any, Dict, List, Optional

import pandas as pd

import backtester


def grid_search(
    strategy: str,
    df: pd.DataFrame,
    param_grid: Dict[str, List[Any]],
    base_params: Dict[str, Any],
    top_n: int = 10,
    sort_by: str = "totalReturn",
) -> List[Dict[str, Any]]:
    """
    Run a grid search over param_grid on top of base_params.

    Parameters
    ----------
    strategy   : strategy id string (e.g. 'golden_cross')
    df         : raw OHLCV DataFrame (pre-fetched, NOT indicators-added yet)
    param_grid : dict of param_name → list of values to try
                 e.g. {"fastMA": [10, 20, 50], "slowMA": [100, 150, 200]}
    base_params: fixed params passed to backtester (capital, risk, dates, etc.)
    top_n      : how many top results to return
    sort_by    : metric key to rank by (default: "totalReturn")

    Returns
    -------
    List of dicts, each with {"params": {...}, "metrics": {...}}
    sorted descending by sort_by, limited to top_n.
    """
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    results: List[Dict[str, Any]] = []

    for combo in product(*values):
        params = {**base_params, **dict(zip(keys, combo))}

        # Skip invalid combos (fast MA must be strictly less than slow MA)
        fast = params.get("fastMA", 0)
        slow = params.get("slowMA", 0)
        if fast >= slow:
            continue

        try:
            data = backtester.add_indicators(df.copy(), params).dropna(subset=["Close"])
            if len(data) < 20:
                continue

            equity, trades, final_cash, bh_shares, last_price = backtester.run_strategy(
                strategy, data, params
            )
            metrics = backtester.calculate_metrics(
                equity, trades, params["initialCapital"], bh_shares, last_price
            )

            results.append({"params": dict(zip(keys, combo)), "metrics": metrics})
        except Exception:
            continue

    results.sort(key=lambda x: x["metrics"].get(sort_by, 0), reverse=True)
    return results[:top_n]


def build_param_grid_from_request(req_dict: Dict[str, Any]) -> Dict[str, List[Any]]:
    """
    Convert OptimizeRequest fields into a param_grid dict.
    Parses comma-separated fastMAList and slowMAList strings.
    """
    fast_list = [
        int(x.strip())
        for x in str(req_dict.get("fastMAList", "20,50,100")).split(",")
        if x.strip().isdigit()
    ]
    slow_list = [
        int(x.strip())
        for x in str(req_dict.get("slowMAList", "150,200,250")).split(",")
        if x.strip().isdigit()
    ]
    return {"fastMA": fast_list, "slowMA": slow_list}


def build_base_params(req_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract fixed (non-grid) params from an OptimizeRequest dict.
    """
    return {
        "mrK": req_dict.get("mrK", 2.0),
        "atrPeriod": req_dict.get("atrPeriod", 14),
        "initialCapital": float(req_dict.get("initialCapital", 100000)),
        "riskPercent": float(req_dict.get("riskPercent", 2.0)),
        "stopLoss": float(req_dict.get("stopLoss", 2.0)),
        "takeProfit": float(req_dict.get("takeProfit", 6.0)),
        "slippage": float(req_dict.get("slippage", 0.1)),
        "transactionCost": float(req_dict.get("transactionCost", 0.05)),
        "ticker": req_dict.get("ticker", "RELIANCE.NS"),
        "startDate": req_dict.get("startDate", "2023-01-01"),
        "endDate": req_dict.get("endDate", "2024-12-31"),
        "interval": req_dict.get("interval", "1d"),
    }