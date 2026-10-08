import pandas as pd
tech = pd.read_json('logs/technical_eval.ndjson', lines=True)
print(tech['mapping_source'].value_counts())
print(tech['fallback_reason'].value_counts(dropna=False))
print(tech['latency_ms'].describe())