//! `binding-capability` (β11 over-privileged-coordinator): a binding the role of one of its endpoints does not allow.

use crate::{Detector, Finding};
use apsis_ir::{attr, branch, EdgeKind, ExecutionModel, NodeKind, Workflow};
use std::collections::{BTreeMap, BTreeSet};

const NAME: &str = "binding-capability";

pub struct BindingCapability;

impl Detector for BindingCapability {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        let group_chat = matches!(wf.execution_model, ExecutionModel::GroupChatSpeaker);
        let mut out = Vec::new();
        coordinators_with_tools(wf, group_chat, &mut out);
        tools_from_undeclared_outputs(wf, &mut out);
        if group_chat {
            handoffs_to_non_agents(wf, &mut out);
            nested_chat_self_triggers(wf, &mut out);
        }
        out
    }
}

/// coordinator-declares-tools: a coordinator (the `manager` role, or a group-chat router) declares tools.
fn coordinators_with_tools(wf: &Workflow, group_chat: bool, out: &mut Vec<Finding>) {
    for n in wf.nodes.iter().filter(|n| n.flag(attr::DECLARES_TOOLS)) {
        let coordinator = n.role.as_deref() == Some("manager") || (group_chat && matches!(n.kind, NodeKind::Router));
        if coordinator {
            out.push(Finding::new(
                NAME,
                "coordinator-declares-tools",
                &n.id,
                format!(
                    "coordinator `{}` declares tools, but its role only selects the next speaker and cannot call them",
                    n.id
                ),
            ));
        }
    }
}

/// tool-from-undeclared-output: a step is bound as a tool through an output it does not declare.
fn tools_from_undeclared_outputs(wf: &Workflow, out: &mut Vec<Finding>) {
    for e in wf.edges.iter().filter(|e| matches!(e.kind, EdgeKind::Tool) && !e.from.socket.is_empty()) {
        let Some(src) = wf.node(&e.from.node) else { continue };
        if !src.outputs.is_empty() && src.output(&e.from.socket).is_none() {
            out.push(Finding::new(
                NAME,
                "tool-from-undeclared-output",
                format!("{}.{}", e.from.node, e.from.socket),
                format!(
                    "`{}` is bound as a tool of `{}` through output `{}`, which it does not declare, so it provides no tool",
                    e.from.node, e.to.node, e.from.socket
                ),
            ));
        }
    }
}

/// handoff-to-non-agent (group-chat model): a handoff from or to an executor or a tool; one finding per step.
fn handoffs_to_non_agents(wf: &Workflow, out: &mut Vec<Finding>) {
    let is_non_agent = |id: &str| wf.node(id).is_some_and(|n| matches!(n.kind, NodeKind::Executor | NodeKind::Tool));
    // step -> (it is the target of some handoff, the steps on the other side)
    let mut offenders: BTreeMap<&str, (bool, BTreeSet<&str>)> = BTreeMap::new();
    for e in wf.edges.iter().filter(|e| matches!(e.kind, EdgeKind::Handoff)) {
        for (this, other, is_target) in [(&e.to.node, &e.from.node, true), (&e.from.node, &e.to.node, false)] {
            if is_non_agent(this) {
                let entry = offenders.entry(this).or_default();
                entry.0 |= is_target;
                entry.1.insert(other);
            }
        }
    }
    for (id, (is_target, others)) in offenders {
        let side = if is_target { "is the target of a handoff from" } else { "hands off to" };
        out.push(Finding::new(
            NAME,
            "handoff-to-non-agent",
            id,
            format!("`{id}` {side} {others:?} but is not an agent, so the handoff cannot be taken"),
        ));
    }
}

/// nested-chat-self-trigger (group-chat model): an agent starts a nested chat it also takes part in.
fn nested_chat_self_triggers(wf: &Workflow, out: &mut Vec<Finding>) {
    for c in &wf.nodes {
        let triggers: BTreeSet<&str> = wf
            .edges
            .iter()
            .filter(|e| {
                e.to.node == c.id
                    && matches!(e.kind, EdgeKind::Control)
                    && e.branch.as_deref() == Some(branch::NESTED_CHAT_TRIGGER)
            })
            .map(|e| e.from.node.as_str())
            .collect();
        let participants: BTreeSet<&str> = wf
            .edges
            .iter()
            .filter(|e| {
                e.from.node == c.id
                    && matches!(e.kind, EdgeKind::Subflow)
                    && e.branch.as_deref() == Some(branch::NESTED_CHAT)
            })
            .map(|e| e.to.node.as_str())
            .collect();
        for agent in triggers.intersection(&participants) {
            out.push(Finding::new(
                NAME,
                "nested-chat-self-trigger",
                *agent,
                format!("agent `{agent}` starts the nested chat of `{}` and also takes part in it, so its turn starts a chat it is part of", c.id),
            ));
        }
    }
}
