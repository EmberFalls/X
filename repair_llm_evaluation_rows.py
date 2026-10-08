"""Repair duplicate/missing IDs in an LLM evaluation CSV without changing valid rows."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from run_paper_evaluation import (
    END_DATE,
    INTERVAL,
    START_DATE,
    TICKERS,
    load_project_environment,
    map_prompt,
    prepare_data,
    write_evaluation_row,
)


BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "outputs" / "paper_eval_llm_500.csv"
FINAL_PATH = BASE / "outputs" / "paper_eval_llm_500_final.csv"
PROMPTS = {item["id"]: item for item in json.loads((BASE / "evaluation_prompts_50.json").read_text(encoding="utf-8"))}


def main() -> None:
    load_project_environment()
    with CSV_PATH.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        original_rows = list(reader)
    valid = [row for row in original_rows if row.get("requested_mapping_path") == "llm"]
    unique = {}
    for row in valid:
        unique.setdefault(row["evaluation_id"], row)
    expected = {f"llm_{repeat}_{spec_id}_{ticker}" for repeat in (1, 2) for spec_id in PROMPTS for ticker in TICKERS}
    missing = sorted(expected - set(unique))
    if len(missing) != 2:
        raise RuntimeError(f"Expected exactly two missing rows, found {missing}")
    data_cache = prepare_data()
    with FINAL_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for evaluation_id in sorted(unique):
            writer.writerow(unique[evaluation_id])
        for evaluation_id in missing:
            _, repeat, prompt_id, ticker = evaluation_id.split("_", 3)
            spec = PROMPTS[prompt_id]
            payload, latency = map_prompt(spec["prompt"], ticker, "llm")
            write_evaluation_row(writer, int(repeat), spec, ticker, "llm", payload, latency, None, data_cache[ticker])
    print(f"Repaired {len(missing)} rows; wrote {len(unique) + len(missing)} unique evaluation rows to {FINAL_PATH}.")


if __name__ == "__main__":
    main()
