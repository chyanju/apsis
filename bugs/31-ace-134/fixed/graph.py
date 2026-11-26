# Derived from ACE (github.com/kayba-ai/agentic-context-engine, Apache-2.0) and modified; license text in LICENSE.
"""ACE's agentic SkillManager: a PydanticAI agent whose `recurse` tool runs child sessions, with the skill tools that
change the skillbook in their deps. Compaction, metering, prompts, insight sources and skill search are left out."""

from __future__ import annotations

import copy
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Optional, Sequence, Type, cast

from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models import Model as PydanticModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

# ace/core/skillbook.py


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UpdateOperation:
    """Single mutation to apply to the skillbook."""

    type: Literal["ADD", "UPDATE", "TAG", "REMOVE"]
    section: str
    issue: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    insight: Optional[str] = None
    skill_id: Optional[str] = None
    metadata: Dict[str, int] = field(default_factory=dict)
    reason: Optional[str] = None


@dataclass
class UpdateBatch:
    """Bundle of skill manager reasoning and operations."""

    reasoning: str
    operations: List[UpdateOperation] = field(default_factory=list)


@dataclass
class Skill:
    """Single skillbook entry."""

    id: str
    section: str
    keywords: list[str]
    issue: str
    insight: str | None = None
    active: bool = True
    helpful_count: int = 0
    harmful_count: int = 0
    neutral_count: int = 0
    updated_at: str = field(default_factory=_now_iso)


class Skillbook:
    """Structured context store as defined by ACE."""

    def __init__(self) -> None:
        self._skills: Dict[str, Skill] = {}
        self._sections: Dict[str, List[str]] = {}
        self._next_id = 0
        self._lock = threading.RLock()

    @property
    def lock(self) -> threading.RLock:
        """Reentrant lock guarding all mutations."""
        return self._lock

    def clone(self) -> "Skillbook":
        """In-memory deep copy that preserves computed embeddings."""

        with self._lock:
            clone = Skillbook()
            clone._skills = {
                skill_id: copy.deepcopy(skill)
                for skill_id, skill in self._skills.items()
            }
            clone._sections = {
                section: list(skill_ids)
                for section, skill_ids in self._sections.items()
            }
            clone._next_id = self._next_id
            return clone

    def add_skill(
        self,
        section: str,
        issue: str | None = None,
        *,
        keywords: Iterable[Any] | None = None,
        insight: str | None = None,
        skill_id: Optional[str] = None,
    ) -> Skill:
        with self._lock:
            skill_id = skill_id or self._generate_id(section)
            skill = Skill(id=skill_id, section=section, keywords=list(keywords or [section]), issue=issue or "", insight=insight)
            self._skills[skill_id] = skill
            self._sections.setdefault(section, []).append(skill_id)
            return skill

    def update_skill(
        self,
        skill_id: str,
        *,
        issue: str | None = None,
        keywords: Iterable[Any] | None = None,
        insight: str | None = None,
    ) -> Optional[Skill]:
        with self._lock:
            skill = self._skills.get(skill_id)
            if skill is None:
                return None
            if issue is not None:
                skill.issue = issue
            if keywords is not None:
                skill.keywords = list(keywords)
            if insight is not None:
                skill.insight = insight
            skill.updated_at = _now_iso()
            return skill

    def tag_skill(self, skill_id: str, delta: Literal[1, -1, 0]) -> Optional[Skill]:
        """Record an effectiveness observation for a skill."""
        with self._lock:
            skill = self._skills.get(skill_id)
            if skill is None:
                return None
            if delta == 1:
                skill.helpful_count += 1
            elif delta == -1:
                skill.harmful_count += 1
            else:
                skill.neutral_count += 1
            skill.updated_at = _now_iso()
            return skill

    def remove_skill(self, skill_id: str) -> None:
        with self._lock:
            skill = self._skills.get(skill_id)
            if skill is None:
                return
            skill.active = False
            skill.updated_at = _now_iso()

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        return self._skills.get(skill_id)

    def skills(self) -> List[Skill]:
        return [s for s in self._skills.values() if s.active]

    def apply_update(self, update: UpdateBatch) -> None:
        with self._lock:
            for operation in update.operations:
                self._apply_operation(operation)

    def _apply_operation(self, operation: UpdateOperation) -> None:
        op_type = operation.type.upper()
        if op_type == "ADD":
            self.add_skill(
                section=operation.section,
                issue=operation.issue or "",
                keywords=operation.keywords,
                insight=operation.insight,
                skill_id=operation.skill_id,
            )
        elif op_type == "UPDATE" and operation.skill_id is not None:
            self.update_skill(operation.skill_id, issue=operation.issue, keywords=operation.keywords or None, insight=operation.insight)
        elif op_type == "TAG" and operation.skill_id is not None:
            delta = int(operation.metadata.get("delta", 0))
            self.tag_skill(operation.skill_id, 1 if delta > 0 else -1 if delta < 0 else 0)
        elif op_type == "REMOVE" and operation.skill_id is not None:
            self.remove_skill(operation.skill_id)

    def _generate_id(self, section: str) -> str:
        self._next_id += 1
        return f"{section.split()[0].lower()}-{self._next_id:05d}"


