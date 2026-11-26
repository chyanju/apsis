#!/usr/bin/env python3
"""Write the LLM baseline's prompts/ and ground_truth/ from the benchmark suite, without any API call."""
import ast, json, os, glob, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clean_source import clean_python

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
EVALUATION_SET = os.path.join(ROOT, "benchmarks", "evaluation-set.json")

DETECTOR_FAMILY = {
    "readiness-liveness": "liveness_termination", "cycle-termination": "liveness_termination",
    "type-contract": "type_contracts",
    "target-resolution": "routing_resolution", "router-branch-gating": "routing_resolution",
    "dangling-output": "routing_resolution",
    "channel-write-merge": "state_concurrency", "shared-instance-aliasing": "state_concurrency",
    "read-after-write": "state_concurrency",
    "subflow-port-binding": "composition",
    "binding-capability": "capability_protocol", "interrupt-ordering": "capability_protocol",
}

FRAMEWORK_LABEL = {
    "langgraph": "LangGraph", "haystack": "Haystack", "autogen": "AutoGen",
    "agent-framework": "Microsoft Agent Framework", "langflow": "Langflow", "flowise": "Flowise",
}

ID_RE = re.compile(r"^[A-Za-z_][\w.\-/]{0,48}$")


def entry_of(case_dir):
    m = json.load(open(os.path.join(case_dir, "meta.json")))
    return os.path.join(case_dir, m.get("entry", "").split(":")[0]), m


def sources(entry):
    """The entry file, or a C# project's .cs files except the driver Run.cs."""
    if entry.endswith(".csproj"):
        d = os.path.dirname(entry)
        return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".cs") and f != "Run.cs")
    return [entry]


def cs_identifiers(path):
    from clean_source import clean_csharp
    text = clean_csharp(open(path, encoding="utf-8").read())
    return {v for v in re.findall(r'"((?:[^"\\\n]|\\.)*)"', text) if ID_RE.match(v)}


def py_identifiers(path):
    try:
        t = ast.parse(clean_python(open(path, encoding="utf-8").read()))
    except SyntaxError:
        return set()
    return {n.value for n in ast.walk(t)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and ID_RE.match(n.value)}


def json_elements(path):
    d = json.load(open(path, encoding="utf-8"))
    data = d.get("data", d)
    nodes = {n.get("id") for n in data.get("nodes", []) if isinstance(n, dict)}
    edges = {f"{e.get('source')}->{e.get('target')}" for e in data.get("edges", []) if isinstance(e, dict)}
    return {x for x in (nodes | edges) if x}


def elements(path):
    if not os.path.exists(path):
        return set()
    if path.endswith(".csproj"):
        return set().union(*(cs_identifiers(f) for f in sources(path)))
    return json_elements(path) if path.endswith(".json") else py_identifiers(path)


def artifacts():
    """artifact -> is_buggy, for both artifacts of every benchmark."""
    c = {}
    for case in json.load(open(EVALUATION_SET))["cases"]:
        c[case["case"]] = True
        c[case["fixed"]] = False
    return c


def main():
    from clean_source import clean_file
    corp = artifacts()
    os.makedirs(os.path.join(HERE, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "ground_truth"), exist_ok=True)
    n_prompt = n_gt = n_err = 0
    for base, is_buggy in sorted(corp.items()):
        fw = re.sub(r"-\d.*", "", base)
        d = os.path.join(ROOT, "benchmarks", fw, base)
        if not os.path.isdir(d):
            continue
        ep, m = entry_of(d)
        if not os.path.exists(ep):
            continue
        try:
            cleaned = "\n".join(clean_file(f) for f in sources(ep))
        except Exception as e:
            print(f"  clean-err {base}: {type(e).__name__}")
            n_err += 1
            continue
        od = os.path.join(HERE, "prompts", base)
        os.makedirs(od, exist_ok=True)
        kind = ("exported flow.json" if ep.endswith(".json")
                else "C# definition" if ep.endswith(".csproj") else "Python definition")
        header = (f"# This is a {FRAMEWORK_LABEL.get(fw, fw)} agent workflow ({kind}).\n"
                  f"# Analyze the workflow below for bugs, working only from this source.\n\n")
        open(os.path.join(od, "user.txt"), "w", encoding="utf-8").write(header + cleaned)
        n_prompt += 1
        if is_buggy:
            fixed = [os.path.join(ROOT, "benchmarks", fw, t) for t, b in corp.items() if not b and t.rsplit("-fixed", 1)[0] == base]
            fel = set()
            for f in fixed:
                fel |= elements(entry_of(f)[0])
            loc = sorted(elements(ep) ^ fel)  # the identifiers the fix changed
            fams = sorted({DETECTOR_FAMILY[x] for x in m.get("expected_detectors", []) if x in DETECTOR_FAMILY})
            json.dump({"base": base, "framework": fw, "families": fams, "location_ids": loc},
                      open(os.path.join(HERE, "ground_truth", base + ".json"), "w"), indent=2)
            n_gt += 1
    print(f"prompts written: {n_prompt}  ground_truth: {n_gt}  clean-errors: {n_err}")


if __name__ == "__main__":
    main()
