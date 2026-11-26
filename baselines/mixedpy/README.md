# mixedpy

The second half of the CodeQL Extended row of the paper's Table 5: a small static analyzer for Langflow, Flowise, AutoGen and the Python SDK of Agent Framework, the frameworks [CodeQL](../codeql/) does not cover. A front-end per framework (`fe_*.py`) lifts a workflow into one graph (`graph.py`), on which five structural checks run (`detectors.py`). It needs no framework installed.

```
python3 baselines/mixedpy/run_mixedpy.py   # writes baselines/mixedpy/records.json
python3 baselines/codeql/score.py          # the CodeQL and CodeQL Extended rows
```
