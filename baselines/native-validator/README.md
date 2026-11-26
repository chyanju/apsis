# Framework-native validator

The Framework-Native Validator row of the paper's Table 5. Each workflow is built with the checks its framework runs at construction time (Haystack's typed `connect`, LangGraph's `compile()`, the AutoGen and Agent Framework builders, the C# compiler for the .NET SDK); Langflow and Flowise have no standalone checker, so their flows pass. A rejected buggy workflow is a detection and a rejected fixed twin a false positive.

```
python3 scripts/setup_envs.py              # once: the framework environments of the evaluation
python3 baselines/native-validator/run.py
```

The last line of the output:

```
135 benchmarks: P ---, R 0.00, F1 ---, FPR 0.00
```
