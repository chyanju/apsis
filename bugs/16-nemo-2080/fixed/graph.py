# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Derived from NeMo Agent Toolkit (github.com/NVIDIA/NeMo-Agent-Toolkit) and modified; license text in LICENSE.

from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import StateGraph


class SupportState(TypedDict):
    """State passed through the customer support triage graph."""

    query: str
    category: str
    context: str
    policy: str
    compliance: str
    sentiment: str
    draft: str
    final_response: str


class _Function:
    async def ainvoke(self, value: str) -> str:
        return ""


classify_fn = research_fn = policy_fn = compliance_fn = sentiment_fn = draft_fn = review_fn = _Function()


async def classify(state: SupportState) -> dict:
    category = await classify_fn.ainvoke(state["query"])
    return {"category": str(category).strip().lower()}


async def research_context(state: SupportState) -> dict:
    context = await research_fn.ainvoke(f"{state['category']}|{state['query']}")
    return {"context": str(context)}


async def lookup_policy(state: SupportState) -> dict:
    policy = await policy_fn.ainvoke(f"{state['category']}|{state['query']}")
    return {"policy": str(policy)}


async def check_compliance(state: SupportState) -> dict:
    compliance = await compliance_fn.ainvoke(f"{state['category']}|{state['query']}")
    return {"compliance": str(compliance)}


async def analyze_sentiment(state: SupportState) -> dict:
    sentiment = await sentiment_fn.ainvoke(f"{state['category']}|{state['query']}")
    return {"sentiment": str(sentiment)}


async def draft_response(state: SupportState) -> dict:
    draft = await draft_fn.ainvoke(f"{state['query']}|{state['category']}|{state['context']}|"
                                   f"{state['policy']}|{state['compliance']}|{state['sentiment']}")
    return {"draft": str(draft)}


async def review(state: SupportState) -> dict:
    final = await review_fn.ainvoke(f"{state['query']}|{state['draft']}")
    return {"final_response": str(final)}


graph = StateGraph(SupportState)

graph.add_node("classify", classify)
graph.add_node("research_context", research_context)
graph.add_node("lookup_policy", lookup_policy)
graph.add_node("check_compliance", check_compliance)
graph.add_node("analyze_sentiment", analyze_sentiment)
graph.add_node("draft_response", draft_response)
graph.add_node("review", review)

graph.set_entry_point("classify")

# Parallel fan-out: 4 LOW-priority branches
graph.add_edge("classify", "research_context")
graph.add_edge("classify", "lookup_policy")
graph.add_edge("classify", "check_compliance")
graph.add_edge("classify", "analyze_sentiment")

# Converge: all 4 branches feed into draft  (wait-for-all barrier)
graph.add_edge(
    ["research_context", "lookup_policy", "check_compliance", "analyze_sentiment"],
    "draft_response",
)

# Sequential tail
graph.add_edge("draft_response", "review")
graph.add_edge("review", END)

app = graph.compile()
