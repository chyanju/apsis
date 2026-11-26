#!/usr/bin/env python3
"""Run the CodeQL baseline over the Haystack and LangGraph artifacts of the benchmark suite.

Usage:
  CODEQL=$PWD/codeql/codeql python3 run_codeql.py [--jobs N]   # every covered artifact
  CODEQL=$PWD/codeql/codeql python3 run_codeql.py --smoke      # build one database to check the toolchain
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
EVALUATION_SET = os.path.join(ROOT, "benchmarks", "evaluation-set.json")
CODEQL = os.environ.get("CODEQL", os.path.join(HERE, "codeql", "codeql"))
DBS = os.path.join(HERE, "dbs")
QUERIES = os.path.join(HERE, "queries", "checks")  # the active queries (queries/disabled/ is not run)
RESULTS = os.path.join(HERE, "results")
RECORDS = os.path.join(HERE, "records.json")
FW = ["haystack", "langgraph"]  # the frameworks whose graphs the queries can rebuild


def build_db(case_dir, db_dir):
    if os.path.isdir(db_dir):
        return True
    p = subprocess.run([CODEQL, "database", "create", db_dir, "--language=python",
                        f"--source-root={case_dir}", "--overwrite"],
                       capture_output=True, text=True)
    return p.returncode == 0


def analyze(db_dir, threads=0):
    """Run queries/checks over a DB; return the set of fired rule ids (empty = clean), or None on error."""
    out = os.path.join(RESULTS, os.path.basename(db_dir) + ".sarif")
    p = subprocess.run([CODEQL, "database", "analyze", db_dir, QUERIES,
                        "--format=sarifv2.1.0", f"--output={out}", "--rerun", f"--threads={threads}"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-300:] + "\n")
        return None
    doc = json.load(open(out))
    return {r.get("ruleId", "?") for run in doc.get("runs", []) for r in run.get("results", [])}


def artifacts():
    """(framework, artifact, is_buggy) for every covered artifact of the benchmark suite."""
    cases = json.load(open(EVALUATION_SET))["cases"]
    return [(c["framework"], a, a == c["case"]) for c in cases if c["framework"] in FW
            for a in (c["case"], c["fixed"])]


def main(jobs):
    os.makedirs(DBS, exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)
    threads = 0 if jobs == 1 else 1

    def one(job):
        fw, base, is_buggy = job
        rec = {"fw": fw, "base": base, "is_buggy": is_buggy}
        db = os.path.join(DBS, base)
        if not build_db(os.path.join(ROOT, "benchmarks", fw, base), db):
            return {**rec, "error": "database create failed"}
        fired = analyze(db, threads)
        if fired is None:
            return {**rec, "error": "database analyze failed"}
        print(f"  {base:28} buggy={int(is_buggy)} flagged={int(bool(fired))} {sorted(fired)}", flush=True)
        return {**rec, "fired": sorted(fired)}

    with ThreadPoolExecutor(jobs) as ex:
        records = list(ex.map(one, artifacts()))
    json.dump(records, open(RECORDS, "w"), indent=2)
    errors = [r for r in records if "error" in r]
    print(f"{len(records)} artifacts, {len(errors)} errors -> records.json (score with baselines/codeql/score.py)")
    for r in errors:
        print(f"  {r['base']}: {r['error']}")


def smoke():
    os.makedirs(DBS, exist_ok=True)
    fw, base, _ = artifacts()[0]
    print(f"Building DB for {base} ...")
    ok = build_db(os.path.join(ROOT, "benchmarks", fw, base), os.path.join(DBS, "smoke"))
    print("build:", "OK" if ok else "FAILED — check CODEQL path / setup.sh")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jobs", type=int, default=1, help="artifacts processed in parallel (default 1)")
    ap.add_argument("--smoke", action="store_true", help="only build one database")
    args = ap.parse_args()
    smoke() if args.smoke else main(args.jobs)
