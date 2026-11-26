# LLM judges

The GPT-5.5, Opus-4.8 and DeepSeek-V4 rows of the paper's Table 5, with their Strict rows. Each call gives a model `system_prompt.txt` and one workflow, `prompts/<artifact>/user.txt` (its source without comments); the model answers for each of six bug categories whether the workflow has such a bug.

Score the runs of the paper (`runs/`):

```
python3 baselines/llm/score.py
```

```
judge                     P     R    F1   FPR
GPT-5.5                0.60  0.80  0.68  0.54
GPT-5.5 Strict         0.44  0.43  0.44  0.54
Opus-4.8               0.61  0.77  0.68  0.49
Opus-4.8 Strict        0.45  0.39  0.42  0.49
DeepSeek-V4            0.57  0.88  0.69  0.67
DeepSeek-V4 Strict     0.40  0.44  0.42  0.67
```

Run a model again (the paper's runs used openai 3.51.0 and anthropic 2.8.0; DeepSeek is called through the OpenAI client):

```
cp baselines/llm/.env.example baselines/llm/.env    # then fill in the API key
pip install openai anthropic
python3 baselines/llm/run_llm.py --profile gpt_xhigh --workers 6
python3 baselines/llm/score.py "GPT-5.5=baselines/llm/results/<run>/records.json"
```

`run_llm.py` writes each run to `baselines/llm/results/<run>/`, and `--resume <run-dir>` continues it.
