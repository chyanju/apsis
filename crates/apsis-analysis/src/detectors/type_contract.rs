//! `type-contract` (β3 mistyped-handoff): a value handed to a step that does not accept its type.

use crate::types::{assignable, collectible};
use crate::{Detector, Finding};
use apsis_ir::{attr, EdgeKind, ExecutionModel, Node, NodeKind, Program, Workflow};
use std::collections::BTreeSet;

const NAME: &str = "type-contract";

pub struct TypeContract;

impl Detector for TypeContract {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        check(wf, &BTreeSet::new())
    }

    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        // A sub-workflow shares its parent's state schema, so a channel declared anywhere counts everywhere.
        let declared: BTreeSet<&str> =
            prog.workflows.iter().flat_map(|w| w.channels.iter().map(|c| c.name.as_str())).collect();
        let mut out: Vec<Finding> = prog.workflows.iter().flat_map(|w| check(w, &declared)).collect();
        for wf in &prog.workflows {
            typed_bindings(prog, wf, &mut out);
        }
        out
    }
}

/// edge-type-mismatch across a sub-workflow boundary: an unconverted out-binding whose types are not assignable.
fn typed_bindings(prog: &Program, wf: &Workflow, out: &mut Vec<Finding>) {
    let coercive = matches!(wf.execution_model, ExecutionModel::VisualDataflow);
    for host in &wf.nodes {
        let Some(sr) = &host.subflow_ref else { continue };
        let Some(sub) = prog.workflow(&sr.workflow) else { continue };
        for b in sr.out_bindings.iter().filter(|b| !b.converted) {
            let inner = sub.node(&b.inner.node).and_then(|n| n.output(&b.inner.socket));
            let outer = host.output(&b.outer.socket);
            let (Some(i), Some(o)) = (inner, outer) else { continue };
            if !assignable(&i.type_repr, &o.type_repr, coercive) {
                out.push(Finding::new(
                    NAME,
                    "edge-type-mismatch",
                    format!("{}.{}->{}.{}", b.inner.node, b.inner.socket, host.id, b.outer.socket),
                    format!(
                        "`{}` hands output `{}.{}` of type `{}` back as its output `{}`, declared as `{}`, which does not accept it",
                        host.id, b.inner.node, b.inner.socket, i.type_repr, b.outer.socket, o.type_repr
                    ),
                ));
            }
        }
    }
}

fn check(wf: &Workflow, declared_elsewhere: &BTreeSet<&str>) -> Vec<Finding> {
    let mut out = Vec::new();
    typed_edges(wf, &mut out);
    streams(wf, &mut out);
    match wf.execution_model {
        ExecutionModel::BspSuperstep => undeclared_channel_writes(wf, declared_elsewhere, &mut out),
        ExecutionModel::GroupChatSpeaker => message_routing(wf, &mut out),
        ExecutionModel::VisualDataflow => loop_targets(wf, &mut out),
        _ => {}
    }
    out
}

/// edge-type-mismatch: an edge between two typed sockets whose output type is not assignable to the input type.
fn typed_edges(wf: &Workflow, out: &mut Vec<Finding>) {
    let coercive = matches!(wf.execution_model, ExecutionModel::VisualDataflow);
    for e in &wf.edges {
        let from = wf.node(&e.from.node).and_then(|n| n.output(&e.from.socket));
        let to = wf.node(&e.to.node).and_then(|n| n.input(&e.to.socket));
        let (Some(o), Some(i)) = (from, to) else { continue };
        if !assignable(&o.type_repr, &i.type_repr, coercive) {
            out.push(Finding::new(
                NAME,
                "edge-type-mismatch",
                format!("{}.{}->{}.{}", e.from.node, e.from.socket, e.to.node, e.to.socket),
                format!(
                    "connection `{}.{} -> {}.{}` binds output type `{}` to input type `{}`, which does not accept it",
                    e.from.node, e.from.socket, e.to.node, e.to.socket, o.type_repr, i.type_repr
                ),
            ));
        }
    }
}

