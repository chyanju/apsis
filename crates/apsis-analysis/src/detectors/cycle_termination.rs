//! `cycle-termination` (β2 runaway-loop): a cycle the workflow cannot leave.

use crate::graph::{is_cycle, reaches_or_eq, sccs, succ_over, Succ};
use crate::types::is_integer;
use crate::{Detector, Finding};
use apsis_ir::{attr, Edge, EdgeKind, ExecutionModel, Node, NodeKind, Workflow, END};
use std::collections::BTreeSet;

const NAME: &str = "cycle-termination";

pub struct CycleTermination;

impl Detector for CycleTermination {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        let visual = matches!(wf.execution_model, ExecutionModel::VisualDataflow);
        let group_chat = matches!(wf.execution_model, ExecutionModel::GroupChatSpeaker);
        // Group chat: handoff cycles end at run time, so only control, conditional and data edges are checked.
        let kinds =
            |e: &Edge| !group_chat || matches!(e.kind, EdgeKind::Control | EdgeKind::Conditional | EdgeKind::Data);
        // A possible edge may close a cycle but never shows a way out.
        let succ = succ_over(wf, kinds);
        let known = succ_over(wf, |e| kinds(e) && !e.possible);
        let mut comps: Vec<Vec<&str>> = sccs(wf, &succ).into_iter().filter(|c| is_cycle(c, &succ)).collect();
        for c in sccs(wf, &known).into_iter().filter(|c| is_cycle(c, &known)) {
            if !comps.iter().any(|d| d.iter().collect::<BTreeSet<_>>() == c.iter().collect::<BTreeSet<_>>()) {
                comps.push(c);
            }
        }
        let mut out = Vec::new();
        for comp in &comps {
            let members: Vec<&Node> = comp.iter().filter_map(|id| wf.node(id)).collect();
            let ids: BTreeSet<&str> = comp.iter().copied().collect();
            let bounded = if visual {
                // An exported flow has no iteration limit; only a structural loop node bounds a cycle.
                members.iter().any(|n| matches!(n.kind, NodeKind::Loop))
            } else {
                leaves(&ids, &known)
                    || members.iter().any(|n| routes_out(n, &ids) || yields_output(n))
                    || (!group_chat && members.iter().any(|n| breaks_out(wf, n, &ids)))
            };
            if !bounded {
                let unresolved = wf.edges.iter().any(|e| e.possible && ids.contains(e.from.node.as_str()));
                let why = if visual {
                    "no loop node bounds it, so the engine repeats it without a limit"
                } else if unresolved {
                    "no edge, route or output is known to lead out of it (a route that could not be resolved may stay inside), so it may end only at the engine's iteration limit"
                } else {
                    "no edge, route or output leads out of it, so it can end only at the engine's iteration limit"
                };
                out.push(Finding::new(
                    NAME,
                    "closed-cycle",
                    comp[0],
                    format!("steps {comp:?} form a closed cycle: {why}"),
                ));
            } else if !visual && !group_chat {
                out.extend(members.iter().filter(|n| reschedules_itself(wf, n) && !advances_a_counter(n)).map(|n| {
                    Finding::new(
                        NAME,
                        "self-loop-without-counter",
                        &n.id,
                        format!(
                            "step `{}` routes to itself and advances no integer counter, so nothing bounds the number of passes but the engine's iteration limit",
                            n.id
                        ),
                    )
                }));
            }
        }
        if !visual && !group_chat {
            bypassed_limits(wf, &succ, &mut out);
            counters_lost_on_rewrap(wf, &mut out);
        }
        out
    }
}

