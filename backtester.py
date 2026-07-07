from __future__ import annotations

from typing import Dict, List, Tuple, Any
import numpy as np
import pandas as pd


def _col(df: pd.DataFrame, name: str) -> str:
    if name in df.columns:
        return name
    for c in df.columns:
        if c.lower() == name.lower():
            return c
    raise KeyError(f"Missing column: {name}")


def add_indicators(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    df = df.copy()

    open_col = _col(df, "Open")
    high_col = _col(df, "High")
    low_col = _col(df, "Low")
    close_col = _col(df, "Close")
    volume_col = _col(df, "Volume")

    fast = int(params.get("fastMA", 20))
    slow = int(params.get("slowMA", 50))
    atr_period = int(params.get("atrPeriod", 14))

    df["EMA_FAST"] = df[close_col].ewm(span=fast, adjust=False).mean()
    df["EMA_SLOW"] = df[close_col].ewm(span=slow, adjust=False).mean()

    prev_close = df[close_col].shift(1)
    tr1 = df[high_col] - df[low_col]
    tr2 = (df[high_col] - prev_close).abs()
    tr3 = (df[low_col] - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR"] = df["TR"].rolling(atr_period).mean()

    delta = df[close_col].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    ema12 = df[close_col].ewm(span=12, adjust=False).mean()
    ema26 = df[close_col].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    df["BB_MID"] = df[close_col].rolling(20).mean()
    bb_std = df[close_col].rolling(20).std()
    k = float(params.get("mrK", 2.0))
    df["BB_UPPER"] = df["BB_MID"] + (k * bb_std)
    df["BB_LOWER"] = df["BB_MID"] - (k * bb_std)

    df["Volume_SMA"] = df[volume_col].rolling(20).mean()
    return df


def _make_trade(date, signal, entry_price, exit_price, qty, fees):
    pnl = (exit_price - entry_price) * qty if signal == "BUY" else (entry_price - exit_price) * qty
    pnl -= fees
    pnl_pct = (pnl / (entry_price * qty) * 100) if entry_price and qty else 0
    return {
        "date": str(date),
        "signal": signal,
        "entryPrice": round(float(entry_price), 2),
        "exitPrice": round(float(exit_price), 2),
        "shares": int(qty),
        "fees": round(float(fees), 2),
        "pnl": round(float(pnl), 2),
        "pnlPct": round(float(pnl_pct), 2),
    }


def run_strategy(strategy: str, df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[List[Dict], List[Dict], float, float, float]:
    close_col = _col(df, "Close")
    open_col = _col(df, "Open")

    initial_capital = float(params.get("initialCapital", 100000))
    stop_loss = float(params.get("stopLoss", 2.0)) / 100.0
    take_profit = float(params.get("takeProfit", 6.0)) / 100.0
    slippage = float(params.get("slippage", 0.1)) / 100.0
    tx_cost = float(params.get("transactionCost", 0.05)) / 100.0

    cash = initial_capital
    position = 0
    entry_price = None
    entry_date = None
    trades = []
    equity_curve = []

    rsi_buy_thresh = float(params.get("rsiBuy", params.get("rsi_buy", 30.0)))
    rsi_sell_thresh = float(params.get("rsiSell", params.get("rsi_sell", 70.0)))

    def fees_for(value):
        return value * tx_cost

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i] if df.index is not None else i
        price = float(row[close_col])
        open_price = float(row[open_col])

        signal = None

        if strategy == "golden_cross":
            if i > 0 and df["EMA_FAST"].iloc[i - 1] <= df["EMA_SLOW"].iloc[i - 1] and row["EMA_FAST"] > row["EMA_SLOW"]:
                signal = "BUY"
            elif i > 0 and df["EMA_FAST"].iloc[i - 1] >= df["EMA_SLOW"].iloc[i - 1] and row["EMA_FAST"] < row["EMA_SLOW"]:
                signal = "SELL"

        elif strategy == "mean_reversion":
            if price < row["BB_LOWER"]:
                signal = "BUY"
            elif price > row["BB_UPPER"]:
                signal = "SELL"


        elif strategy == "rsi_strategy":

            if row["RSI"] < rsi_buy_thresh:

                signal = "BUY"

            elif row["RSI"] > rsi_sell_thresh:

                signal = "SELL"

        elif strategy == "macd_crossover":
            if i > 0 and df["MACD"].iloc[i - 1] <= df["MACD_SIGNAL"].iloc[i - 1] and row["MACD"] > row["MACD_SIGNAL"]:
                signal = "BUY"
            elif i > 0 and df["MACD"].iloc[i - 1] >= df["MACD_SIGNAL"].iloc[i - 1] and row["MACD"] < row["MACD_SIGNAL"]:
                signal = "SELL"

        elif strategy == "momentum_breakout":
            if i >= 20:
                hh = df[close_col].iloc[i - 20:i].max()
                ll = df[close_col].iloc[i - 20:i].min()
                if price > hh:
                    signal = "BUY"
                elif price < ll:
                    signal = "SELL"

        if position == 0 and signal == "BUY":
            buy_price = price * (1 + slippage)
            qty = int(cash / buy_price)
            if qty > 0:
                cost = buy_price * qty
                f = fees_for(cost)
                cash -= (cost + f)
                position = qty
                entry_price = buy_price
                entry_date = date

        elif position > 0:
            stop_price = entry_price * (1 - stop_loss)
            target_price = entry_price * (1 + take_profit)

            exit_now = False
            if signal == "SELL":
                exit_now = True
            elif price <= stop_price:
                exit_now = True
            elif price >= target_price:
                exit_now = True

            if exit_now:
                sell_price = price * (1 - slippage)
                proceeds = sell_price * position
                f = fees_for(proceeds)
                cash += (proceeds - f)
                trades.append(_make_trade(entry_date, "BUY", entry_price, sell_price, position, f))
                position = 0
                entry_price = None
                entry_date = None

        equity = cash + (position * price if position > 0 else 0)
        buy_hold = initial_capital / float(df[close_col].iloc[0]) * price
        equity_curve.append({
            "date": str(date),
            "strategy": round(float(equity), 2),
            "buyHold": round(float(buy_hold), 2),
        })

    last_price = float(df[close_col].iloc[-1])
    bh_shares = initial_capital / float(df[close_col].iloc[0])
    return equity_curve, trades, cash, bh_shares, last_price


def calculate_metrics(equity: List[Dict], trades: List[Dict], initial_capital: float, bh_shares: float, last_price: float) -> Dict[str, Any]:
    if not equity:
        return {
            "totalReturn": 0,
            "maxDrawdown": 0,
            "sharpeRatio": 0,
            "winRate": 0,
            "totalTrades": 0,
            "finalValue": initial_capital,
            "buyHoldValue": round(float(bh_shares * last_price), 2),
        }

    values = pd.Series([p["strategy"] for p in equity], dtype="float64")
    returns = values.pct_change().dropna()

    total_return = ((values.iloc[-1] / initial_capital) - 1) * 100
    rolling_max = values.cummax()
    drawdown = ((values / rolling_max) - 1) * 100
    max_dd = abs(drawdown.min()) if not drawdown.empty else 0

    sharpe = 0.0
    if len(returns) > 1 and returns.std() != 0:
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252)

    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    win_rate = (wins / len(trades) * 100) if trades else 0

    final_value = float(values.iloc[-1])
    buy_hold_value = float(bh_shares * last_price)

    return {
        "totalReturn": round(float(total_return), 2),
        "maxDrawdown": round(float(max_dd), 2),
        "sharpeRatio": round(float(sharpe), 2),
        "winRate": round(float(win_rate), 2),
        "totalTrades": len(trades),
        "finalValue": round(final_value, 2),
        "buyHoldValue": round(buy_hold_value, 2),
    }