#!/usr/bin/env python3
"""Score the LLM judges of the paper's baseline table over the 135 benchmarks.

A Strict detection must also name the benchmark's category (ground_truth/<benchmark>.json).

Usage: python3 score.py [NAME=RECORDS.json ...]   (default: the paper's three runs in runs/)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RUNS = {"GPT-5.5": os.path.join(HERE, "runs", "gpt-5.5-xhigh.json"),
        "Opus-4.8": os.path.join(HERE, "runs", "opus-4.8-xhigh.json"),
        "DeepSeek-V4": os.path.join(HERE, "runs", "deepseek-v4-pro-max.json")}


def row(tp, fp, n):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / n
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return f"{p:.2f}  {r:.2f}  {f1:.2f}  {fp / n:.2f}"


def main(runs):
    cases = json.load(open(os.path.join(ROOT, "benchmarks", "evaluation-set.json")))["cases"]
    n = len(cases)
    print(f"{'judge':22s} {'P':>4s}  {'R':>4s}  {'F1':>4s}  {'FPR':>4s}")
    for name, path in runs.items():
        recs = {r["base"]: r for r in json.load(open(path))}
        missing = [a for c in cases for a in (c["case"], c["fixed"]) if a not in recs or "error" in recs[a]]
        if missing:
            raise SystemExit(f"{path}: no verdict for {len(missing)} artifacts, for example {missing[0]};"
                             " continue the run with run_llm.py --resume before scoring")
        tp = sum(bool(recs[c["case"]]["flagged"]) for c in cases)
        fp = sum(bool(recs[c["fixed"]]["flagged"]) for c in cases)
        strict = 0
        for c in cases:
            b = recs[c["case"]]
            truth = set(json.load(open(os.path.join(HERE, "ground_truth", c["case"] + ".json")))["families"])
            strict += bool(b["flagged"] and truth & set(b["flagged_families"]))
        print(f"{name:22s} {row(tp, fp, n)}")
        print(f"{name + ' Strict':22s} {row(strict, fp, n)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(dict(a.split("=", 1) for a in args) if args else RUNS)
