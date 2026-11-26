#!/usr/bin/env python3
"""Run the mixedpy baseline over the Langflow, Flowise, AutoGen and Agent Framework artifacts of the benchmark suite.

Usage: python3 run_mixedpy.py
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
EVALUATION_SET = os.path.join(ROOT, "benchmarks", "evaluation-set.json")
RECORDS = os.path.join(HERE, "records.json")

import detectors  # noqa: E402

FE = {
    "langflow": "fe_langflow",
    "flowise": "fe_flowise",
    "autogen": "fe_autogen",
    "agent-framework": "fe_agentframework",
}


def load_graph(fw, entry):
    return importlib.import_module(FE[fw]).load(entry)


def main():
    cases = json.load(open(EVALUATION_SET))["cases"]
    records, not_covered = [], 0
    for c in cases:
        fw = c["framework"]
        if fw not in FE:
            continue
        for base in (c["case"], c["fixed"]):
            d = os.path.join(ROOT, "benchmarks", fw, base)
            entry = json.load(open(os.path.join(d, "meta.json")))["entry"].split(":")[0]
            if entry.endswith(".csproj"):
                not_covered += 1
                continue
            rec = {"fw": fw, "base": base, "is_buggy": base == c["case"]}
            try:
                fired = sorted(detectors.run_all(load_graph(fw, os.path.join(d, entry))))
            except Exception as ex:
                print(f"  {base:28} ERROR {type(ex).__name__}: {str(ex)[:80]}")
                records.append({**rec, "error": f"{type(ex).__name__}: {str(ex)[:200]}"})
                continue
            print(f"  {base:28} buggy={int(rec['is_buggy'])} flagged={int(bool(fired))} {fired}")
            records.append({**rec, "fired": fired})
    json.dump(records, open(RECORDS, "w"), indent=2)
    errors = sum("error" in r for r in records)
    print(f"{len(records)} artifacts, {errors} errors, {not_covered} C# projects not covered"
          " -> records.json (score with baselines/codeql/score.py)")


if __name__ == "__main__":
    main()
