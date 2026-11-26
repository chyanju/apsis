import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict


class ExecutionResult(BaseModel):
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


class AgentState(TypedDict):
    user_query: str
    db_info: Optional[Dict]
    table_relationship: Optional[List[Dict[str, Any]]]
    generated_sql: Optional[str]
    execution_result: Optional[ExecutionResult]
    report_summary: Optional[str]
    attempts: int
    correct_attempts: int
    chart_type: Optional[str]
    chart_config: Optional[Dict[str, Any]]
    render_data: Optional[Dict[str, Any]]
    datasource_id: Optional[int]
    user_id: Optional[int]
    filtered_sql: Optional[str]
    recommended_questions: Optional[List[str]]
    used_tables: Optional[List[str]]
    bm25_tokens: Optional[List[str]]
    error_message: Optional[str]


_recommender_executor: Optional[ThreadPoolExecutor] = None
_recommender_lock = threading.Lock()
_recommender_futures: dict = {}


def get_recommender_executor() -> ThreadPoolExecutor:
    global _recommender_executor
    if _recommender_executor is None:
        with _recommender_lock:
            if _recommender_executor is None:
                _recommender_executor = ThreadPoolExecutor(max_workers=2)
    return _recommender_executor


def question_recommender(state: AgentState) -> AgentState:
    state["recommended_questions"] = []
    return state


def start_early_recommender(state: AgentState) -> AgentState:
    if not state.get("datasource_id") or not state.get("db_info") or not state.get("user_query"):
        return state
    task_id = f"{state.get('datasource_id')}_{id(state)}"

    def run_recommender():
        questions = question_recommender(dict(state)).get("recommended_questions", [])
        with _recommender_lock:
            if task_id in _recommender_futures:
                _recommender_futures[task_id]["completed"] = True
                _recommender_futures[task_id]["result"] = questions

    future = get_recommender_executor().submit(run_recommender)
    with _recommender_lock:
        _recommender_futures[task_id] = {"future": future, "result": [], "completed": False, "error": None}
    state["_early_recommender_task_id"] = task_id
    return state


def wait_for_early_recommender(task_id: str, timeout: int = 5) -> Optional[List[str]]:
    with _recommender_lock:
        if task_id not in _recommender_futures:
            return None
        task_info = _recommender_futures[task_id].copy()
    task_info["future"].result(timeout=timeout)
    with _recommender_lock:
        result = _recommender_futures.pop(task_id, task_info).get("result", [])
    return result or None


def wait_and_merge_early_recommender(state: AgentState) -> AgentState:
    task_id = state.get("_early_recommender_task_id")
    questions = wait_for_early_recommender(task_id, timeout=5) if task_id else None
    state["recommended_questions"] = questions or question_recommender(dict(state)).get("recommended_questions", [])
    return state


def datasource_selector(state: AgentState) -> AgentState:
    return state


def should_continue_after_datasource_selector(state: AgentState) -> str:
    if not state.get("datasource_id"):
        return "error_handler"
    return "schema_inspector"


def handle_datasource_error(state: AgentState) -> AgentState:
    if not state.get("error_message"):
        state["error_message"] = "no data source"
    return state


class DatabaseService:
    def __init__(self, datasource_id: int = None):
        self.datasource_id = datasource_id

    def get_table_schema(self, state: AgentState) -> AgentState:
        state["db_info"] = {}
        return state

    def execute_sql(self, state: AgentState) -> AgentState:
        state["execution_result"] = ExecutionResult(success=True, data=[])
        return state


def sql_generate(state: AgentState) -> AgentState:
    state["generated_sql"] = ""
    return state


def permission_filter_injector(state: AgentState) -> AgentState:
    state["filtered_sql"] = state.get("generated_sql")
    return state


def parallel_collect_after_sql_executor(state: AgentState) -> AgentState:
    state["report_summary"] = ""
    state["chart_config"] = {}
    if not state.get("_early_recommender_task_id"):
        state["recommended_questions"] = question_recommender(dict(state)).get("recommended_questions", [])
    return state


async def unified_collect(state: AgentState) -> AgentState:
    state["render_data"] = {}
    if state.get("_early_recommender_task_id"):
        state = wait_and_merge_early_recommender(state)
    return state


def create_graph(datasource_id: int = None):
    graph = StateGraph(AgentState)
    db_service = DatabaseService(datasource_id)

    graph.add_node("datasource_selector", datasource_selector)
    graph.add_node("error_handler", handle_datasource_error)
    graph.add_node("schema_inspector", db_service.get_table_schema)
    graph.add_node("early_recommender", start_early_recommender)
    graph.add_node("sql_generator", sql_generate)
    graph.add_node("permission_filter", permission_filter_injector)
    graph.add_node("sql_executor", db_service.execute_sql)
    graph.add_node("parallel_collector", parallel_collect_after_sql_executor)
    graph.add_node("unified_collector", unified_collect)

    graph.set_entry_point("datasource_selector")
    graph.add_conditional_edges(
        "datasource_selector",
        should_continue_after_datasource_selector,
        {
            "error_handler": "error_handler",
            "schema_inspector": "schema_inspector",
        },
    )
    graph.add_edge("error_handler", END)
    graph.add_edge("schema_inspector", "early_recommender")
    graph.add_edge("early_recommender", "sql_generator")
    graph.add_edge("sql_generator", "permission_filter")
    graph.add_edge("permission_filter", "sql_executor")
    graph.add_edge("sql_executor", "parallel_collector")
    graph.add_edge("parallel_collector", "unified_collector")
    graph.add_edge("unified_collector", END)

    return graph.compile()


graph = create_graph()
