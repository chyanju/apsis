#!/usr/bin/env python3
"""Run an LLM judge over the artifacts of benchmarks/evaluation-set.json (each buggy workflow and its fixed twin).

A profile in .env, PROFILE_<name>=provider/model/effort, picks the model; results go to results/<run>/.

Usage: python3 run_llm.py --profile NAME [--only FILE] [--limit N] [--workers K] [--resume <run-dir>]
"""
import json, os, glob, re, sys, time, threading, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
EVALUATION_SET = os.path.join(ROOT, "benchmarks", "evaluation-set.json")
RESULTS = os.path.join(HERE, "results")
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SYSTEM = open(os.path.join(HERE, "system_prompt.txt"), encoding="utf-8").read()
FAMILIES = ["liveness_termination", "type_contracts", "routing_resolution",
            "state_concurrency", "composition", "capability_protocol"]


def load_dotenv():
    """Load KEY=VALUE lines from .env into the environment."""
    for p in (os.path.join(HERE, ".env"), os.path.join(ROOT, ".env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()


def resolve(profile):
    """(provider, model, effort) from PROFILE_<profile> in .env."""
    spec = os.environ.get(f"PROFILE_{profile}")
    if not spec:
        sys.exit(f"Profile '{profile}' not found in .env. Add a line: PROFILE_{profile}=provider/model/effort")
    parts = [x.strip() for x in spec.split("/")]
    if len(parts) != 3:
        sys.exit(f"PROFILE_{profile} must be provider/model/effort")
    return tuple(parts)


PROVIDER = MODEL = EFFORT = ""  # set by main() from --profile


def artifacts():
    """artifact -> is_buggy, for both artifacts of every benchmark."""
    c = {}
    for case in json.load(open(EVALUATION_SET))["cases"]:
        c[case["case"]] = True
        c[case["fixed"]] = False
    return c


def make_client():
    if PROVIDER == "anthropic":
        import anthropic
        return anthropic.Anthropic()
    if PROVIDER == "openai":
        import openai
        return openai.OpenAI()
    if PROVIDER == "deepseek":
        import openai  # DeepSeek is OpenAI-compatible
        return openai.OpenAI(base_url=DEEPSEEK_BASE_URL,
                             api_key=os.environ.get("DEEPSEEK_API_KEY", ""))
    sys.exit("No provider. Use --profile NAME (PROFILE_NAME=provider/model/effort in .env), "
             "or set a key in .env.")


def ask(client, user):
    """One call at the profile's effort; returns (parsed JSON or None, {'in','out'} token counts)."""
    usage = {"in": 0, "out": 0}
    if PROVIDER == "anthropic":
        # max_tokens covers thinking and output; streamed, as a 32k-token call can exceed the SDK's non-streaming limit
        txt = ""
        with client.messages.stream(
            model=MODEL, max_tokens=32000,
            thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
            system=SYSTEM, messages=[{"role": "user", "content": user}]) as stream:
            for delta in stream.text_stream:
                txt += delta
            u = stream.get_final_message().usage
        usage = {"in": u.input_tokens, "out": u.output_tokens}  # output includes thinking tokens
    elif PROVIDER == "openai":  # reasoning model: depth via reasoning_effort
        msg = client.chat.completions.create(
            model=MODEL, reasoning_effort=EFFORT, max_completion_tokens=32000,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
        txt = msg.choices[0].message.content
        if msg.usage:
            usage = {"in": msg.usage.prompt_tokens, "out": msg.usage.completion_tokens}
    else:  # deepseek thinking mode: the CoT counts toward max_tokens and is not kept
        txt = ""
        stream = client.chat.completions.create(
            model=MODEL, max_tokens=64000, reasoning_effort=EFFORT,
            extra_body={"thinking": {"type": "enabled"}},
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            stream=True, stream_options={"include_usage": True})
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = {"in": chunk.usage.prompt_tokens, "out": chunk.usage.completion_tokens}
            if chunk.choices and getattr(chunk.choices[0].delta, "content", None):
                txt += chunk.choices[0].delta.content
    return extract_json(txt), usage


def extract_json(txt):
    """The last balanced top-level {...} of a reply that parses as JSON (replies may wrap it in prose or fences)."""
    if not txt:
        return None
    best, depth, start = None, 0, -1
    for i, ch in enumerate(txt):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    best = json.loads(txt[start:i + 1])
                except json.JSONDecodeError:
                    pass
                start = -1
    return best


def process_case(client, base, is_buggy):
    pf = os.path.join(HERE, "prompts", base, "user.txt")
    if not os.path.exists(pf):
        return None
    t0 = time.time()
    try:
        out, usage = ask(client, open(pf, encoding="utf-8").read())
    except Exception as e:
        return {"base": base, "is_buggy": is_buggy, "error": f"{type(e).__name__}: {str(e)[:90]}"}
    dt = round(time.time() - t0, 2)
    if out is None:
        return {"base": base, "is_buggy": is_buggy, "error": "unparseable-output",
                "seconds": dt, "tokens": usage}
    fams = sorted(f for f in FAMILIES if isinstance(out.get(f), dict) and out[f].get("has_bug"))
    return {"base": base, "is_buggy": is_buggy, "flagged": bool(fams),
            "flagged_families": fams, "seconds": dt, "tokens": usage, "output": out}


def metrics(tp, fp, tn, fn):
    P = tp / (tp + fp) if tp + fp else 0.0
    R = tp / (tp + fn) if tp + fn else 0.0
    FPR = fp / (fp + tn) if fp + tn else 0.0
    F1 = 2 * P * R / (P + R) if P + R else 0.0
    return P, R, F1, FPR


def run_dir():
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9.-]", "-", f"{MODEL}_{EFFORT}")
    return os.path.join(RESULTS, f"{PROVIDER}_{safe}_{ts}")


def main(limit=None, workers=1, resume_dir=None, profile=None, only=None):
    global PROVIDER, MODEL, EFFORT
    PROVIDER, MODEL, EFFORT = resolve(profile)
    if not PROVIDER or not os.environ.get(KEY_ENV.get(PROVIDER, "")):
        sys.exit(f"No key for provider '{PROVIDER}'. Set {KEY_ENV.get(PROVIDER, '?')} in .env.")
    client = make_client()
    rundir = resume_dir if resume_dir else run_dir()
    os.makedirs(rundir, exist_ok=True)
    rpath = os.path.join(rundir, "records.json")
    logf = open(os.path.join(rundir, "run.log"), "a" if resume_dir else "w", encoding="utf-8")
    lock = threading.Lock()

    def log(m):
        with lock:
            print(m)
            logf.write(m + "\n")
            logf.flush()

    items = sorted(artifacts().items())
    if only:
        wanted = {line.strip() for line in open(only, encoding="utf-8") if line.strip() and not line.startswith("#")}
        unknown = wanted - {b for b, _ in items}
        if unknown:
            sys.exit(f"--only names artifacts not in the benchmark suite: {sorted(unknown)}")
        items = [(b, ib) for b, ib in items if b in wanted]
    if limit:
        step = max(1, len(items) // limit)
        items = items[::step][:limit]
    log(f"provider={PROVIDER}  model={MODEL}  effort={EFFORT}  artifacts={len(items)}  "
        f"workers={workers}  dir={os.path.basename(rundir)}")

    def handle(rec):
        if not rec:
            return
        if "error" in rec:
            log(f"  api-err {rec['base']}: {rec['error']}")
        else:
            log(f"  {rec['base']:26} buggy={int(rec['is_buggy'])} flagged={int(rec['flagged'])} "
                f"{rec['flagged_families']}  {rec['seconds']:5.1f}s")

    def record(rec):
        if not rec:
            return
        recs.append(rec)
        json.dump(recs, open(rpath, "w"), indent=2)  # flush after every artifact so --resume works mid-run
        handle(rec)

    recs = []
    if resume_dir and os.path.exists(rpath):
        recs = [r for r in json.load(open(rpath)) if "error" not in r]
        done = {r["base"] for r in recs}
        items = [(b, ib) for b, ib in items if b not in done]
        log(f"resume: {len(done)} valid kept, {len(items)} to (re)run")
    wall0 = time.time()
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(process_case, client, b, ib) for b, ib in items]
            for fut in as_completed(futs):
                record(fut.result())
    else:
        for b, ib in items:
            record(process_case(client, b, ib))
    wall = time.time() - wall0

    valid = [r for r in recs if "error" not in r]
    err = len(recs) - len(valid)
    tp = fp = tn = fn = 0
    fam_hit = fam_tot = pin_hit = pin_tot = 0
    for r in valid:
        fl = r["flagged"]
        if r["is_buggy"]:
            tp += fl; fn += (not fl)
            gtp = os.path.join(HERE, "ground_truth", r["base"] + ".json")
            if fl and os.path.exists(gtp):
                gt = json.load(open(gtp))
                fam_tot += 1
                if set(gt["families"]) & set(r["flagged_families"]):
                    fam_hit += 1
                if gt["location_ids"]:
                    pin_tot += 1
                    locs = " ".join(r["output"][f].get("location", "") for f in r["flagged_families"])
                    if any(g in locs for g in gt["location_ids"]):
                        pin_hit += 1
        else:
            fp += fl; tn += (not fl)
    P, R, F1, FPR = metrics(tp, fp, tn, fn)
    n = len(valid)
    log(f"\nLLM baseline ({PROVIDER}/{MODEL}/{EFFORT}): TP={tp} FP={fp} TN={tn} FN={fn} | "
        f"P={P:.2f} R={R:.2f} F1={F1:.2f} FPR={FPR:.2f}  (errors {err})")
    log(f"family-match (over flagged buggy): {fam_hit}/{fam_tot}" + (f" = {fam_hit/fam_tot:.2f}" if fam_tot else ""))
    log(f"pinpoint (over flagged buggy w/ gt-location): {pin_hit}/{pin_tot}" + (f" = {pin_hit/pin_tot:.2f}" if pin_tot else ""))
    if n:
        mean_call = sum(r["seconds"] for r in valid) / n
        log(f"timing: wall {wall:.0f}s for {n} artifacts at {workers} workers (mean {mean_call:.1f}s/call)")
    toks = [r["tokens"] for r in recs if "tokens" in r]
    if toks:
        tin = sum(t["in"] for t in toks); tout = sum(t["out"] for t in toks)
        log(f"tokens over {len(toks)} calls: input={tin} output={tout}")
    json.dump(recs, open(rpath, "w"), indent=2)
    log(f"results -> {rpath}")
    logf.close()


if __name__ == "__main__":
    def arg(flag, default=None):
        return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default
    if "-h" in sys.argv or "--help" in sys.argv or "--profile" not in sys.argv:
        print(__doc__.strip().splitlines()[-1])
        sys.exit(0 if ("-h" in sys.argv or "--help" in sys.argv) else 2)
    main(limit=int(arg("--limit", 0)) or None,
         workers=int(arg("--workers", 1)),
         resume_dir=arg("--resume"),
         profile=arg("--profile"),
         only=arg("--only"))