# ace/core/sandbox.py, reduced to the namespace that `recurse` copies; code execution is left out


@dataclass
class ExecutionResult:
    stdout: str = ""
    stderr: str = ""
    exception: BaseException | None = None


class TraceSandbox:
    def __init__(self, trace: Any = None) -> None:
        self.namespace: Dict[str, Any] = {"trace": trace}

    def inject(self, name: str, value: Any) -> None:
        self.namespace[name] = value

    def execute(self, code: str, timeout: float | None = None) -> ExecutionResult:
        return ExecutionResult()


# ace/core/recursive_agent.py


def register_execute_code(agent: PydanticAgent[AgenticDeps, Any]) -> None:
    """Register the generic ``execute_code`` tool."""

    @agent.tool(retries=3)
    def execute_code(ctx: RunContext[AgenticDeps], code: str) -> str:
        """Execute Python code in the sandbox.

        Args:
            code: Python code to execute.

        Returns:
            Captured stdout/stderr from execution.
        """
        ctx.deps.iteration += 1
        if ctx.deps.sandbox is None:
            return "(no sandbox configured)"

        result = ctx.deps.sandbox.execute(code, timeout=ctx.deps.config.timeout)
        if result.exception:
            raise ModelRetry(f"Code error:\n{type(result.exception).__name__}: {result.exception}")
        output = "\n".join(p for p in (result.stdout, result.stderr and f"stderr: {result.stderr}") if p)
        return output[: ctx.deps.config.max_output_chars] or "(no output)"


def register_recurse(agent: PydanticAgent[AgenticDeps, Any]) -> None:
    """Register the generic ``recurse`` tool for depth-based decomposition.

    Expects ``deps.run_session_fn`` to be set (done by
    :meth:`RecursiveAgent.run`).
    """

    @agent.tool
    async def recurse(
        ctx: RunContext[AgenticDeps],
        prompt: str,
        context_code: str = "",
    ) -> str:
        """Spawn a child session to investigate a sub-problem in isolation.

        Use this to keep your context lean: the child works through
        bulky data in its own context window and returns only a text
        summary. The child inherits a copy of your sandbox variables
        and any helpers you've registered via `register_helper`. It
        does NOT see your conversation, so `prompt` must be self-contained.
        Calling `recurse` multiple times in a single assistant turn
        dispatches the children in parallel.

        Args:
            prompt: Self-contained instructions. Name the sandbox
                variables to inspect and say what to return.
            context_code: Optional Python run once in the child's
                sandbox before it starts (e.g. ``chunk = traces[5:10]``).

        Returns:
            Text summary of the child's structured output.
        """
        deps = ctx.deps
        if deps.run_session_fn is None:
            return "(recurse unavailable — no session runner configured)"

        if deps.sandbox is None:
            return "(recurse unavailable — no sandbox on deps)"

        sandbox = deps.sandbox

        # Create child sandbox inheriting parent's injected data
        child_sandbox = TraceSandbox(trace=None)
        for key, value in sandbox.namespace.items():
            if not key.startswith("_") and not callable(value):
                child_sandbox.inject(key, value)

        # Run optional context_code
        if context_code.strip():
            result = child_sandbox.execute(context_code, timeout=deps.config.timeout)
            if result.exception:
                raise ModelRetry(
                    f"context_code failed: {result.exception}\n"
                    "Fix the code and try again."
                )

        # Build child deps (same type as parent)
        child_deps = deps.for_child(sandbox=child_sandbox)

        try:
            output, _ = await deps.run_session_fn(
                deps=child_deps,
                prompt=prompt,
                depth=deps.depth + 1,
            )

            if hasattr(output, "model_dump"):
                d = output.model_dump(exclude={"raw"}, exclude_defaults=True)
                parts = [f"{k}: {v}" for k, v in d.items() if v]
                text = "\n".join(parts) if parts else "(empty output)"
            else:
                text = str(output) if output else "(empty output)"

            id_map = deps.commit_child(child_deps)

            if id_map:
                pattern = re.compile(
                    "|".join(
                        re.escape(child_id)
                        for child_id in sorted(id_map, key=len, reverse=True)
                    )
                )
                text = pattern.sub(lambda m: id_map[m.group(0)], text)
            return text

        except Exception as e:
            return f"(child session failed: {e})"


