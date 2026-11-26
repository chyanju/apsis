#!/usr/bin/env python3
"""Score the CodeQL and CodeQL Extended rows of the paper's baseline table over the 135 benchmarks.

CodeQL Extended flags an artifact when CodeQL or ../mixedpy (the other four frameworks) reports it.

Usage: python3 score.py [--codeql FILE] [--mixedpy FILE]   (default: the records.json of each baseline)
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def flagged(path):
    records = json.load(open(path))
    errors = [r["base"] for r in records if "error" in r]
    if errors:
        raise SystemExit(f"{path}: {len(errors)} artifacts failed to run, for example {errors[0]}; run them again")
    return {r["base"] for r in records if r["fired"]}


def row(tp, fp, n):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / n
    f1 = 2 * p * r / (p + r) if p else None
    fmt = lambda x: "---" if x is None else f"{x:.2f}"
    return f"TP {tp:3d}  FP {fp:3d}  |  P {fmt(p)}  R {fmt(r)}  F1 {fmt(f1)}  FPR {fp / n:.2f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--codeql", default=os.path.join(HERE, "records.json"))
    ap.add_argument("--mixedpy", default=os.path.join(ROOT, "baselines", "mixedpy", "records.json"))
    args = ap.parse_args()
    cases = json.load(open(os.path.join(ROOT, "benchmarks", "evaluation-set.json")))["cases"]
    cq = flagged(args.codeql)
    ext = cq | flagged(args.mixedpy)
    print(f"{'framework':16s} {'benchmarks':>10s}   CodeQL TP/FP   Extended TP/FP")
    for fw in sorted({c["framework"] for c in cases}):
        cs = [c for c in cases if c["framework"] == fw]
        counts = [(sum(c["case"] in s for c in cs), sum(c["fixed"] in s for c in cs)) for s in (cq, ext)]
        print(f"{fw:16s} {len(cs):10d}   {counts[0][0]:6d}/{counts[0][1]:<6d}  {counts[1][0]:8d}/{counts[1][1]:<6d}")
    print()
    for name, s in (("CodeQL", cq), ("CodeQL Extended", ext)):
        tp = sum(c["case"] in s for c in cases)
        fp = sum(c["fixed"] in s for c in cases)
        print(f"{name:16s} {len(cases)} benchmarks: {row(tp, fp, len(cases))}")


if __name__ == "__main__":
    main()