/// counter-reset-on-rewrap: a tool dispatches to objects that keep a counter on the instance, and re-wrapping one
/// with `with_config` gives an instance without the count.
fn counters_lost_on_rewrap(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in &wf.nodes {
        for item in n.attr(attr::REWRAP_RESETS).into_iter().flat_map(|v| v.split(',')) {
            let Some((tool, counter)) = item.split_once(':') else { continue };
            let (class, field) = counter.rsplit_once('.').unwrap_or(("object", counter));
            out.push(Finding::new(
                NAME,
                "counter-reset-on-rewrap",
                format!("{}:{tool}.{field}", n.id),
                format!(
                    "tool `{tool}` of step `{}` dispatches to `{class}` objects that count in `{field}` on the instance, and `with_config` builds a new instance without the count: a re-wrapped object counts from zero again, so a cap on the count is reached later or not at all",
                    n.id
                ),
            ));
        }
    }
}

/// loop-limit-bypassed: a routing function ends its cycle when a counter passes a bound, but returns targets on
/// the cycle ahead of that test.
fn bypassed_limits(wf: &Workflow, succ: &Succ, out: &mut Vec<Finding>) {
    let is_counter = |key: &str| wf.channels.iter().any(|c| c.name == key && is_integer(&c.type_repr));
    for r in &wf.nodes {
        for (branch, keys) in r.branch_attrs(attr::ROUTER_LIMIT) {
            let counters: Vec<&str> = keys.split(',').filter(|k| is_counter(k)).collect();
            let early = r.attr(&format!("{}{branch}", attr::ROUTER_BEFORE_LIMIT)).unwrap_or("");
            let staying: Vec<&str> =
                early.split(',').filter(|t| !t.is_empty() && reaches_or_eq(succ, t, &r.id)).collect();
            if !counters.is_empty() && !staying.is_empty() {
                out.push(Finding::new(
                    NAME,
                    "loop-limit-bypassed",
                    &r.id,
                    format!(
                        "the routing function of `{}` ends the loop when {counters:?} passes its bound, but returns {staying:?} ahead of that test; these routes stay on the cycle, so a run that keeps taking them ends only at the engine's iteration limit",
                        r.id
                    ),
                ));
            }
        }
    }
}

fn leaves(ids: &BTreeSet<&str>, succ: &Succ) -> bool {
    ids.iter().any(|c| succ.get(c).is_some_and(|ss| ss.iter().any(|s| !ids.contains(s))))
}

/// A declared routing target outside the cycle; `END` is a route out that is never an edge.
fn routes_out(n: &Node, ids: &BTreeSet<&str>) -> bool {
    n.declared_targets.iter().any(|t| t == END || !ids.contains(t.as_str()))
}

/// Yielding the workflow's output ends the run; unknown output types show no way out.
fn yields_output(n: &Node) -> bool {
    n.attr(attr::WORKFLOW_OUTPUT_TYPES).is_some_and(|types| !types.is_empty())
}

/// An output a run may omit that is not wired back into the cycle.
fn breaks_out(wf: &Workflow, n: &Node, ids: &BTreeSet<&str>) -> bool {
    n.outputs.iter().any(|o| {
        o.may_emit
            && !wf
                .edges
                .iter()
                .any(|e| e.from.node == n.id && e.from.socket == o.name && ids.contains(e.to.node.as_str()))
    })
}

/// The step names itself as a dynamic routing target, or may (a possible edge to itself).
fn reschedules_itself(wf: &Workflow, n: &Node) -> bool {
    let self_edge = |possible: bool| {
        wf.edges.iter().any(|e| {
            e.from.node == n.id && e.to.node == n.id && e.possible == possible && matches!(e.kind, EdgeKind::Handoff)
        })
    };
    (n.declared_targets.contains(&n.id) && self_edge(false)) || self_edge(true)
}

/// The step advances an integer channel, a counter a guard can bound; any integer output when steps are not tracked.
fn advances_a_counter(n: &Node) -> bool {
    let stepped: Option<Vec<&str>> = n.attr(attr::COUNTERS).map(|v| v.split(',').collect());
    n.outputs
        .iter()
        .any(|o| is_integer(&o.type_repr) && stepped.as_ref().is_none_or(|s| s.contains(&o.name.as_str())))
}