@dataclass
class AgenticConfig:
    """Base configuration for agentic steps with compaction and recursion."""

    max_tokens: int = 500_000
    max_requests: int = 50
    max_depth: int = 2
    child_budget_fraction: float = 0.5
    timeout: float = 60.0
    max_output_chars: int = 50_000

    def build_usage_limits(self, remaining_tokens: int | None = None) -> UsageLimits:
        return UsageLimits(total_tokens_limit=remaining_tokens or self.max_tokens, request_limit=self.max_requests)


@dataclass
class AgenticDeps:
    """Base dependencies for agentic steps.

    Subclass to add step-specific deps (trace data, etc.).
    """

    config: AgenticConfig
    sandbox: Any = None  # TraceSandbox or compatible
    depth: int = 0
    max_depth: int = 2
    iteration: int = 0
    run_session_fn: Callable[..., Awaitable[tuple[Any, Any]]] | None = None
    parent_usage_tokens: int = 0

    def for_child(self, *, sandbox: Any) -> "AgenticDeps":
        """Build dependency state for a child session."""
        return replace(
            self,
            sandbox=sandbox,
            depth=self.depth + 1,
            iteration=0,
            parent_usage_tokens=0,
        )

    def commit_child(self, child: "AgenticDeps") -> dict[str, str]:
        """Merge a successful child session's mutations back into this state; the child-local identifiers that
        were renamed while committing, mapped to the identifiers they now have."""
        return {}


class BudgetExhausted(Exception):
    """Raised when the agent's token or request budget is fully spent."""


async def run_agent(agent: PydanticAgent[AgenticDeps, Any], *, deps: AgenticDeps, prompt: str, usage_limits: UsageLimits) -> tuple[Any, dict]:
    """``run_agent_with_compaction`` without the compaction: one run of the agent."""
    result = await agent.run(prompt, deps=deps, usage_limits=usage_limits)
    return result.output, {"depth": deps.depth, "iterations": deps.iteration}


class RecursiveAgent:
    """A PydanticAI agent with recursion and budget management."""

    def __init__(
        self,
        model: str | PydanticModel,
        *,
        output_type: Type,
        system_prompt: str,
        config: AgenticConfig | None = None,
        tools: Sequence[Callable[..., None]] = (),
    ) -> None:
        self.config = config or AgenticConfig()
        self._model = model
        self._output_type = output_type
        self._system_prompt = system_prompt
        self._tools = list(tools)

        # Build root agent (depth=0)
        self._agent = self._create_agent(depth=0)

    def _create_agent(self, depth: int = 0) -> PydanticAgent[AgenticDeps, Any]:
        """Create a PydanticAI agent for the given recursion depth; children return free-form text."""
        output_type = self._output_type if depth == 0 else str

        agent: PydanticAgent[AgenticDeps, Any] = PydanticAgent(
            self._model,
            output_type=output_type,
            system_prompt=self._system_prompt,
            retries=3,
            defer_model_check=True,
        )

        # Default tools: execute_code + recurse (if not at max depth)
        register_execute_code(agent)
        if depth < self.config.max_depth:
            register_recurse(agent)

        # Additional caller-provided tools
        for registrar in self._tools:
            registrar(agent)

        return agent

    async def _run_child_session(self, *, deps: AgenticDeps, prompt: str, depth: int = 0) -> tuple[Any, AgenticDeps]:
        """Run a child session with its own agent and budget."""
        child_agent = self._create_agent(depth=depth)

        remaining = getattr(deps, "_remaining_tokens", None)
        try:
            output, metadata = await run_agent(
                child_agent,
                deps=deps,
                prompt=prompt,
                usage_limits=self.config.build_usage_limits(remaining_tokens=remaining),
            )
            return output, deps
        except BudgetExhausted:
            return None, deps


