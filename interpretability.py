"""
interpretability.py
Live chart interpretability layer for SimuTrade v2.
Computes strategy-specific overlays and annotated BUY/SELL signal points
from raw OHLCV candles. Returns a structured dict consumed by the frontend
and by /api/assistant/suggest_llm for paper traceability.

No prediction. No ML. Pure indicator math on top of existing OHLCV data.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------
def build_interpretability_layer(
    df: pd.DataFrame,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build overlay data for a given strategy payload and OHLCV DataFrame.

    Parameters
    ----------
    df       : DataFrame with columns [Open, High, Low, Close, Volume] (or lowercase).
               Minimum 30 rows for meaningful computation.
    payload  : StrategyPayload dict (output of llm_mapper or heuristic mapper).

    Returns
    -------
    dict with keys:
        strategy_id        : str
        overlays           : list[dict]  — indicator series for chart rendering
        signal_annotations : list[dict]  — BUY/SELL points with labels
        rationale_trace    : list[str]   — step-by-step decision chain (paper figure)
    """
    df = _normalise_columns(df)
    if len(df) < 10:
        return {"strategy_id": payload.get("strategy_id"), "overlays": [], "signal_annotations": [], "rationale_trace": []}

    strategy_id = payload.get("strategy_id", "golden_cross")
    entry = payload.get("entry_logic", {}) or {}

    dispatch = {
        "golden_cross":      _golden_cross_layer,
        "mean_reversion":    _mean_reversion_layer,
        "rsi_strategy":      _rsi_strategy_layer,
        "macd_crossover":    _macd_crossover_layer,
        "momentum_breakout": _momentum_breakout_layer,
    }

    handler = dispatch.get(strategy_id, _golden_cross_layer)
    overlays, signals, trace = handler(df, entry)

    return {
        "strategy_id": strategy_id,
        "overlays": overlays,
        "signal_annotations": signals,
        "rationale_trace": trace,
    }


# ---------------------------------------------------------------------------
# Strategy-specific layer builders
# ---------------------------------------------------------------------------