/// stream-into-non-chat-sink: a step that streams its output, wired into a step that does not take a stream.
fn streams(wf: &Workflow, out: &mut Vec<Finding>) {
    for e in &wf.edges {
        let streaming = wf.node(&e.from.node).is_some_and(|n| n.flag(attr::STREAM));
        let accepted = wf.node(&e.to.node).is_some_and(|n| n.flag(attr::ACCEPTS_STREAM));
        if streaming && !accepted {
            out.push(Finding::new(
                NAME,
                "stream-into-non-chat-sink",
                format!("{}->{}", e.from.node, e.to.node),
                format!("`{}` streams its output into `{}`, which does not take a stream", e.from.node, e.to.node),
            ));
        }
    }
}

/// undeclared-channel-write (bulk-synchronous model): a step output that is not a channel of the state schema.
fn undeclared_channel_writes(wf: &Workflow, declared_elsewhere: &BTreeSet<&str>, out: &mut Vec<Finding>) {
    if wf.channels.is_empty() {
        return;
    }
    let declared: BTreeSet<&str> =
        wf.channels.iter().map(|c| c.name.as_str()).chain(declared_elsewhere.iter().copied()).collect();
    for n in &wf.nodes {
        for o in n.outputs.iter().filter(|o| !declared.contains(o.name.as_str())) {
            out.push(Finding::new(
                NAME,
                "undeclared-channel-write",
                format!("{}.{}", n.id, o.name),
                format!(
                    "step `{}` writes state key `{}`, which the state schema does not declare, so nothing can read it",
                    n.id, o.name
                ),
            ));
        }
    }
}

fn receives_list(n: &Node) -> bool {
    n.attr(attr::FAN_IN_DELIVERY) == Some("list")
}

/// The types a message of type `sent` from `n` is an instance of: its own and those in `supertypes:<sent>`.
fn instance_types<'a>(n: &'a Node, sent: &'a str) -> Vec<&'a str> {
    let supertypes = n.attr(&format!("{}{sent}", attr::SUPERTYPES)).unwrap_or("");
    std::iter::once(sent).chain(supertypes.split(',').map(str::trim).filter(|t| !t.is_empty())).collect()
}

/// Group-chat rules: edges name no sockets, so producer output types are compared with consumer handler types.
fn message_routing(wf: &Workflow, out: &mut Vec<Finding>) {
    // no-handler-for-message via a channel: a `takes_all_messages` reader needs a handler for every type posted.
    for ch in &wf.channels {
        for r in ch.readers.iter().filter_map(|id| wf.node(id)).filter(|n| n.flag(attr::TAKES_ALL_MESSAGES)) {
            for w in ch.writers.iter().filter(|w| **w != r.id).filter_map(|id| wf.node(id)) {
                if let Some(f) = unhandled_messages(w, r, "is handed every message posted to the channel `", &ch.name) {
                    out.push(f);
                }
            }
        }
    }

    // send-of-undeclared-type: no type the sent message is an instance of is in the step's declared sends.
    for n in &wf.nodes {
        let Some(declared) = n.attr(attr::DECLARED_SENDS) else { continue };
        let declared: Vec<&str> = declared.split(',').map(str::trim).filter(|t| !t.is_empty()).collect();
        for o in n.outputs.iter().filter(|o| o.type_repr != "Never" && !o.type_repr.is_empty()) {
            if !instance_types(n, &o.type_repr).iter().any(|t| declared.iter().any(|d| assignable(t, d, false))) {
                out.push(Finding::new(
                    NAME,
                    "send-of-undeclared-type",
                    format!("{}.{}", n.id, o.name),
                    format!(
                        "`{}` sends `{}`, which its declared protocol does not list ({declared:?}); the send is rejected",
                        n.id, o.type_repr
                    ),
                ));
            }
        }
    }

    for e in &wf.edges {
        let (Some(a), Some(b)) = (wf.node(&e.from.node), wf.node(&e.to.node)) else { continue };
        let location = || format!("{}->{}", a.id, b.id);

        // never-emitter-into-required-input: a producer emitting only `Never` or untyped feeds a mandatory input.
        let routing_or_data =
            matches!(e.kind, EdgeKind::Control | EdgeKind::Data | EdgeKind::Conditional | EdgeKind::Handoff);
        let emits_nothing =
            !a.outputs.is_empty() && a.outputs.iter().all(|o| o.type_repr == "Never" || o.type_repr.is_empty());
        if routing_or_data && emits_nothing && b.inputs.iter().any(|s| s.mandatory) {
            out.push(Finding::new(
                NAME,
                "never-emitter-into-required-input",
                location(),
                format!(
                    "`{}` sends no message (it emits only `Never`), yet it is wired to `{}`, which requires one",
                    a.id, b.id
                ),
            ));
        }

        // no-handler-for-message: no handler of the consumer accepts any type the producer sends, as it receives them.
        if matches!(e.kind, EdgeKind::Control | EdgeKind::Data | EdgeKind::Conditional) {
            let emitted: Vec<&str> = a.outputs.iter().map(|o| o.type_repr.as_str()).filter(|t| *t != "Never").collect();
            let handled: Vec<&str> = b.inputs.iter().map(|s| s.type_repr.as_str()).collect();
            // Unknown types (no outputs or no inputs) may leave a message unhandled, unless a handler takes any.
            let catch_all = handled.iter().any(|i| i.is_empty() || *i == "Any" || *i == "object");
            if (a.outputs.is_empty() || b.inputs.is_empty()) && !catch_all {
                out.push(Finding::new(
                    NAME,
                    "no-handler-for-message",
                    location(),
                    format!("the messages `{}` sends to `{}`, or the handlers of `{}`, are not known, so a message may have no handler", a.id, b.id, b.id),
                ));
                continue;
            }
            if emitted.is_empty() || handled.is_empty() {
                continue;
            }
            let joins = receives_list(b);
            let accepts = |t: &str, i: &str| if joins { collectible(t, i) } else { assignable(t, i, false) };
            let has_handler = |o: &str| instance_types(a, o).iter().any(|t| handled.iter().any(|i| accepts(t, i)));
            if b.flag(attr::TAKES_ALL_MESSAGES) {
                if let Some(f) = unhandled_messages(a, b, "is handed every message sent over the edge", "") {
                    out.push(f);
                }
            } else if !emitted.iter().any(|o| has_handler(o)) {
                out.push(Finding::new(
                    NAME,
                    "no-handler-for-message",
                    location(),
                    format!("`{}` sends {emitted:?} to `{}`, whose handlers accept only {handled:?}", a.id, b.id),
                ));
            }
        }
    }
}

