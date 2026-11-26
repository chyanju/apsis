//! `readiness-liveness` (β1 starved-step): a step that cannot become ready, or becomes ready too early.

use crate::graph::{is_cycle, is_routing_edge, must_fed, reaches, sccs, succ_map, succ_over};
use crate::{Detector, Finding};
use apsis_ir::{attr, EdgeKind, ExecutionModel, InputSocket, Node, NodeKind, Program, Workflow, END, START};
use std::collections::BTreeSet;

const NAME: &str = "readiness-liveness";

pub struct ReadinessLiveness;

impl Detector for ReadinessLiveness {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        check(wf, &BTreeSet::new(), true)
    }

    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        // Steps a sub-workflow routes to in its parent count as entered from outside.
        let routed_from_child: BTreeSet<&str> = prog
            .workflows
            .iter()
            .flat_map(|w| w.nodes.iter())
            .filter(|n| n.flag(attr::COMMAND_PARENT))
            .flat_map(|n| n.declared_targets.iter().map(String::as_str))
            .collect();
        // a sub-workflow ends when its parent continues, so only a top-level workflow needs a way to END
        let embedded: BTreeSet<&str> = prog
            .workflows
            .iter()
            .flat_map(|w| w.nodes.iter().filter_map(|n| n.subflow_ref.as_ref().map(|r| r.workflow.as_str())))
            .collect();
        prog.workflows
            .iter()
            .flat_map(|w| {
                let entered: BTreeSet<&str> =
                    w.nodes.iter().map(|n| n.id.as_str()).filter(|id| routed_from_child.contains(id)).collect();
                check(w, &entered, !w.id.as_deref().is_some_and(|id| embedded.contains(id)))
            })
            .collect()
    }
}

fn check(wf: &Workflow, entered_from_outside: &BTreeSet<&str>, top_level: bool) -> Vec<Finding> {
    let mut out = Vec::new();
    if matches!(wf.execution_model, ExecutionModel::DataflowReadiness) {
        dataflow_readiness(wf, &mut out);
    }
    eager_starts(wf, &mut out);
    unfed_required_inputs(wf, &mut out);
    unbound_template_variables(wf, &mut out);
    deadlocked_joins(wf, &mut out);
    loops_seeded_from_their_own_cycle(wf, &mut out);
    if matches!(wf.execution_model, ExecutionModel::BspSuperstep) {
        unreachable_steps(wf, entered_from_outside, &mut out);
        if top_level {
            ends_without_terminal(wf, &mut out);
        }
    }
    out
}

/// no-terminal (LangGraph): no step of a top-level workflow routes to END; each step with no way on is a dead end
/// where the run stops without reaching END.
fn ends_without_terminal(wf: &Workflow, out: &mut Vec<Finding>) {
    if wf.framework != "langgraph" {
        return;
    }
    let unresolved = |n: &Node| n.flag(attr::GOTO_UNRESOLVED) || n.branch_attrs(attr::ROUTER_UNRESOLVED).next().is_some();
    let ends = wf.edges.iter().any(|e| e.to.node == END)
        || wf.nodes.iter().any(|n| n.declared_targets.iter().any(|t| t == END) || unresolved(n));
    if ends {
        return;
    }
    for n in wf.nodes.iter().filter(|n| n.id != START && n.id != END) {
        if !wf.edges.iter().any(|e| e.from.node == n.id) && n.declared_targets.is_empty() {
            out.push(Finding::new(
                NAME,
                "no-terminal",
                &n.id,
                format!(
                    "step `{}` has no way on and no step of the workflow routes to END: the run stops after it without reaching END, so its end is never declared",
                    n.id
                ),
            ));
        }
    }
}

fn is_fed(wf: &Workflow, n: &Node, s: &InputSocket) -> bool {
    wf.edges_into(&n.id, &s.name).next().is_some()
}

/// A wired mandatory or variadic input that a run can leave without a value.
fn may_starve(wf: &Workflow, n: &Node, s: &InputSocket) -> bool {
    (s.mandatory || s.variadic) && is_fed(wf, n, s) && !must_fed(wf, &n.id, &s.name, s.has_default)
}