# ace/implementations/sm_tools.py


@dataclass
class SMDeps(AgenticDeps):
    """Dependencies injected into SkillManager tool calls via ``RunContext``."""

    skillbook: Optional[Skillbook] = None
    operations: list[UpdateOperation] = field(default_factory=list)
    current_source: Optional[Any] = None

    def for_child(self, *, sandbox: Any) -> "SMDeps":
        child = cast(SMDeps, super().for_child(sandbox=sandbox))

        if self.skillbook is not None:
            child.skillbook = self.skillbook.clone()

        child.operations = []
        return child

    def commit_child(self, child: AgenticDeps) -> dict[str, str]:
        """Atomically merge a successful child's skillbook mutations.

        Returns:
            Mapping of the child's temporary skill IDs (assigned inside
            its isolated copy) to the IDs they were committed under in
            the parent skillbook.
        """
        child = cast(SMDeps, child)

        if self.skillbook is None or child.skillbook is None:
            return {}

        with self.skillbook.lock:
            staged_skillbook = self.skillbook.clone()

            id_map: dict[str, str] = {}
            committed_operations: list[UpdateOperation] = []
            apply_operations: list[UpdateOperation] = []

            for operation in child.operations:
                skill_id = operation.skill_id

                if skill_id is not None:
                    skill_id = id_map.get(skill_id, skill_id)

                if operation.type == "ADD":
                    child_skill_id = operation.skill_id

                    skill = staged_skillbook.add_skill(
                        section=operation.section,
                        issue=operation.issue,
                        keywords=operation.keywords,
                        insight=operation.insight,
                    )

                    if child_skill_id is not None:
                        id_map[child_skill_id] = skill.id

                    committed_operation = replace(
                        operation,
                        skill_id=skill.id,
                    )
                    committed_operations.append(committed_operation)

                    apply_operations.append(replace(committed_operation, skill_id=None))
                    continue

                committed_operation = replace(
                    operation,
                    skill_id=skill_id,
                )

                staged_skillbook.apply_update(
                    UpdateBatch(
                        reasoning="",
                        operations=[committed_operation],
                    )
                )

                committed_operations.append(committed_operation)
                apply_operations.append(committed_operation)

            self.skillbook.apply_update(
                UpdateBatch(
                    reasoning="",
                    operations=apply_operations,
                )
            )
            self.operations.extend(committed_operations)

        return id_map


