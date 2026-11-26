//! `channel-write-merge` (β7 racing-channel-write): a channel updated in a way its merge rule cannot reconcile.

use crate::graph::{
    cross_graph_fanout, distances, fanout_succ_map, may_run_together, parallel_siblings, reaches, same_superstep, succ_map,
    unordered,
};
use crate::types::{is_list, is_message_list, nullable};
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
    single_pass_writes(wf, &mut out);
    if matches!(wf.execution_model, ExecutionModel::BspSuperstep) {
        fan_ins_without_barrier(wf, cross_fanout, &mut out);
    }
    out
}

fn channel_writes(wf: &Workflow, out: &mut Vec<Finding>) {
    let succ = succ_map(wf);
    let bsp = matches!(wf.execution_model, ExecutionModel::BspSuperstep);
    let together = if bsp { same_superstep(wf) } else { BTreeSet::new() };
    for ch in &wf.channels {
        // message-list-concatenation (LangGraph): a message list merged by list concatenation, not `add_messages`.
        if wf.framework == "langgraph" && ch.reducer == Reducer::Append && is_message_list(&ch.type_repr) {
            out.push(Finding::new(
                NAME,
                "message-list-concatenation",
                &ch.name,
                format!(
                    "channel `{}` holds chat messages but merges writes by list concatenation, not by message id (`add_messages`): a message written again with its id is added as a copy, and a removal is stored as a message instead of removing one",
                    ch.name
                ),
            ));
        }
        if !matches!(ch.reducer, Reducer::LastValue | Reducer::Overwrite) {
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
        // concurrent-last-value-writes: no reducer, and two unordered writers one pass may run together (a may
        // relation) or a fan-out writer.
        let writers: BTreeSet<&str> = ch.writers.iter().map(String::as_str).collect();
        let ws: Vec<&str> = writers.iter().copied().collect();
        let unordered_pair = ws.iter().enumerate().any(|(i, &a)| {
            ws[i + 1..].iter().any(|&b| {
                (unordered(&succ, a, b) && may_run_together(wf, &succ, a, b))
                    || together.contains(&if a < b { (a, b) } else { (b, a) })
            })
        });
        let repeats = |n: &apsis_ir::Node| {
            n.flag(attr::FANOUT) || n.attr(attr::REPEATED_WRITES).is_some_and(|v| v.split(',').any(|c| c == ch.name))
        };
        let fanout_writer = ws.iter().any(|w| wf.node(w).is_some_and(repeats));
        // accumulated-channel-overwrite: no reducer, steps keep a list by writing it back extended, and a step
        // that runs after one of them writes new content without the list.
        if is_list(&ch.type_repr) {
            let lists = |w: &str, key: &str| {
                wf.node(w).and_then(|n| n.attr(key)).is_some_and(|v| v.split(',').any(|c| c == ch.name))
            };
            let extenders: Vec<&str> = ws.iter().copied().filter(|w| lists(w, attr::EXTENDS)).collect();
            // accumulated-across-passes: a step on a cycle works on items another step of the cycle writes anew on
            // each pass, and keeps its results in a list it writes back extended, which no step of the cycle
            // writes anew.
            if bsp {
                let mut keepers: Vec<(&str, &str)> = Vec::new();
                for &a in extenders.iter().filter(|&&a| reaches(&succ, a, a)) {
                    let on_cycle = |c: &str| reaches(&succ, a, c) && reaches(&succ, c, a);
                    if ws.iter().any(|&b| on_cycle(b) && lists(b, attr::REPLACES)) {
                        continue;
                    }
                    let planned = wf.channels.iter().find(|p| {
                        p.name != ch.name
                            && p.readers.iter().any(|r| r == a)
                            && p.writers.iter().any(|b| b != a && on_cycle(b) && wf.node(b).and_then(|n| n.attr(attr::REPLACES)).is_some_and(|v| v.split(',').any(|c| c == p.name)))
                    });
                    if let Some(p) = planned {
                        keepers.push((a, p.name.as_str()));
                    }
                }
                if let Some(&(a, plan)) = keepers.first() {
                    let steps: Vec<&str> = keepers.iter().map(|k| k.0).collect();
                    out.push(Finding::new(
                        NAME,
                        "accumulated-across-passes",
                        format!("{a}.{}", ch.name),
                        format!(
                            "steps {steps:?} work on items their cycle writes anew on every pass (`{plan}` for `{a}`) and keep their results in `{}`, which they write back extended and no step of the cycle writes anew: the results of earlier passes stay next to those of the new items, and a later pass reads them as its own",
                            ch.name
                        ),
                    ));
                }
            }
            for &b in ws.iter().filter(|w| lists(w, attr::REPLACES)) {
                if extenders.iter().any(|&a| a != b && reaches(&succ, a, b)) {
                    out.push(Finding::new(
                        NAME,
                        "accumulated-channel-overwrite",
                        format!("{b}.{}", ch.name),
                        format!(
                            "channel `{}` has no reducer and steps {extenders:?} keep it by writing it back extended; step `{b}` writes new content without it, so what they added is lost",
                            ch.name
                        ),
                    ));
                }
            }
        }
        if unordered_pair || fanout_writer {
            let why = if unordered_pair {
                format!("{} writers {writers:?} that may run in one step", writers.len())
            } else {
                format!("a writer {writers:?} that writes it several times in one step (a fan-out, or once per tool call)")
            };
            let message = if ch.reducer == Reducer::Overwrite {
                format!("channel `{}` has a reducer that keeps only the last write of a step, and {why}; all but one of those writes are lost", ch.name)
            } else {
                format!("channel `{}` has no reducer and {why}; two writes in one step collide, or one is lost", ch.name)
            };
            out.push(Finding::new(NAME, "concurrent-last-value-writes", &ch.name, message));
        }
    }
}

/// single-pass-write: a step returns its update of a channel from inside a loop, after the loop's first item.
fn single_pass_writes(wf: &Workflow, out: &mut Vec<Finding>) {
    for n in &wf.nodes {
        for ch in n.attr(attr::SINGLE_PASS_WRITES).into_iter().flat_map(|v| v.split(',')) {
            out.push(Finding::new(
                NAME,
                "single-pass-write",
                format!("{}.{ch}", n.id),
                format!(
                    "step `{}` returns its update of channel `{ch}` from inside a loop, after the loop's first item: the items after the first never reach the channel",
                    n.id
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
        let pairs: Vec<(&str, &str)> = preds
            .iter()
            .enumerate()
            .flat_map(|(i, &a)| preds[i + 1..].iter().map(move |&b| (a, b)))
            .filter(|&(a, b)| unordered(&succ, a, b) && parallel_siblings(&succ, &fanout_succ, a, b))
            .collect();
        if let Some(&(p1, p2)) = pairs.iter().find(|(a, b)| dist.get(a) != dist.get(b)) {
            out.push(Finding::new(
                NAME,
                "fan-in-without-barrier",
                &n.id,
                format!(
                    "join `{}` is fed by the parallel branches `{p1}` and `{p2}` through separate edges and without a barrier; they reach it in different steps, so it runs once for each",
                    n.id
                ),
            ));
        } else if let Some(&(p1, p2)) = pairs.first() {
            // same-step-fan-in: the branches arrive together today, so the join runs once only while they keep pace.
            out.push(Finding::new(
                NAME,
                "same-step-fan-in",
                &n.id,
                format!(
                    "join `{}` is fed by the parallel branches `{p1}` and `{p2}` through separate edges and without a barrier; they reach it in the same step, so it runs once only while they take equally many steps, and once per arrival as soon as one takes longer",
                    n.id
                ),
            ));
        }
    }
}
