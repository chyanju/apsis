//! `channel-write-merge` (β7 racing-channel-write): a channel updated in a way its merge rule cannot reconcile.

use crate::graph::{cross_graph_fanout, distances, fanout_succ_map, parallel_siblings, succ_map, unordered};
use crate::types::nullable;
use crate::{Detector, Finding};
use apsis_ir::{attr, EdgeKind, ExecutionModel, Program, Reducer, Workflow, START};
use std::collections::BTreeSet;

const NAME: &str = "channel-write-merge";

pub struct ChannelWriteMerge;

impl Detector for ChannelWriteMerge {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        check(wf, &[])
    }

    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        prog.workflows.iter().flat_map(|w| check(w, &cross_graph_fanout(prog, w))).collect()
    }
}

/// `cross_fanout`: see `cross_graph_fanout`.
fn check(wf: &Workflow, cross_fanout: &[(&str, &str)]) -> Vec<Finding> {
    let mut out = Vec::new();
    channel_writes(wf, &mut out);
    full_state_overwrites(wf, &mut out);
    if matches!(wf.execution_model, ExecutionModel::BspSuperstep) {
        fan_ins_without_barrier(wf, cross_fanout, &mut out);
    }
    out
}

fn channel_writes(wf: &Workflow, out: &mut Vec<Finding>) {
    let succ = succ_map(wf);
    for ch in &wf.channels {
        if ch.reducer != Reducer::LastValue {
            // nullable-reducer-channel: a channel with a reducer whose declared type admits none.
            if nullable(&ch.type_repr) {
                out.push(Finding::new(
                    NAME,
                    "nullable-reducer-channel",
                    &ch.name,
                    format!("channel `{}` has a reducer and the nullable type `{}`: the first write is reduced against a none value", ch.name, ch.type_repr),
                ));
            }
            continue;
        }
        // concurrent-last-value-writes: no reducer, and two unordered writers (a may relation) or a fan-out writer.
        let writers: BTreeSet<&str> = ch.writers.iter().map(String::as_str).collect();
        let ws: Vec<&str> = writers.iter().copied().collect();
        let unordered_pair = ws.iter().enumerate().any(|(i, &a)| ws[i + 1..].iter().any(|&b| unordered(&succ, a, b)));
        let fanout_writer = ws.iter().any(|w| wf.node(w).is_some_and(|n| n.flag(attr::FANOUT)));
        if unordered_pair || fanout_writer {
            let why = if unordered_pair {
                format!("{} writers {writers:?} that are not ordered by the graph", writers.len())
            } else {
                format!("a writer {writers:?} that runs as concurrent instances of a fan-out")
            };
            out.push(Finding::new(
                NAME,
                "concurrent-last-value-writes",
                &ch.name,
                format!(
                    "channel `{}` has no reducer and {why}; two writes in one step collide, or one is lost",
                    ch.name
                ),
            ));
        }
    }
}

/// full-state-overwrite: a step replaces the whole state while the workflow has two or more channels.
fn full_state_overwrites(wf: &Workflow, out: &mut Vec<Finding>) {
    if wf.channels.len() < 2 {
        return;
    }
    for n in wf.nodes.iter().filter(|n| n.flag(attr::FULL_STATE_UPDATE)) {
        out.push(Finding::new(
            NAME,
            "full-state-overwrite",
            &n.id,
            format!(
                "step `{}` replaces the whole state; the channels it does not set are reset, discarding other writes",
                n.id
            ),
        ));
    }
}

/// fan-in-without-barrier (bulk-synchronous model): a join fed by parallel branches of unequal depth, no barrier.
fn fan_ins_without_barrier(wf: &Workflow, cross_fanout: &[(&str, &str)], out: &mut Vec<Finding>) {
    let succ = succ_map(wf);
    let mut fanout_succ = fanout_succ_map(wf);
    let mut depth_succ = succ.clone();
    for &(n, t) in cross_fanout {
        fanout_succ.entry(n).or_default().push(t);
        depth_succ.entry(n).or_default().push(t);
    }
    let starts: Vec<&str> = if wf.node(START).is_some() {
        vec![START]
    } else if !wf.start_nodes.is_empty() {
        wf.start_nodes.iter().map(String::as_str).collect()
    } else {
        wf.edges.iter().filter(|e| e.from.node == START).map(|e| e.to.node.as_str()).collect()
    };
    let dist = distances(&depth_succ, &starts);

    for n in wf.nodes.iter().filter(|n| !n.flag(attr::BARRIER_JOIN)) {
        let preds: Vec<&str> = wf
            .edges
            .iter()
            .filter(|e| e.to.node == n.id && matches!(e.kind, EdgeKind::Control))
            .map(|e| e.from.node.as_str())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        let pair = preds.iter().enumerate().find_map(|(i, &a)| {
            preds[i + 1..]
                .iter()
                .copied()
                .find(|&b| {
                    unordered(&succ, a, b) && parallel_siblings(&succ, &fanout_succ, a, b) && dist.get(a) != dist.get(b)
                })
                .map(|b| (a, b))
        });
        if let Some((p1, p2)) = pair {
            out.push(Finding::new(
                NAME,
                "fan-in-without-barrier",
                &n.id,
                format!(
                    "join `{}` is fed by the parallel branches `{p1}` and `{p2}` through separate edges and without a barrier; they reach it in different steps, so it runs once for each",
                    n.id
                ),
            ));
        }
    }
}
