from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Dict
import pandas as pd
import numpy as np
import yfinance as yf

class MarketDataProvider(ABC):
    name = 'abstract'

    @abstractmethod
    def get_history(self, ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def get_live_snapshot(self, ticker: str, interval: str) -> List[Dict]:
        raise NotImplementedError


def flatten_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ['_'.join([str(c) for c in col if c]).strip('_') for col in df.columns]
    col_map = {}
    for col in df.columns:
        for standard in ['Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close']:
            if col.startswith(standard):
                col_map[col] = standard
                break
    df.rename(columns=col_map, inplace=True)
    df = df.loc[:, ~df.columns.duplicated()]
    return df

class YFinanceProvider(MarketDataProvider):
    name = 'yfinance-temporary'

    def get_history(self, ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        raw = yf.download(ticker, start=start, end=end, interval=interval, auto_adjust=False, progress=False)
        if raw.empty:
            return pd.DataFrame()
        return flatten_yf_columns(raw)

    def get_live_snapshot(self, ticker: str, interval: str) -> List[Dict]:
        interval_map = {
            '1m': ('1m', '1d'),
            '5m': ('5m', '5d'),
            '15m': ('15m', '5d'),
            '1h': ('60m', '30d'),
            '1d': ('1d', '180d'),
        }
        yf_interval, yf_period = interval_map.get(interval, ('5m', '5d'))
        raw = yf.download(ticker, period=yf_period, interval=yf_interval, auto_adjust=False, progress=False)
        if raw.empty:
            return []
        raw = flatten_yf_columns(raw)
        candles = []
        for idx, row in raw.tail(200).iterrows():
            try:
                o, h, l, c = float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])
                v = int(float(row['Volume']))
                if any(np.isnan(x) for x in [o, h, l, c]):
                    continue
                candles.append({'time': int(idx.timestamp()), 'open': round(o, 2), 'high': round(h, 2), 'low': round(l, 2), 'close': round(c, 2), 'volume': v})
            except Exception:
                continue
        return candles

class UpstoxProvider(MarketDataProvider):
    name = 'upstox-plug-in-pending'

    def __init__(self, access_token: str = '', instrument_map: dict | None = None):
        self.access_token = access_token
        self.instrument_map = instrument_map or {}

    def get_history(self, ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
        raise NotImplementedError('Implement official Upstox historical candle fetch here.')

    def get_live_snapshot(self, ticker: str, interval: str) -> List[Dict]:
        raise NotImplementedError('Implement Upstox market data websocket or snapshot here.')