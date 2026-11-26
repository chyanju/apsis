//! `target-resolution` (β4 missing-route-target): routing that names nothing, cannot proceed, or goes two ways.

use crate::graph::{is_routing_edge, is_static_edge};
use crate::{Detector, Finding};
use apsis_ir::{attr, Edge, EdgeKind, ExecutionModel, NodeKind, Program, Workflow, END, START};
use std::collections::BTreeSet;

const NAME: &str = "target-resolution";

/// Target names that resolve without a step: entry, exit, the human participant, the "finished" route.
const SENTINELS: [&str; 7] = [START, END, "START", "END", "user", "human", "FINISH"];

pub struct TargetResolution;

impl Detector for TargetResolution {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        check(wf, &BTreeSet::new())
    }

    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        // A step may route into another workflow of the program, so a name resolves anywhere in it.
        let names: BTreeSet<&str> = prog
            .workflows
            .iter()
            .flat_map(|w| w.nodes.iter().flat_map(|n| std::iter::once(n.id.as_str()).chain(n.name.as_deref())))
            .collect();
        prog.workflows.iter().flat_map(|w| check(w, &names)).collect()
    }
}

fn check(wf: &Workflow, names_elsewhere: &BTreeSet<&str>) -> Vec<Finding> {
    let mut out = Vec::new();
    unresolved_references(wf, names_elsewhere, &mut out);
    unresolved_routes(wf, &mut out);
    stale_routes(wf, &mut out);
    match wf.execution_model {
        ExecutionModel::BspSuperstep => {
            double_routes(wf, &mut out);
            labels_outside_the_path_map(wf, &mut out);
        }
        ExecutionModel::GroupChatSpeaker => {
            routers_without_route(wf, &mut out);
            group_chat_routing(wf, &mut out);
        }
        _ => routers_without_route(wf, &mut out),
    }
    out
}

/// unresolved-route: a `goto` target or routing-function return value the front-end could not evaluate.
fn unresolved_routes(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in &wf.nodes {
        if n.flag(attr::GOTO_UNRESOLVED) {
            out.push(Finding::new(
                NAME,
                "unresolved-route",
                &n.id,
                format!("step `{}` routes to a target that cannot be determined before the run; it may name a step the workflow does not have", n.id),
            ));
        }
        for (branch, _) in n.branch_attrs(attr::ROUTER_UNRESOLVED).filter(|(_, v)| *v == "true") {
            out.push(Finding::new(
                NAME,
                "unresolved-route",
                format!("{}.{branch}", n.id),
                format!("the routing function of `{}` (branch `{branch}`) returns a value that cannot be determined before the run; it may name a target the edge does not declare", n.id),
            ));
        }
    }
}

fn is_value_wire(e: &Edge) -> bool {
    !e.from.socket.is_empty() && e.branch.is_none() && !matches!(e.kind, EdgeKind::Conditional)
}

/// A declared target, an edge endpoint or an output port that names nothing.
fn unresolved_references(wf: &Workflow, names_elsewhere: &BTreeSet<&str>, out: &mut Vec<Finding>) {
    let mut known: BTreeSet<&str> = names_elsewhere.clone();
    known.extend(wf.nodes.iter().flat_map(|n| std::iter::once(n.id.as_str()).chain(n.name.as_deref())));
    known.extend(SENTINELS);

    // unresolved-target: a declared routing target that names no step.
    for n in &wf.nodes {
        for t in n.declared_targets.iter().map(|t| t.trim()).filter(|t| !t.is_empty() && !known.contains(t)) {
            out.push(Finding::new(
                NAME,
                "unresolved-target",
                &n.id,
                format!("step `{}` declares routing target `{t}`, which names no step", n.id),
            ));
        }
    }
    for e in &wf.edges {
        // unresolved-edge-endpoint: an edge whose source or target names no step.
        for (role, end) in [("source", &e.from), ("target", &e.to)] {
            if !end.node.is_empty() && wf.node(&end.node).is_none() && !known.contains(end.node.as_str()) {
                out.push(Finding::new(
                    NAME,
                    "unresolved-edge-endpoint",
                    &end.node,
                    format!("the {role} `{}` of an edge names no step", end.node),
                ));
            }
        }
        // undeclared-output-port: a value wire from an undeclared output; `binding-capability` takes tool bindings.
        if is_value_wire(e) && !matches!(e.kind, EdgeKind::Tool) {
            let Some(src) = wf.node(&e.from.node) else { continue };
            if !src.outputs.is_empty() && src.output(&e.from.socket).is_none() {
                out.push(Finding::new(
                    NAME,
                    "undeclared-output-port",
                    format!("{}.{}", e.from.node, e.from.socket),
                    format!("an edge leaves `{}.{}`, an output the step does not declare", e.from.node, e.from.socket),
                ));
            }
        }
    }
}

/// stale-route: a router reads channels its input schema filters out (`router_filtered_reads`).
fn stale_routes(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in &wf.nodes {
        let Some(channels) = n.attr(attr::ROUTER_FILTERED_READS).filter(|c| !c.is_empty()) else { continue };
        out.push(Finding::new(
            NAME,
            "stale-route",
            &n.id,
            format!("router `{}` reads channel(s) `{channels}`, which its input schema filters out; it routes on a missing or stale value", n.id),
        ));
    }
}

/// router-without-route: a router that declares no target and has no outgoing routing edge.
fn routers_without_route(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in wf.nodes.iter().filter(|n| matches!(n.kind, NodeKind::Router) && n.declared_targets.is_empty()) {
        if !wf.edges.iter().any(|e| e.from.node == n.id && is_routing_edge(e)) {
            out.push(Finding::new(
                NAME,
                "router-without-route",
                &n.id,
                format!("router `{}` declares no target and has no outgoing route, so it cannot route", n.id),
            ));
        }
    }
}