/// Dataflow-model rules: a step runs once its inputs are ready, and a default counts as ready.
fn dataflow_readiness(wf: &Workflow, out: &mut Vec<Finding>) {
    let succ = succ_map(wf);
    // a sink's output is an output of the workflow
    let is_sink = |n: &Node| !wf.edges.iter().any(|e| e.from.node == n.id);
    // Two or more starvable sinks are a router's alternative outputs: exactly one runs.
    let starvable_sinks =
        wf.nodes.iter().filter(|n| is_sink(n) && n.inputs.iter().any(|s| may_starve(wf, n, s))).count();
    let on_cycle: BTreeSet<&str> = sccs(wf, &succ).into_iter().filter(|c| is_cycle(c, &succ)).flatten().collect();

    for n in &wf.nodes {
        // no-input-component: a step without inputs is never scheduled, yet another step consumes its output.
        if n.inputs.is_empty() && !is_sink(n) {
            out.push(Finding::new(
                NAME,
                "no-input-component",
                &n.id,
                format!("component `{}` has no input sockets, so it is never scheduled, yet its output is consumed downstream", n.id),
            ));
        }
        // No mandatory input: the step can fire on defaults if an input is unwired or it has a single input.
        let runs_on_defaults = !n.inputs.iter().any(|i| i.mandatory);
        let has_unfed_input = n.inputs.iter().any(|i| !is_fed(wf, n, i));
        let can_fire_early = runs_on_defaults && (n.inputs.len() == 1 || has_unfed_input);
        for s in &n.inputs {
            // premature-default: an input that has a default and is also wired, on a step that can fire early.
            if s.has_default && is_fed(wf, n, s) && !s.variadic && can_fire_early {
                out.push(Finding::new(
                    NAME,
                    "premature-default",
                    format!("{}.{}", n.id, s.name),
                    format!(
                        "input `{}.{}` has a default and an incoming connection, and `{}` has no mandatory input; readiness may fire it on defaults before the upstream value arrives (early/double run)",
                        n.id, s.name, n.id
                    ),
                ));
            }
            // conditional-producers-only: an input that may starve, on a sink or a variadic join.
            if may_starve(wf, n, s) {
                let mut producers = wf.edges_into(&n.id, &s.name).map(|e| e.from.node.as_str()).peekable();
                let delivered_by_loop = producers.peek().is_some() && producers.all(|p| on_cycle.contains(p));
                let alternative_output = is_sink(n) && starvable_sinks >= 2;
                if (s.variadic || is_sink(n)) && !alternative_output && !delivered_by_loop {
                    let kind = if s.variadic { "variadic input" } else { "input" };
                    out.push(Finding::new(
                        NAME,
                        "conditional-producers-only",
                        format!("{}.{}", n.id, s.name),
                        format!(
                            "{kind} `{}.{}` has only producers that may omit their output and no default; it is left without a value when every branch is skipped",
                            n.id, s.name
                        ),
                    ));
                }
            }
        }
    }
}

/// premature-default (`eager_start`): a step not behind producer `p`, off the cycle, feeds `v` or a step behind it.
fn eager_starts(wf: &Workflow, out: &mut Vec<Finding>) {
    let succ = succ_map(wf);
    let comps = sccs(wf, &succ);
    for v in wf.nodes.iter().filter(|n| n.flag(attr::EAGER_START)) {
        let Some(cycle) = comps.iter().find(|c| c.contains(&v.id.as_str())).filter(|c| is_cycle(c, &succ)) else {
            continue;
        };
        let on_cycle = |x: &str| cycle.contains(&x);
        let mut reported = BTreeSet::new();
        for e in wf.edges.iter().filter(|e| e.to.node == v.id && !on_cycle(&e.from.node)) {
            let p = e.from.node.as_str();
            let trigger = wf.edges.iter().find(|z| {
                let zs = z.from.node.as_str();
                zs != p
                    && !on_cycle(zs)
                    && !reaches(&succ, p, zs)
                    && !reaches(&succ, &v.id, zs)
                    && (z.to.node == v.id || reaches(&succ, &v.id, &z.to.node))
            });
            let Some(z) = trigger else { continue };
            if !reported.insert(e.to.socket.as_str()) {
                continue;
            }
            out.push(Finding::new(
                NAME,
                "premature-default",
                format!("{}.{}", v.id, e.to.socket),
                format!(
                    "input `{}.{}` is fed by `{p}` from outside the cycle of `{}`, which the engine starts without waiting for its inputs from outside the cycle; `{}` need not wait for `{p}` and feeds `{}`, so `{}` can start before `{p}` has run and read the input's default",
                    v.id, e.to.socket, v.id, z.from.node, z.to.node, v.id
                ),
            ));
        }
    }
}

/// unfed-required-input: a mandatory input that only an edge can fill, with no edge into it.
fn unfed_required_inputs(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in &wf.nodes {
        for s in n.inputs.iter().filter(|s| s.mandatory && s.connection_only && !is_fed(wf, n, s)) {
            out.push(Finding::new(
                NAME,
                "unfed-required-input",
                format!("{}.{}", n.id, s.name),
                format!(
                    "required input `{}.{}` (type `{}`) can only be filled by a connection and has none",
                    n.id, s.name, s.type_repr
                ),
            ));
        }
    }
}

/// unbound-template-variable: the input named by `template_values_input` is not wired.
fn unbound_template_variables(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in wf.nodes.iter().filter(|n| !n.requires_vars.is_empty()) {
        let Some(s) = n.attr(attr::TEMPLATE_VALUES_INPUT).and_then(|name| n.input(name)) else { continue };
        if !is_fed(wf, n, s) {
            out.push(Finding::new(
                NAME,
                "unbound-template-variable",
                &n.id,
                format!(
                    "prompt `{}` references template variable(s) {:?} but its input `{}`, which binds them, is not connected; the variables render empty",
                    n.id, n.requires_vars, s.name
                ),
            ));
        }
    }
}

