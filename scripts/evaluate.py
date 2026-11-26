#!/usr/bin/env python3
"""Run Apsis on the paper's benchmark suite and print the numbers of Table 4, the Apsis rows of Table 5
and Fig. 8.

    cargo build --release
    python3 scripts/setup_envs.py          # once: creates .envs/<environment> (benchmarks/environments.json)
    python3 scripts/evaluate.py --check    # tables + a cell-by-cell comparison with the paper
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

FRONTEND_MODULE = {
    "haystack": "apsis_haystack",
    "langgraph": "apsis_langgraph",
    "autogen": "apsis_autogen",
    "agent-framework": "apsis_agent_framework",
    "langflow": "apsis_langflow",
    "flowise": "apsis_flowise",
}
FRAMEWORKS = ["haystack", "langgraph", "flowise", "langflow", "autogen", "agent-framework"]
CATEGORIES = [
    "Stalled & Runaway Workflows",
    "Broken Data Handoffs",
    "Misrouted Dispatch",
    "Corrupted Shared State",
    "Unwired Subflows",
    "Role & Interrupt Violations",
]
# Fig. 8: structural-only is the same run with the findings of these detectors ignored.
BEHAVIORAL_DETECTORS = {"readiness-liveness", "channel-write-merge", "read-after-write"}
# The twelve detectors in the order of Fig. 7, with the paper's numbers and names.
DETECTORS = [
    ("readiness-liveness", "β1 starved-step"),
    ("cycle-termination", "β2 runaway-loop"),
    ("type-contract", "β3 mistyped-handoff"),
    ("target-resolution", "β4 missing-route-target"),
    ("router-branch-gating", "β5 ungated-branch-merge"),
    ("dangling-output", "β6 dead-end-branch"),
    ("channel-write-merge", "β7 racing-channel-write"),
    ("shared-instance-aliasing", "β8 aliased-instance"),
    ("read-after-write", "β9 stale-read"),
    ("subflow-port-binding", "β10 unwired-subflow-input"),
    ("binding-capability", "β11 over-privileged-coordinator"),
    ("interrupt-ordering", "β12 ungated-interrupt"),
]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Runner:
    def __init__(self, args):
        self.tree = os.path.abspath(args.tree)
        self.apsis = os.path.abspath(args.apsis)
        self.envs_dir = os.path.abspath(args.envs)
        self.envs = load_json(os.path.join(REPO, "benchmarks", "environments.json"))
        self.dotnet_frontend = os.path.abspath(args.dotnet_frontend or os.path.join(self.envs_dir, "dotnet", "frontend",
                                                                                     "apsis-agent-framework-dotnet"))
        self.workdir = args.keep or tempfile.mkdtemp(prefix="apsis-eval-")
        for sub in ("ir", "stderr", "cwd"):
            os.makedirs(os.path.join(self.workdir, sub), exist_ok=True)

    def interpreter(self, framework, name, case_dir):
        """The Python interpreter the front-end of this artifact runs under (see environments.json)."""
        env = self.envs["case_overrides"].get(name)
        if env is None:
            requirements = ""
            path = os.path.join(case_dir, "requirements.txt")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    requirements = f.read()
            for rule in self.envs["rules"]:
                if rule["framework"] == framework and rule["requirements_contain"] in requirements:
                    env = rule["environment"]
                    break
            else:
                env = self.envs["framework_default"][framework]
        if env is None:
            return sys.executable  # a flow.json front-end: no framework needed
        python = os.path.join(self.envs_dir, env, "bin", "python")
        if not os.path.exists(python):
            raise FileNotFoundError(f"environment '{env}' not found at {python}; run scripts/setup_envs.py")
        return python

    def run(self, framework, name):
        """Extract and analyze one artifact. Returns {'findings': [[detector, rule, location], ...]} or {'error': ...}."""
        case_dir = os.path.join(self.tree, "benchmarks", framework, name)
        started = time.time()
        try:
            meta = load_json(os.path.join(case_dir, "meta.json"))
            python = None if ".csproj:" in meta["entry"] else self.interpreter(framework, name, case_dir)
        except (OSError, ValueError) as e:
            return {"error": str(e)}
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") or k.startswith(("DOTNET_", "NUGET_"))}
        env["PYTHONPATH"] = os.pathsep.join(
            [os.path.join(self.tree, "frontends", framework), os.path.join(self.tree, "frontends", "common")]
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        ir_path = os.path.join(self.workdir, "ir", name + ".json")
        cwd = tempfile.mkdtemp(dir=os.path.join(self.workdir, "cwd"))
        source = os.path.join(case_dir, meta["entry"])
        if ".csproj:" in meta["entry"]:
            if not os.path.exists(self.dotnet_frontend):
                return {"error": f"the .NET front-end is not at {self.dotnet_frontend}; run scripts/setup_envs.py dotnet"}
            launcher = ["dotnet"] if self.dotnet_frontend.endswith(".dll") else []
            # filled by scripts/setup_envs.py dotnet, so the project builds incrementally
            build = os.path.join(self.envs_dir, "dotnet", "build", name)
            cmd = launcher + [self.dotnet_frontend, source, "-o", ir_path, "--artifacts", build]
        else:
            cmd = [python, "-m", FRONTEND_MODULE[framework], source, "-o", ir_path]
        try:
            fe = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return {"error": "front-end timed out"}
        if fe.stderr.strip():
            with open(os.path.join(self.workdir, "stderr", name + ".txt"), "w", encoding="utf-8") as f:
                f.write(fe.stderr)
        if fe.returncode != 0:
            last = fe.stderr.strip().splitlines()[-1] if fe.stderr.strip() else ""
            return {"error": f"front-end exit {fe.returncode}: {last[:200]}"}
        check = subprocess.run([self.apsis, "check", ir_path, "--json"], capture_output=True, text=True, timeout=120)
        try:
            doc = json.loads(check.stdout)
        except ValueError:
            return {"error": f"analyzer output is not JSON: {(check.stdout + check.stderr)[:200]}"}
        if "error" in doc:
            return {"error": "analyzer: " + doc["error"][:200]}
        findings = sorted({(f["detector"], f.get("rule", ""), f["location"]) for f in doc["findings"]})
        return {"findings": [list(f) for f in findings], "seconds": time.time() - started}


def ratio(num, den):
    return num / den if den else 0.0


def scores(tp, fn, fp, tn):
    p, r = ratio(tp, tp + fp), ratio(tp, tp + fn)
    return p, r, ratio(2 * p * r, p + r), ratio(fp, fp + tn)


def flagged(result, without=frozenset()):
    return any(f[0] not in without for f in result.get("findings", []))


def print_detectors(cases, results):
    """Per detector and per rule: how many buggy artifacts and how many fixed twins it fires on."""
    buggy = [c["case"] for c in cases]
    fixed = [c["fixed"] for c in cases]

    def fires(names, detector, rule=None):
        return sum(any(f[0] == detector and (rule is None or f[1] == rule) for f in results[n].get("findings", [])) for n in names)

    rules = {}
    for res in results.values():
        for d, r, _ in res.get("findings", []):
            rules.setdefault(d, set()).add(r)
    print(f"\nDetections per detector and rule ({len(buggy)} buggy artifacts, {len(fixed)} fixed twins)")
    print(f"  {'':54s} buggy fixed")
    for det, paper_name in DETECTORS:
        print(f"  {det + ' (' + paper_name + ')':54s} {fires(buggy, det):5d} {fires(fixed, det):5d}")
        for rule in sorted(rules.get(det, ())):
            print(f"  {'    ' + rule:54s} {fires(buggy, det, rule):5d} {fires(fixed, det, rule):5d}")


def summarize(cases, results):
    """Count TP/FN/FP/TN per framework and per category, for the full catalog and structural-only."""
    out = {"per_framework": {}, "per_category": {}}
    for key, field, names in (("per_framework", "framework", FRAMEWORKS), ("per_category", "category", CATEGORIES)):
        for name in names:
            group = [c for c in cases if c[field] == name]
            tp = sum(flagged(results[c["case"]]) for c in group)
            fp = sum(flagged(results[c["fixed"]]) for c in group)
            st = sum(flagged(results[c["case"]], BEHAVIORAL_DETECTORS) for c in group)
            out[key][name] = {"cases": len(group), "tp": tp, "fn": len(group) - tp, "fp": fp,
                              "tn": len(group) - fp, "structural_only_tp": st}
    tot = {k: sum(v[k] for v in out["per_framework"].values()) for k in ("cases", "tp", "fn", "fp", "tn", "structural_only_tp")}
    tot["recovered_by_behavioral"] = tot["tp"] - tot["structural_only_tp"]
    out["overall"] = tot
    return out


def print_tables(summary):
    def row(label, c):
        p, r, f1, fpr = scores(c["tp"], c["fn"], c["fp"], c["tn"])
        return f"  {label:30s} {c['cases']:4d} {c['cases']:4d} | {c['tp']:3d} {c['fn']:3d} {c['fp']:3d} | {p:.2f} {r:.2f} {f1:.2f} {fpr:.2f}"

    header = f"  {'':30s} #Bug #Fix |  TP  FN  FP |    P    R   F1  FPR"
    print("Detection per framework (Table 4)")
    print(header)
    for fw in FRAMEWORKS:
        print(row(fw, summary["per_framework"][fw]))
    print(row("Overall", summary["overall"]))
    print("\nDetection per category (Table 5, Apsis rows)")
    print(header)
    for cat in CATEGORIES:
        print(row(cat, summary["per_category"][cat]))
    print("\nRecall without and with the behavioral detectors (Fig. 8)")
    print(f"  {'':30s} structural-only      full")
    for cat in CATEGORIES:
        c = summary["per_category"][cat]
        print(f"  {cat:30s} {c['structural_only_tp']:3d}/{c['cases']:<3d} {ratio(c['structural_only_tp'], c['cases']):.2f}"
              f"   {c['tp']:3d}/{c['cases']:<3d} {ratio(c['tp'], c['cases']):.2f}")
    o = summary["overall"]
    print(f"  {'Overall':30s} {o['structural_only_tp']:3d}/{o['cases']:<3d} {ratio(o['structural_only_tp'], o['cases']):.2f}"
          f"   {o['tp']:3d}/{o['cases']:<3d} {ratio(o['tp'], o['cases']):.2f}")
    print(f"  bugs the behavioral detectors recover: {o['recovered_by_behavioral']}")


def compare_with_paper(summary, reference):
    """Compare every reported count with the paper's. Returns (lines, worse) where `worse` counts regressions."""
    paper = load_json(reference)
    lines, worse = [], 0

    def cell(where, what, measured, reference, higher_is_better):
        nonlocal worse
        if measured == reference:
            return
        better = (measured > reference) == higher_is_better
        worse += 0 if better else 1
        lines.append(f"  {'better' if better else 'worse '}  {where}: {what} {reference} -> {measured}")

    for key in ("per_framework", "per_category"):
        for name, ref in paper[key].items():
            got = summary[key][name]
            cell(name, "detected", got["tp"], ref["tp"], True)
            cell(name, "fixed twins flagged", got["fp"], ref["fp"], False)
            if "structural_only_tp" in ref:
                cell(name, "detected by the structural detectors alone", got["structural_only_tp"], ref["structural_only_tp"], True)
    o, ref = summary["overall"], paper["overall"]
    cell("overall", "detected", o["tp"], ref["tp"], True)
    cell("overall", "fixed twins flagged", o["fp"], ref["fp"], False)
    cell("overall", "bugs the behavioral detectors recover", o["recovered_by_behavioral"], ref["recovered_by_behavioral"], True)
    return lines, worse


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--envs", default=os.path.join(REPO, ".envs"), help="directory holding the environments (default: .envs)")
    ap.add_argument("--apsis", default=os.path.join(REPO, "target", "release", "apsis"), help="the analyzer binary")
    ap.add_argument("--dotnet-frontend", metavar="PATH",
                    help="the built .NET front-end, its executable or .dll (default: <envs>/dotnet/frontend, which "
                         "scripts/setup_envs.py dotnet creates)")
    ap.add_argument("--tree", default=REPO, help="checkout whose benchmarks/ and frontends/ are evaluated (default: this one)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--keep", metavar="DIR", help="keep the IR files and front-end stderr in DIR")
    ap.add_argument("--list", action="store_true", help="list the missed benchmarks and the flagged fixed twins")
    ap.add_argument("--by-detector", action="store_true", help="print the detections per detector and per rule")
    ap.add_argument("--json", metavar="FILE", help="write the summary and the per-artifact findings to FILE")
    ap.add_argument("--check", action="store_true", help="fail if a number is worse than the paper's")
    ap.add_argument("--paper", metavar="FILE", default=os.path.join(REPO, "benchmarks", "paper-results.json"),
                    help="reference numbers for --check (default: benchmarks/paper-results.json)")
    ap.add_argument("--check-expected", action="store_true", help="fail if findings differ from expected-findings.json")
    ap.add_argument("--write-expected", action="store_true", help="rewrite expected-findings.json from this run")
    args = ap.parse_args()

    if not os.path.exists(args.apsis):
        sys.exit(f"analyzer not found at {args.apsis}; run `cargo build --release` or pass --apsis")
    cases = load_json(os.path.join(REPO, "benchmarks", "evaluation-set.json"))["cases"]
    runner = Runner(args)
    artifacts = [(c["framework"], n) for c in cases for n in (c["case"], c["fixed"])]
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        outcome = list(pool.map(lambda a: runner.run(*a), artifacts))
    results = {name: res for (_, name), res in zip(artifacts, outcome)}

    summary = summarize(cases, results)
    print_tables(summary)
    if args.by_detector:
        print_detectors(cases, results)
    times = [r["seconds"] for r in results.values() if "seconds" in r]
    if times:
        print(f"\n{len(artifacts)} artifacts in {time.time() - started:.0f} s with {args.jobs} job(s); "
              f"per artifact, front-end plus analysis: median {statistics.median(times):.2f} s, mean {statistics.mean(times):.2f} s")

    failed = False
    errors = {n: r["error"] for n, r in results.items() if "error" in r}
    if errors:
        failed = True
        print(f"\n{len(errors)} artifact(s) could not be analyzed (counted as not flagged):")
        for n, e in sorted(errors.items()):
            print(f"  {n}: {e}")
    if args.list:
        print("\nMissed benchmarks:", ", ".join(c["case"] for c in cases if not flagged(results[c["case"]])) or "none")
        print("Flagged fixed twins:", ", ".join(c["fixed"] for c in cases if flagged(results[c["fixed"]])) or "none")

    expected_path = os.path.join(REPO, "benchmarks", "expected-findings.json")
    measured = {n: [f"{d}/{rule}@{loc}" for d, rule, loc in r.get("findings", [])] for n, r in sorted(results.items())}
    if args.write_expected:
        if errors:
            sys.exit("not writing expected-findings.json: some artifacts could not be analyzed")
        with open(expected_path, "w", encoding="utf-8") as f:
            f.write("{\n" + ",\n".join(f" {json.dumps(n)}: {json.dumps(v)}" for n, v in measured.items()) + "\n}\n")
        print(f"\nwrote {os.path.relpath(expected_path, REPO)}")
    if args.check_expected:
        expected = load_json(expected_path)
        changed = [n for n in sorted(set(expected) | set(measured)) if expected.get(n) != measured.get(n)]
        if changed:
            failed = True
            print(f"\nFindings differ from expected-findings.json on {len(changed)} artifact(s):")
            for n in changed:
                print(f"  {n}\n    expected {expected.get(n)}\n    got      {measured.get(n)}")
        else:
            print("\nFindings match expected-findings.json on every artifact.")
    if args.check:
        lines, worse = compare_with_paper(summary, args.paper)
        print(f"\nCompared with the paper ({os.path.relpath(args.paper, REPO)}):")
        print("\n".join(lines) if lines else "  every number is identical")
        failed = failed or worse > 0
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "findings": measured, "errors": errors}, f, indent=1)
    if args.keep is None:
        import shutil

        shutil.rmtree(runner.workdir, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
