# CodeQL

The CodeQL and CodeQL Extended rows of the paper's Table 5. The queries in `queries/` rebuild a workflow's graph from the literal arguments of the calls that wire it, which only Haystack and LangGraph programs use, and report cycles without an exit, references to undeclared nodes, and instances shared between nodes. CodeQL Extended adds [mixedpy](../mixedpy/) for the other four frameworks.

Score the runs of the paper (`records.json`):

```
python3 baselines/codeql/score.py
```

Run CodeQL again (`setup.sh` downloads the CodeQL 2.25.6 bundle for Linux x86-64; set `CODEQL_PLATFORM=osx64` on macOS):

```
baselines/codeql/setup.sh
python3 baselines/codeql/run_codeql.py --jobs 4
python3 baselines/mixedpy/run_mixedpy.py
python3 baselines/codeql/score.py
```

The last two lines of `score.py`:

```
CodeQL           135 benchmarks: TP  10  FP   4  |  P 0.71  R 0.07  F1 0.13  FPR 0.03
CodeQL Extended  135 benchmarks: TP  23  FP   8  |  P 0.74  R 0.17  F1 0.28  FPR 0.06
```