/// double-route (bulk-synchronous model): a step with a static edge that also routes dynamically elsewhere.
/// A route into the parent graph ends the step's pass, so it does not count.
fn double_routes(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in &wf.nodes {
        let into_parent = |t: &str| n.flag(attr::COMMAND_PARENT) && t != END && wf.node(t).is_none();
        let dynamic: BTreeSet<&str> = wf
            .edges
            .iter()
            .filter(|e| e.from.node == n.id && matches!(e.kind, EdgeKind::Handoff | EdgeKind::Conditional))
            .map(|e| e.to.node.as_str())
            .chain(n.declared_targets.iter().map(String::as_str))
            .filter(|t| !into_parent(t))
            .collect();
        if dynamic.is_empty() {
            continue;
        }
        let static_targets: BTreeSet<&str> =
            wf.edges.iter().filter(|e| e.from.node == n.id && is_static_edge(e)).map(|e| e.to.node.as_str()).collect();
        let confined_to = |t: &str| dynamic.len() == 1 && dynamic.contains(t);
        for &t in static_targets.iter().filter(|&&t| t != END && !confined_to(t)) {
            let others: Vec<&str> = dynamic.iter().copied().filter(|d| *d != t).collect();
            out.push(Finding::new(
                NAME,
                "double-route",
                format!("{}->{t}", n.id),
                format!(
                    "step `{}` has a static edge to `{t}` and also routes dynamically to {others:?}: the static edge is taken on every pass, so `{t}` runs even when the route picks another target",
                    n.id
                ),
            ));
        }
    }
}

/// label-outside-path-map (bulk-synchronous model): a routing function can return a label its path map lacks.
fn labels_outside_the_path_map(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in &wf.nodes {
        for (branch, map) in n.branch_attrs(attr::ROUTER_MAP) {
            let declared: BTreeSet<&str> = map.split(',').map(str::trim).filter(|s| !s.is_empty()).collect();
            let Some(returns) = n.attr(&format!("{}{branch}", attr::ROUTER_RETURNS)) else { continue };
            for label in returns.split(',').map(str::trim).filter(|l| !l.is_empty() && !declared.contains(l)) {
                out.push(Finding::new(
                    NAME,
                    "label-outside-path-map",
                    format!("{}:{label}", n.id),
                    format!(
                        "router `{}` can return `{label}`, which its path map {declared:?} does not contain; the run fails when that branch is taken",
                        n.id
                    ),
                ));
            }
        }
    }
}

/// Group-chat rules: routing by participant name, handoff or proposed call.
fn group_chat_routing(wf: &Workflow, out: &mut Vec<Finding>) {
    let has_handoff = |id: &str| wf.edges.iter().any(|e| e.from.node == id && matches!(e.kind, EdgeKind::Handoff));

    // invalid-participant-name: an agent name, the chat's routing key, that is empty or has whitespace.
    for n in wf.nodes.iter().filter(|n| matches!(n.kind, NodeKind::Agent)) {
        let Some(name) = &n.name else { continue };
        if name.is_empty() || name.chars().any(char::is_whitespace) {
            out.push(Finding::new(
                NAME,
                "invalid-participant-name",
                &n.id,
                format!(
                    "agent `{}` is named {name:?}, which is not a valid participant name (empty or with whitespace)",
                    n.id
                ),
            ));
        }
    }

    // coordinator-without-handoff: in a handoff orchestration, a start agent with no handoff target or edge.
    let agents = wf.nodes.iter().filter(|n| matches!(n.kind, NodeKind::Agent)).count();
    if agents >= 2 && wf.edges.iter().any(|e| matches!(e.kind, EdgeKind::Handoff)) {
        for n in wf.start_nodes.iter().filter_map(|s| wf.node(s)).filter(|n| matches!(n.kind, NodeKind::Agent)) {
            if n.declared_targets.is_empty() && !has_handoff(&n.id) {
                out.push(Finding::new(
                    NAME,
                    "coordinator-without-handoff",
                    &n.id,
                    format!("start agent `{}` declares no handoff target and has no handoff edge, so it can pass control to no other agent", n.id),
                ));
            }
        }
    }

    // no-next-speaker: under restricted transitions (handoff edges), a participant that starts no transition.
    for r in wf.nodes.iter().filter(|r| r.attr(attr::SPEAKER_TRANSITIONS) == Some("restricted")) {
        for t in &r.declared_targets {
            let Some(m) = wf.nodes.iter().find(|n| &n.id == t || n.name.as_deref() == Some(t.as_str())) else {
                continue;
            };
            if matches!(m.kind, NodeKind::Agent) && !has_handoff(&m.id) {
                out.push(Finding::new(
                    NAME,
                    "no-next-speaker",
                    &m.id,
                    format!(
                        "participant `{}` has no allowed next speaker: `{}` restricts speaker transitions and none starts at `{}`, so the chat cannot continue once it has spoken",
                        m.id, r.id, m.id
                    ),
                ));
            }
        }
    }

    // tool-without-executor: some agent can propose a call of the tool, and no agent can execute it.
    for n in wf.nodes.iter().filter(|n| matches!(n.kind, NodeKind::Tool)) {
        let proposable = n.attr(attr::CALLERS).is_some_and(|c| !c.is_empty());
        if proposable && n.attr(attr::HAS_EXECUTOR) == Some("false") {
            out.push(Finding::new(
                NAME,
                "tool-without-executor",
                &n.id,
                format!("an agent can propose a call of `{}`, but no agent can execute it", n.id),
            ));
        }
    }
}
