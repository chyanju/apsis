# Derived from TradingAgents (github.com/TauricResearch/TradingAgents, Apache-2.0) and modified; license text in LICENSE.
"""The checkpointed runs of `TradingAgentsGraph.propagate` after the fix: the thread id also carries the run's
signature, the choices that shape the graph. The workflow is the one of bugs/05-tradingagents-1088."""

import atexit
import hashlib
import importlib.util
import shutil
import sqlite3
import tempfile
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def _workflow():
    spec = importlib.util.spec_from_file_location(
        "tradingagents_workflow", Path(__file__).resolve().parents[2] / "05-tradingagents-1088" / "graph.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


workflow = _workflow()


# tradingagents/graph/checkpointer.py


def _db_path(data_dir, ticker: str) -> Path:
    """Return the SQLite checkpoint DB path for a ticker."""
    p = Path(data_dir) / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{ticker.upper()}.db"


def thread_id(ticker: str, date: str, signature: str = "") -> str:
    """Deterministic thread ID for a ticker+date pair.

    ``signature`` folds in graph-shape-affecting run choices so a resume under a
    different graph can't reuse this checkpoint (#1089); omitting it keeps the
    legacy ID.
    """
    base = f"{ticker.upper()}:{date}"
    if signature:
        base = f"{base}:{signature}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def get_checkpointer(data_dir, ticker: str) -> SqliteSaver:
    """A SqliteSaver backed by a per-ticker DB, open for the run."""
    conn = sqlite3.connect(str(_db_path(data_dir, ticker)), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


# tradingagents/graph/trading_graph.py: TradingAgentsGraph._run_signature, propagate and _run_graph


def _run_signature(selected_analysts, config: dict, asset_type: str) -> str:
    """Graph-shape inputs that must invalidate a checkpoint if changed."""
    return "|".join([
        "analysts=" + ",".join(selected_analysts),
        f"debate={config['max_debate_rounds']}",
        f"risk={config['max_risk_discuss_rounds']}",
        f"asset={asset_type}",
    ])


def propagate(selected_analysts, company_name: str, trade_date: str, data_dir, asset_type: str = "stock"):
    """The graph a run compiles with the ticker's saver, and the config it is invoked with."""
    graph_setup = workflow.GraphSetup(None, None, workflow.tool_nodes, workflow.ConditionalLogic())
    graph = graph_setup.setup_graph(selected_analysts).compile(checkpointer=get_checkpointer(data_dir, company_name))
    signature = _run_signature(selected_analysts, {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}, asset_type)
    config = {"configurable": {"thread_id": thread_id(company_name, str(trade_date), signature)}}
    return graph, config


data_dir = tempfile.mkdtemp(prefix="tradingagents-")
atexit.register(shutil.rmtree, data_dir, ignore_errors=True)

runs = [propagate(["market"], "NVDA", "2026-06-01", data_dir), propagate(["news"], "NVDA", "2026-06-01", data_dir)]
