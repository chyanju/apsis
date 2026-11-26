# Derived from TradingAgents (github.com/TauricResearch/TradingAgents, Apache-2.0) and modified; license text in LICENSE.
"""The checkpointed runs of `TradingAgentsGraph.propagate`: the graph of an analyst selection, compiled with the
SQLite saver of the ticker and invoked with the thread id of the ticker and date. The workflow is the one of
bugs/05-tradingagents-1088, at the same commit."""

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
        "tradingagents_workflow", Path(__file__).resolve().parents[1] / "05-tradingagents-1088" / "graph.py"
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


def thread_id(ticker: str, date: str) -> str:
    """Deterministic thread ID for a ticker+date pair."""
    return hashlib.sha256(f"{ticker.upper()}:{date}".encode()).hexdigest()[:16]


def get_checkpointer(data_dir, ticker: str) -> SqliteSaver:
    """A SqliteSaver backed by a per-ticker DB, open for the run."""
    conn = sqlite3.connect(str(_db_path(data_dir, ticker)), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


# tradingagents/graph/trading_graph.py: TradingAgentsGraph.propagate and _run_graph


def propagate(selected_analysts, company_name: str, trade_date: str, data_dir):
    """The graph a run compiles with the ticker's saver, and the config it is invoked with."""
    graph_setup = workflow.GraphSetup(None, None, workflow.tool_nodes, workflow.ConditionalLogic())
    graph = graph_setup.setup_graph(selected_analysts).compile(checkpointer=get_checkpointer(data_dir, company_name))
    config = {"configurable": {"thread_id": thread_id(company_name, str(trade_date))}}
    return graph, config


data_dir = tempfile.mkdtemp(prefix="tradingagents-")
atexit.register(shutil.rmtree, data_dir, ignore_errors=True)

# a run with the market analyst stopped after its first steps; the same ticker and date run again with the news analyst
runs = [propagate(["market"], "NVDA", "2026-06-01", data_dir), propagate(["news"], "NVDA", "2026-06-01", data_dir)]
