"""Create a clearly-labelled partial snapshot without touching a live clean run."""
from __future__ import annotations
import csv, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "paper_evaluation_clean"
OUT = SOURCE / "partial_snapshot"
OUT.mkdir(parents=True, exist_ok=True)

def read_csv(name):
    with (SOURCE / name).open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))
def write_csv(name, fields, rows):
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
def truth(v): return str(v).lower() == "true"
def number(v):
    try: return float(v)
    except: return None

semantic = read_csv("semantic_mapping_results.csv")
prompts = read_csv("prompt_set.csv")
# Snapshot only complete rows that have a declared mapper; no fallback source is present.
semantic = [r for r in semantic if r.get("mapper") in {"heuristic", "llm"}]
semantic.sort(key=lambda r: (r["prompt_id"], r["mapper"]))
write_csv("semantic_mapping_results_PARTIAL.csv", list(semantic[0]) if semantic else [], semantic)
write_csv("prompt_set.csv", list(prompts[0]) if prompts else [], prompts)

overall, family = [], []
families = ["trend", "mean_reversion", "reversal", "macd", "breakout"]
for mapper in ["heuristic", "llm"]:
    rows = [r for r in semantic if r["mapper"] == mapper]
    lat = [number(r["mapping_latency_ms"]) for r in rows if number(r["mapping_latency_ms"]) is not None]
    overall.append({"Mapper": "Heuristic" if mapper == "heuristic" else "Direct LLM (partial)", "Prompts observed": len(rows), "Correct strategy": sum(truth(r["strategy_match"]) for r in rows), "Strategy accuracy (%)": round(100 * sum(truth(r["strategy_match"]) for r in rows) / len(rows), 1) if rows else "", "Correct risk": sum(truth(r["risk_match"]) for r in rows), "Risk accuracy (%)": round(100 * sum(truth(r["risk_match"]) for r in rows) / len(rows), 1) if rows else "", "Schema-valid": sum(truth(r["schema_valid"]) for r in rows), "Schema-valid (%)": round(100 * sum(truth(r["schema_valid"]) for r in rows) / len(rows), 1) if rows else "", "Mean latency (ms)": round(mean(lat), 2) if lat else "", "Median latency (ms)": round(median(lat), 2) if lat else ""})
    for f in families:
        q = [r for r in rows if r["prompt_family"] == f]
        if not q: continue
        qlat = [number(r["mapping_latency_ms"]) for r in q if number(r["mapping_latency_ms"]) is not None]
        family.append({"Mapper": "Heuristic" if mapper == "heuristic" else "Direct LLM (partial)", "Prompt family": f, "Prompts observed": len(q), "Correct strategy": sum(truth(r["strategy_match"]) for r in q), "Strategy accuracy (%)": round(100 * sum(truth(r["strategy_match"]) for r in q) / len(q), 1), "Correct risk": sum(truth(r["risk_match"]) for r in q), "Risk accuracy (%)": round(100 * sum(truth(r["risk_match"]) for r in q) / len(q), 1), "Schema-valid (%)": round(100 * sum(truth(r["schema_valid"]) for r in q) / len(q), 1), "Mean latency (ms)": round(mean(qlat), 2) if qlat else ""})
write_csv("overall_mapping_results_PARTIAL.csv", list(overall[0]), overall)
write_csv("per_family_mapping_results_PARTIAL.csv", list(family[0]), family)

strategies = ["golden_cross", "mean_reversion", "rsi_strategy", "macd_crossover", "momentum_breakout"]
for mapper in ["heuristic", "llm"]:
    rows = [r for r in semantic if r["mapper"] == mapper]
    matrix = []
    for expected in strategies:
        matrix.append({"expected_strategy": expected, **{actual: sum(r["expected_strategy"] == expected and r["produced_strategy"] == actual for r in rows) for actual in strategies}})
    write_csv(f"confusion_matrix_{mapper}_PARTIAL.csv", ["expected_strategy", *strategies], matrix)

failures = [r for r in semantic if not truth(r["strategy_match"]) or not truth(r["risk_match"]) or not truth(r["schema_valid"])]
write_csv("failure_analysis_PARTIAL.csv", list(semantic[0]) if semantic else [], failures)
manifest = {"snapshot_created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "status": "PARTIAL_NOT_FINAL", "heuristic_semantic_rows": sum(r["mapper"] == "heuristic" for r in semantic), "direct_llm_semantic_rows": sum(r["mapper"] == "llm" for r in semantic), "required_direct_llm_rows": 50, "backtest_rows": 0, "heuristic_fallback_rows_counted_as_llm": 0, "warning": "Direct LLM rows are an incomplete sample and must not be treated as final paper results."}
(OUT / "snapshot_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
(OUT / "README_PARTIAL.md").write_text(f"# SimuTrade Partial Evaluation Snapshot\n\nThis snapshot contains {manifest['heuristic_semantic_rows']} heuristic mappings and {manifest['direct_llm_semantic_rows']} direct LLM mappings. It is not a final paper result because the required 50 direct LLM mappings and 1,000 downstream backtests are incomplete.\n\nNo heuristic fallback is counted as an LLM result.\n", encoding="utf-8")
print(json.dumps(manifest))
