import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
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
    _early_recommender_future: Optional[Any]
    error_msg: Optional[str]
    is_retryable_error: bool
    last_error_type: Optional[str]


MAX_SQL_ATTEMPTS = 3


def sql_execution_route(success: bool, retryable: bool, attempts: int) -> str:
    if success:
        return "success"
    if retryable and attempts < MAX_SQL_ATTEMPTS:
        return "retry"
    return "error"


_recommender_executor: Optional[ThreadPoolExecutor] = None
_recommender_lock = threading.Lock()


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
    state_copy = dict(state)

    def run_recommender() -> List[str]:
        return question_recommender(state_copy).get("recommended_questions", [])

    state["_early_recommender_future"] = get_recommender_executor().submit(run_recommender)
    return state


def wait_for_early_recommender(future: Optional[Future], timeout: int = 5) -> Optional[List[str]]:
    if future is None:
        return None
    try:
        result = future.result(timeout=timeout)
        return result if result else None
    except FutureTimeoutError:
        future.cancel()
    return None


def wait_and_merge_early_recommender(state: AgentState) -> AgentState:
    future = state.get("_early_recommender_future")
    questions = wait_for_early_recommender(future, timeout=5) if future else None
    state["recommended_questions"] = questions or question_recommender(dict(state)).get("recommended_questions", [])
    return state


def datasource_selector(state: AgentState) -> AgentState:
    return state


def should_continue_after_datasource_selector(state: AgentState) -> str:
    if not state.get("datasource_id"):
        return "error_handler"
    return "schema_inspector"


def should_retry_sql(state: AgentState) -> str:
    result = state.get("execution_result")
    return sql_execution_route(
        success=bool(result and result.success),
        retryable=state.get("is_retryable_error", False),
        attempts=state.get("attempts", 0),
    )


def handle_sql_error(state: AgentState) -> AgentState:
    result = state.get("execution_result")
    state["error_message"] = result.error if result and result.error else "SQL execution failed"
    future = state.get("_early_recommender_future")
    state["_early_recommender_future"] = None
    if future is not None and not future.done():
        future.cancel()
    return state


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
    if not state.get("_early_recommender_future"):
        state["recommended_questions"] = question_recommender(dict(state)).get("recommended_questions", [])
    return state


async def unified_collect(state: AgentState) -> AgentState:
    state["render_data"] = {}
    if state.get("_early_recommender_future"):
        state = wait_and_merge_early_recommender(state)
    return state


def create_graph(datasource_id: int = None):
    graph = StateGraph(AgentState)
    db_service = DatabaseService(datasource_id)

    graph.add_node("datasource_selector", datasource_selector)
    graph.add_node("error_handler", handle_datasource_error)
    graph.add_node("sql_error_handler", handle_sql_error)
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
    graph.add_edge("sql_error_handler", END)
    graph.add_edge("schema_inspector", "early_recommender")
    graph.add_edge("early_recommender", "sql_generator")
    graph.add_edge("sql_generator", "permission_filter")
    graph.add_edge("permission_filter", "sql_executor")
    graph.add_conditional_edges(
        "sql_executor",
        should_retry_sql,
        {
            "success": "parallel_collector",
            "retry": "sql_generator",
            "error": "sql_error_handler",
        },
    )
    graph.add_edge("parallel_collector", "unified_collector")
    graph.add_edge("unified_collector", END)

    return graph.compile()


graph = create_graph()