def _golden_cross_layer(df: pd.DataFrame, entry: dict):
    fast = int(entry.get("fast_ma") or 20)
    slow = int(entry.get("slow_ma") or 50)

    ema_fast = _ema_series(df["Close"], fast)
    ema_slow = _ema_series(df["Close"], slow)

    overlays = [
        _series_to_overlay(df, ema_fast, f"EMA{fast}", "line", "#f59e0b"),
        _series_to_overlay(df, ema_slow, f"EMA{slow}", "line", "#3b82f6"),
    ]

    signals = []
    for i in range(1, len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(ema_slow.iloc[i]):
            continue
        prev_above = ema_fast.iloc[i - 1] > ema_slow.iloc[i - 1]
        curr_above = ema_fast.iloc[i] > ema_slow.iloc[i]
        if not prev_above and curr_above:
            signals.append(_annotation(df, i, "BUY", f"EMA{fast} crosses EMA{slow} ↑"))
        elif prev_above and not curr_above:
            signals.append(_annotation(df, i, "SELL", f"EMA{fast} crosses EMA{slow} ↓"))

    trace = [
        f"1. User intent mapped to 'golden_cross' strategy.",
        f"2. EMA{fast} (fast) and EMA{slow} (slow) computed on Close prices.",
        f"3. BUY signal generated when EMA{fast} crosses above EMA{slow}.",
        f"4. SELL signal generated when EMA{fast} crosses below EMA{slow}.",
        f"5. {len(signals)} crossover event(s) detected in this window.",
    ]

    return overlays, signals, trace


def _mean_reversion_layer(df: pd.DataFrame, entry: dict):
    k = float(entry.get("mr_k") or 2.0)
    period = 20

    sma = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std()
    upper = sma + k * std
    lower = sma - k * std

    overlays = [
        _series_to_overlay(df, sma,   "BB Mid",   "line",   "#6366f1"),
        _series_to_overlay(df, upper, "BB Upper", "dashed", "#ef4444"),
        _series_to_overlay(df, lower, "BB Lower", "dashed", "#22c55e"),
    ]

    signals = []
    for i in range(1, len(df)):
        if pd.isna(lower.iloc[i]) or pd.isna(upper.iloc[i]):
            continue
        if df["Close"].iloc[i - 1] >= lower.iloc[i - 1] and df["Close"].iloc[i] < lower.iloc[i]:
            signals.append(_annotation(df, i, "BUY", f"Close touches lower BB (k={k})"))
        elif df["Close"].iloc[i - 1] <= upper.iloc[i - 1] and df["Close"].iloc[i] > upper.iloc[i]:
            signals.append(_annotation(df, i, "SELL", f"Close touches upper BB (k={k})"))

    trace = [
        "1. Intent mapped to 'mean_reversion' — sideways/choppy market regime.",
        f"2. Bollinger Bands computed: SMA{period} ± {k}×σ.",
        "3. BUY when Close dips below lower band (oversold).",
        "4. SELL when Close rises above upper band (overbought).",
        f"5. {len(signals)} band-touch event(s) detected.",
    ]

    return overlays, signals, trace


def _rsi_strategy_layer(df: pd.DataFrame, entry: dict):
    rsi_buy  = float(entry.get("rsi_buy")  or 30.0)
    rsi_sell = float(entry.get("rsi_sell") or 70.0)

    rsi = _rsi_series(df["Close"], 14)

    overlays = [
        _series_to_overlay(df, rsi, "RSI(14)", "line", "#a855f7", secondary=True),
        _constant_overlay(df, rsi_buy,  f"RSI Buy={rsi_buy}",  "dashed", "#22c55e", secondary=True),
        _constant_overlay(df, rsi_sell, f"RSI Sell={rsi_sell}", "dashed", "#ef4444", secondary=True),
    ]

    signals = []
    for i in range(1, len(df)):
        if pd.isna(rsi.iloc[i]):
            continue
        if rsi.iloc[i - 1] >= rsi_buy and rsi.iloc[i] < rsi_buy:
            signals.append(_annotation(df, i, "BUY", f"RSI dips below {rsi_buy} (oversold)"))
        elif rsi.iloc[i - 1] <= rsi_sell and rsi.iloc[i] > rsi_sell:
            signals.append(_annotation(df, i, "SELL", f"RSI rises above {rsi_sell} (overbought)"))

    trace = [
        "1. Intent mapped to 'rsi_strategy' — reversal/bounce regime.",
        "2. RSI(14) computed on Close prices.",
        f"3. BUY when RSI crosses below {rsi_buy} (oversold threshold).",
        f"4. SELL when RSI crosses above {rsi_sell} (overbought threshold).",
        f"5. {len(signals)} RSI threshold crossing(s) detected.",
    ]

    return overlays, signals, trace


def _macd_crossover_layer(df: pd.DataFrame, entry: dict):
    ema12  = _ema_series(df["Close"], 12)
    ema26  = _ema_series(df["Close"], 26)
    macd   = ema12 - ema26
    signal = _ema_series(macd, 9)
    hist   = macd - signal

    overlays = [
        _series_to_overlay(df, macd,   "MACD",        "line",      "#6366f1", secondary=True),
        _series_to_overlay(df, signal, "MACD Signal", "line",      "#f59e0b", secondary=True),
        _series_to_overlay(df, hist,   "MACD Hist",   "histogram", "#94a3b8", secondary=True),
    ]

    signals = []
    for i in range(1, len(df)):
        if pd.isna(macd.iloc[i]) or pd.isna(signal.iloc[i]):
            continue
        prev_above = macd.iloc[i - 1] > signal.iloc[i - 1]
        curr_above = macd.iloc[i] > signal.iloc[i]
        if not prev_above and curr_above:
            signals.append(_annotation(df, i, "BUY", "MACD crosses above Signal ↑"))
        elif prev_above and not curr_above:
            signals.append(_annotation(df, i, "SELL", "MACD crosses below Signal ↓"))

    trace = [
        "1. Intent mapped to 'macd_crossover' — momentum-with-confirmation regime.",
        "2. MACD = EMA12 − EMA26; Signal = EMA9(MACD); Histogram = MACD − Signal.",
        "3. BUY when MACD crosses above Signal line.",
        "4. SELL when MACD crosses below Signal line.",
        f"5. {len(signals)} MACD crossover(s) detected.",
    ]

    return overlays, signals, trace


def _momentum_breakout_layer(df: pd.DataFrame, entry: dict):
    period = 20
    high_channel = df["High"].rolling(period).max()
    low_channel  = df["Low"].rolling(period).min()

    overlays = [
        _series_to_overlay(df, high_channel, f"{period}-High Channel", "dashed", "#f59e0b"),
        _series_to_overlay(df, low_channel,  f"{period}-Low Channel",  "dashed", "#6366f1"),
    ]

    signals = []
    for i in range(1, len(df)):
        if pd.isna(high_channel.iloc[i]) or pd.isna(low_channel.iloc[i]):
            continue
        if df["Close"].iloc[i] > high_channel.iloc[i - 1]:
            signals.append(_annotation(df, i, "BUY", f"Breakout above {period}-period high"))
        elif df["Close"].iloc[i] < low_channel.iloc[i - 1]:
            signals.append(_annotation(df, i, "SELL", f"Breakdown below {period}-period low"))

    trace = [
        "1. Intent mapped to 'momentum_breakout' — breakout/aggressive regime.",
        f"2. {period}-period rolling High channel and Low channel computed.",
        f"3. BUY when Close breaks above rolling {period}-High.",
        f"4. SELL when Close breaks below rolling {period}-Low.",
        f"5. {len(signals)} breakout/breakdown event(s) detected.",
    ]

    return overlays, signals, trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().capitalize() for c in df.columns]
    rename = {"Timestamp": "Date", "Time": "Date", "Datetime": "Date"}
    df.rename(columns=rename, inplace=True)
    if "Date" not in df.columns:
        df["Date"] = list(range(len(df)))
    return df


def _ema_series(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi_series(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _series_to_overlay(
    df: pd.DataFrame,
    series: pd.Series,
    label: str,
    line_type: str,
    color: str,
    secondary: bool = False,
) -> Dict[str, Any]:
    points = []
    for i, val in enumerate(series):
        if not pd.isna(val):
            date_val = df["Date"].iloc[i] if "Date" in df.columns else i
            points.append({"x": str(date_val), "y": round(float(val), 4)})
    return {"label": label, "type": line_type, "color": color, "secondary": secondary, "data": points}


def _constant_overlay(
    df: pd.DataFrame,
    value: float,
    label: str,
    line_type: str,
    color: str,
    secondary: bool = False,
) -> Dict[str, Any]:
    points = []
    for i in range(len(df)):
        date_val = df["Date"].iloc[i] if "Date" in df.columns else i
        points.append({"x": str(date_val), "y": value})
    return {"label": label, "type": line_type, "color": color, "secondary": secondary, "data": points}


def _annotation(df: pd.DataFrame, idx: int, signal_type: str, label: str) -> Dict[str, Any]:
    date_val = df["Date"].iloc[idx] if "Date" in df.columns else idx
    price    = round(float(df["Close"].iloc[idx]), 4)
    return {"x": str(date_val), "y": price, "type": signal_type, "label": label}