/// `(router, branch)` when the only routing edge into `p` is conditional; a data-gate branch is an output socket.
/// One step back only: a branch may fan out, so a join further down can still receive all its inputs.
fn gating_branch<'a>(wf: &'a Workflow, p: &'a str) -> Option<(&'a str, &'a str)> {
    let ins: Vec<_> = wf.edges.iter().filter(|e| e.to.node == p && is_routing_edge(e)).collect();
    let [e] = ins.as_slice() else { return None };
    if !matches!(e.kind, EdgeKind::Conditional) {
        return None;
    }
    let data_gate = wf.node(&e.from.node).and_then(|r| r.attr(attr::BRANCH_OUTPUTS)) == Some(attr::BRANCH_DATA_GATE);
    let branch = if data_gate && !e.from.socket.is_empty() { e.from.socket.as_str() } else { e.to.node.as_str() };
    Some((e.from.node.as_str(), branch))
}

/// An edge an AND-join waits for.
fn joins_on(e: &apsis_ir::Edge) -> bool {
    is_routing_edge(e) || matches!(e.kind, EdgeKind::Data)
}

/// deadlocked-join: an AND-join with predecessors on exclusive branches, or on a cycle with a predecessor off it.
fn deadlocked_joins(wf: &Workflow, out: &mut Vec<Finding>) {
    let routing = succ_over(wf, is_routing_edge);
    for j in &wf.nodes {
        if !(j.attr(attr::ACTIVATION) == Some("all") || j.flag(attr::BARRIER_JOIN)) {
            continue;
        }
        let preds: BTreeSet<&str> =
            wf.edges.iter().filter(|e| e.to.node == j.id && joins_on(e)).map(|e| e.from.node.as_str()).collect();
        if preds.len() < 2 {
            continue;
        }
        let gates: Vec<(&str, &str)> = preds.iter().filter_map(|p| gating_branch(wf, p)).collect();
        let exclusive_router = gates
            .iter()
            .enumerate()
            .find(|&(i, &(r1, t1))| gates[i + 1..].iter().any(|&(r2, t2)| r1 == r2 && t1 != t2))
            .map(|(_, &(r, _))| r);
        let why = if let Some(r) = exclusive_router {
            Some(format!("its predecessors lie on mutually exclusive branches of router `{r}`"))
        } else if reaches(&routing, &j.id, &j.id) {
            let outside: Vec<&str> = preds
                .iter()
                .copied()
                .filter(|&p| !(reaches(&routing, &j.id, p) && reaches(&routing, p, &j.id)))
                .collect();
            (!outside.is_empty()).then(|| {
                format!("it lies on a cycle and its predecessor(s) {outside:?} outside the cycle complete only once")
            })
        } else {
            None
        };
        if let Some(why) = why {
            out.push(Finding::new(
                NAME,
                "deadlocked-join",
                &j.id,
                format!("join `{}` waits for all its predecessors, but {why}; it can never run", j.id),
            ));
        }
    }
}

/// loop-seeded-from-own-cycle: a mandatory input of a loop step whose producers all lie on the loop's own cycle.
fn loops_seeded_from_their_own_cycle(wf: &Workflow, out: &mut Vec<Finding>) {
    let succ = succ_map(wf);
    let comps = sccs(wf, &succ);
    for l in wf.nodes.iter().filter(|n| matches!(n.kind, NodeKind::Loop)) {
        let Some(cycle) = comps.iter().find(|c| c.contains(&l.id.as_str())).filter(|c| c.len() >= 2) else { continue };
        for s in l.inputs.iter().filter(|s| s.mandatory) {
            let producers: Vec<&str> = wf.edges_into(&l.id, &s.name).map(|e| e.from.node.as_str()).collect();
            if !producers.is_empty() && producers.iter().all(|p| cycle.contains(p)) {
                out.push(Finding::new(
                    NAME,
                    "loop-seeded-from-own-cycle",
                    format!("{}.{}", l.id, s.name),
                    format!(
                        "input `{}` of loop `{}` is produced only inside the loop's own cycle ({producers:?}); the loop can never start",
                        s.name, l.id
                    ),
                ));
            }
        }
    }
}

/// unreachable-node (bulk-synchronous model): a step that no path from an entry reaches.
fn unreachable_steps(wf: &Workflow, entered_from_outside: &BTreeSet<&str>, out: &mut Vec<Finding>) {
    let succ = succ_map(wf);
    let mut roots: BTreeSet<&str> = wf.start_nodes.iter().map(String::as_str).collect();
    roots.extend(wf.edges.iter().filter(|e| e.from.node == START).map(|e| e.to.node.as_str()));
    roots.extend(entered_from_outside.iter().copied());
    if roots.is_empty() {
        return;
    }
    for n in wf.nodes.iter().filter(|n| n.id != START && n.id != END) {
        if !roots.contains(n.id.as_str()) && !roots.iter().any(|r| reaches(&succ, r, &n.id)) {
            out.push(Finding::new(
                NAME,
                "unreachable-node",
                &n.id,
                format!(
                    "step `{}` is unreachable from the entry: no edge or route leads to it, so it never runs",
                    n.id
                ),
            ));
        }
    }
}