def _normalize_keywords(keywords: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        text = str(keyword).strip().lower().replace(" ", "_")
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def register_add_skill(agent: PydanticAgent[SMDeps, Any]) -> None:
    @agent.tool
    def add_skill(ctx: RunContext[SMDeps], section: str, issue: str, keywords: list[str], insight: str | None = None) -> dict[str, Any]:
        sb = ctx.deps.skillbook
        if sb is None:
            return {"error": "skillbook unavailable"}
        normalized_keywords = _normalize_keywords(keywords)
        skill = sb.add_skill(section=section, issue=issue, keywords=normalized_keywords, insight=insight)
        ctx.deps.operations.append(
            UpdateOperation(
                type="ADD",
                section=skill.section,
                issue=issue,
                keywords=normalized_keywords,
                insight=insight,
                skill_id=skill.id,
            )
        )
        return {"ok": True, "skill_id": skill.id}


def register_update_skill(agent: PydanticAgent[SMDeps, Any]) -> None:
    @agent.tool
    def update_skill(ctx: RunContext[SMDeps], skill_id: str, issue: str, keywords: list[str] | None = None, insight: str | None = None) -> dict[str, Any]:
        sb = ctx.deps.skillbook
        if sb is None:
            return {"error": "skillbook unavailable"}
        normalized_keywords = _normalize_keywords(keywords) if keywords is not None else None
        skill = sb.update_skill(skill_id, issue=issue, keywords=normalized_keywords, insight=insight)
        if skill is None:
            return {"error": f"skill not found: {skill_id}"}
        ctx.deps.operations.append(
            UpdateOperation(
                type="UPDATE",
                section=skill.section,
                skill_id=skill_id,
                issue=issue,
                keywords=normalized_keywords or [],
                insight=insight,
            )
        )
        return {"ok": True, "skill_id": skill_id}


def register_remove_skill(agent: PydanticAgent[SMDeps, Any]) -> None:
    @agent.tool
    def remove_skill(ctx: RunContext[SMDeps], skill_id: str, reason: str) -> dict[str, Any]:
        sb = ctx.deps.skillbook
        if sb is None:
            return {"error": "skillbook unavailable"}
        skill = sb.get_skill(skill_id)
        if skill is None:
            return {"error": f"skill not found: {skill_id}"}
        sb.remove_skill(skill_id)
        ctx.deps.operations.append(UpdateOperation(type="REMOVE", section=skill.section, skill_id=skill_id, reason=reason))
        return {"ok": True, "skill_id": skill_id}


def register_tag_skill(agent: PydanticAgent[SMDeps, Any]) -> None:
    @agent.tool
    def tag_skill(ctx: RunContext[SMDeps], skill_id: str, delta: Literal[1, -1, 0]) -> dict[str, Any]:
        sb = ctx.deps.skillbook
        if sb is None:
            return {"error": "skillbook unavailable"}
        skill = sb.tag_skill(skill_id, delta)
        if skill is None:
            return {"error": f"skill not found: {skill_id}"}
        ctx.deps.operations.append(UpdateOperation(type="TAG", section=skill.section, skill_id=skill_id, metadata={"delta": int(delta)}))
        return {"ok": True, "skill_id": skill_id, "helpful_count": skill.helpful_count}


def register_sm_read_skill(agent: PydanticAgent[SMDeps, Any]) -> None:
    @agent.tool
    def read_skill(ctx: RunContext[SMDeps], skill_id: str) -> dict[str, Any]:
        sb = ctx.deps.skillbook
        if sb is None:
            return {"error": "skillbook unavailable"}
        skill = sb.get_skill(skill_id)
        if skill is None:
            return {"error": f"skill not found: {skill_id}"}
        return {"id": skill.id, "section": skill.section, "issue": skill.issue, "insight": skill.insight}


# ace/implementations/skill_manager.py


class SkillManagerReport(BaseModel):
    """Structured output the SkillManager emits when it finishes."""

    reasoning: str = Field(..., description="Summary of the actions you took and why.")


class SkillManager(RecursiveAgent):
    """Transforms reflections into skillbook mutations via atomic tool calls."""

    def __init__(self, model: str | PydanticModel, *, config: Optional[AgenticConfig] = None) -> None:
        super().__init__(
            model,
            output_type=SkillManagerReport,
            system_prompt="You maintain the skillbook.",
            config=config or AgenticConfig(),
            tools=[
                register_sm_read_skill,
                register_add_skill,
                register_update_skill,
                register_remove_skill,
                register_tag_skill,
            ],
        )


skillbook = Skillbook()
manager = SkillManager(TestModel())
# the deps of one SkillManager run, with a sandbox as in ACE's own tests of `recurse`, so that it starts children
deps = SMDeps(config=manager.config, max_depth=manager.config.max_depth, skillbook=skillbook, sandbox=TraceSandbox(trace=None))
deps.run_session_fn = manager._run_child_session  # what RecursiveAgent.run sets before it starts the agent
run = (manager._agent, deps)
