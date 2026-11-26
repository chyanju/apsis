"""The framework-native validator baseline: does a framework's own construction-time checking reject the
workflows of the benchmark suite?

usage: python3 baselines/native-validator/run.py [--envs DIR] [--dotnet-frontend PATH] [--jobs N] [--json FILE]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import types
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.dont_write_bytecode = True
import evaluate  # noqa: E402

CODE_FIRST = {"haystack", "langgraph", "autogen", "agent-framework"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--envs", default=os.path.join(REPO, ".envs"), help="directory holding the environments (default: .envs)")
    ap.add_argument("--dotnet-frontend", metavar="PATH", help="the built .NET front-end (default: <envs>/dotnet/frontend)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--json", metavar="FILE", help="write the verdict on every artifact to FILE")
    args = ap.parse_args()

    work = tempfile.mkdtemp(prefix="native-validator-")
    runner = evaluate.Runner(types.SimpleNamespace(tree=REPO, apsis=os.devnull, envs=args.envs, keep=work,
                                                   dotnet_frontend=args.dotnet_frontend))
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") or k.startswith(("DOTNET_", "NUGET_"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def check(framework, name):
        case_dir = os.path.join(REPO, "benchmarks", framework, name)
        meta = evaluate.load_json(os.path.join(case_dir, "meta.json"))
        if framework not in CODE_FIRST:
            return {"ok": True, "type": "exported flow: no standalone checker"}
        source = os.path.join(case_dir, meta["entry"])
        cwd = tempfile.mkdtemp(dir=work)
        if ".csproj:" in meta["entry"]:
            launcher = ["dotnet"] if runner.dotnet_frontend.endswith(".dll") else []
            build = os.path.join(args.envs, "dotnet", "build", name)
            cmd = launcher + [runner.dotnet_frontend, source, "-o", os.path.join(cwd, "ir.json"), "--artifacts", build]
            p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
            if p.returncode == 0:
                return {"ok": True, "type": "C# project compiled; the entry member built the workflow"}
            return {"ok": False, "stage": "dotnet", "error": (p.stderr.strip().splitlines() or ["?"])[-1][:400]}
        python = runner.interpreter(framework, name, case_dir)
        p = subprocess.run([python, "-B", os.path.join(HERE, "construct.py"), source], cwd=cwd, env=env,
                           capture_output=True, text=True, timeout=300)
        try:
            return json.loads((p.stdout.strip().splitlines() or [""])[-1])
        except ValueError:
            return {"ok": False, "stage": "driver", "error": (p.stderr.strip().splitlines() or ["no output"])[-1][:400]}

    cases = evaluate.load_json(os.path.join(REPO, "benchmarks", "evaluation-set.json"))["cases"]
    jobs = [(c["framework"], n, role) for c in cases for n, role in ((c["case"], "buggy"), (c["fixed"], "fixed"))]
    with ThreadPoolExecutor(args.jobs) as pool:
        verdicts = list(pool.map(lambda j: check(j[0], j[1]), jobs))
    out = {}
    for (framework, name, role), v in zip(jobs, verdicts):
        out[name] = dict(v, framework=framework, role=role)

    print(f"{'framework':16s} benchmarks  buggy rejected  fixed rejected")
    for fw in sorted({c["framework"] for c in cases}):
        n = sum(1 for c in cases if c["framework"] == fw)
        rb = sum(1 for v in out.values() if v["framework"] == fw and v["role"] == "buggy" and not v["ok"])
        rf = sum(1 for v in out.values() if v["framework"] == fw and v["role"] == "fixed" and not v["ok"])
        print(f"{fw:16s} {n:10d}  {rb:14d}  {rf:14d}")
    tp = sum(1 for v in out.values() if v["role"] == "buggy" and not v["ok"])
    fp = sum(1 for v in out.values() if v["role"] == "fixed" and not v["ok"])
    n = len(cases)
    p = f"{tp / (tp + fp):.2f}" if tp + fp else "---"
    f1 = f"{2 * tp / (2 * tp + fp + (n - tp)):.2f}" if tp else "---"
    print(f"\n{n} benchmarks: P {p}, R {tp / n:.2f}, F1 {f1}, FPR {fp / n:.2f}")
    for name, v in sorted(out.items()):
        if not v["ok"]:
            print(f"  rejected {name} ({v['role']}): {v['stage']}: {v['error']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