/// no-handler-for-message for a `b` handed every message: the types `a` sends that no handler of `b` takes.
fn unhandled_messages(a: &Node, b: &Node, how: &str, channel: &str) -> Option<Finding> {
    let emitted: Vec<&str> = a.outputs.iter().map(|o| o.type_repr.as_str()).filter(|t| *t != "Never").collect();
    let handled: Vec<&str> = b.inputs.iter().map(|s| s.type_repr.as_str()).collect();
    let catch_all = handled.iter().any(|i| i.is_empty() || *i == "Any" || *i == "object");
    if catch_all {
        return None;
    }
    let tail = if channel.is_empty() { String::new() } else { format!("{channel}`") };
    if a.outputs.is_empty() || b.inputs.is_empty() {
        return Some(Finding::new(
            NAME,
            "no-handler-for-message",
            format!("{}->{}", a.id, b.id),
            format!("`{}` {how}{tail}, and the messages `{}` sends there, or its handlers, are not known, so a message may have no handler", b.id, a.id),
        ));
    }
    let unhandled: Vec<&str> = emitted
        .iter()
        .copied()
        .filter(|o| !instance_types(a, o).iter().any(|t| handled.iter().any(|i| assignable(t, i, false))))
        .collect();
    (!unhandled.is_empty()).then(|| {
        Finding::new(
            NAME,
            "no-handler-for-message",
            format!("{}->{}", a.id, b.id),
            format!("`{}` {how}{tail}; `{}` sends {unhandled:?} there, and the handlers of `{}` accept only {handled:?}", b.id, a.id, b.id),
        )
    })
}

/// loop-target-cannot-host-body (visual model): a loop node that loops back to a tool, a router or an end node.
fn loop_targets(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in wf.nodes.iter().filter(|n| matches!(n.kind, NodeKind::Loop)) {
        for t in n.declared_targets.iter().filter_map(|t| wf.node(t)) {
            if matches!(t.kind, NodeKind::Tool | NodeKind::Router | NodeKind::End) {
                out.push(Finding::new(
                    NAME,
                    "loop-target-cannot-host-body",
                    format!("{}->{}", n.id, t.id),
                    format!(
                        "loop `{}` loops back to `{}`, a {:?} node, which cannot run the loop body",
                        n.id, t.id, t.kind
                    ),
                ));
            }
        }
    }
}
