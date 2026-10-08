import pandas as pd

# --- Load full logs ---
tech = pd.read_json('logs/technical_eval.ndjson', lines=True)
trading = pd.read_json('logs/trading_eval.ndjson', lines=True)
usability = pd.read_json('logs/usability_eval.ndjson', lines=True)

# --- Export full raw CSVs ---
tech.to_csv('technical_eval_raw.csv', index=False)
trading.to_csv('trading_eval_raw.csv', index=False)
usability.to_csv('usability_eval_raw.csv', index=False)

# --- Normalize timestamps ---
tech['logged_at'] = pd.to_datetime(tech['logged_at'])
trading['logged_at'] = pd.to_datetime(trading['logged_at'])

# --- Clean same-day subsets ---
tech_clean = tech[tech['logged_at'] >= '2026-07-19'].copy()
trading_clean = trading[trading['logged_at'] >= '2026-07-19'].copy()

tech_clean.to_csv('technical_eval_clean.csv', index=False)
trading_clean.to_csv('trading_eval_clean.csv', index=False)

print("=== CLEAN TECHNICAL COMPARISON ===")
print(tech_clean['mapping_source'].value_counts())
print()
print("Strategy match accuracy by method:")
print(tech_clean.groupby('mapping_source')['strategy_match'].mean())
print()
print("Average latency (ms) by method:")
print(tech_clean.groupby('mapping_source')['latency_ms'].mean())
print()

print("=== CLEAN TRADING COMPARISON ===")
print(trading_clean['mapping_source'].value_counts())
print()
print("Average return (%) by method:")
print(trading_clean.groupby('mapping_source')['total_return_pct'].mean())
print()
print("Average Sharpe by method:")
print(trading_clean.groupby('mapping_source')['sharpe_ratio'].mean())
print()
print("Average max drawdown (%) by method:")
print(trading_clean.groupby('mapping_source')['max_drawdown_pct'].mean())
print()
print("Average win rate (%) by method:")
print(trading_clean.groupby('mapping_source')['win_rate_pct'].mean())
print()
print("Average trade count by method:")
print(trading_clean.groupby('mapping_source')['total_trades'].mean())
print()
print("MACD rows only:")
print(
    trading_clean[
        trading_clean['params_snapshot'].astype(str).str.contains(
            'MACD crossover with momentum confirmation on TCS',
            na=False
        )
    ][['ticker', 'strategy_id', 'mapping_source', 'total_return_pct', 'sharpe_ratio', 'max_drawdown_pct']]
)