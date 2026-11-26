//! `router-branch-gating` (β5 ungated-branch-merge): a branch the router did not select still runs.

use crate::graph::{reachable_from, succ_over};
use crate::{Detector, Finding};
use apsis_ir::{attr, Edge, EdgeKind, Node, NodeKind, Workflow};
use std::collections::{BTreeMap, BTreeSet};

const NAME: &str = "router-branch-gating";

pub struct RouterBranchGating;

impl Detector for RouterBranchGating {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        let mut out = Vec::new();
        for r in &wf.nodes {
            let data_gate = r.attr(attr::BRANCH_OUTPUTS) == Some(attr::BRANCH_DATA_GATE);
            if !data_gate {
                branches_converge(wf, r, &mut out);
            }
            if !matches!(r.kind, NodeKind::Router) {
                continue;
            }
            if r.attr(attr::BRANCH_OUTPUTS) == Some(attr::BRANCH_TRANSITION) {
                cross_branch_paths(wf, r, &mut out);
            }
            if r.outputs.len() >= 2 {
                if data_gate {
                    skipped_branches(wf, r, &mut out);
                }
                ungated_branch_edges(wf, r, &mut out);
            }
        }
        out
    }
}

/// The targets of the out-edges of `r`, by branch label.
fn targets_by_branch<'a>(wf: &'a Workflow, r: &Node) -> BTreeMap<&'a str, BTreeSet<&'a str>> {
    let mut by_branch: BTreeMap<&str, BTreeSet<&str>> = BTreeMap::new();
    for e in wf.edges.iter().filter(|e| e.from.node == r.id) {
        if let Some(label) = e.branch.as_deref() {
            by_branch.entry(label).or_default().insert(e.to.node.as_str());
        }
    }
    by_branch
}

/// branches-converge: a step that is the direct target of two or more branches of `r`.
fn branches_converge(wf: &Workflow, r: &Node, out: &mut Vec<Finding>) {
    let by_branch = targets_by_branch(wf, r);
    if by_branch.len() < 2 {
        return;
    }
    let mut branches_into: BTreeMap<&str, usize> = BTreeMap::new();
    for t in by_branch.values().flatten() {
        *branches_into.entry(t).or_default() += 1;
    }
    for (t, count) in branches_into.into_iter().filter(|&(_, count)| count >= 2) {
        out.push(Finding::new(
            NAME,
            "branches-converge",
            t,
            format!("`{t}` is the target of {count} mutually exclusive branches of router `{}`, so it runs whichever branch is selected", r.id),
        ));
    }
}

/// cross-branch-path: the head of one exclusive branch reaches the head of another over unbranched edges.
fn cross_branch_paths(wf: &Workflow, r: &Node, out: &mut Vec<Finding>) {
    let by_branch = targets_by_branch(wf, r);
    if by_branch.len() < 2 {
        return;
    }
    let unbranched = succ_over(wf, |e| e.branch.is_none());
    for (bi, heads_i) in &by_branch {
        for (bj, heads_j) in by_branch.iter().filter(|(bj, _)| *bj != bi) {
            for hi in heads_i {
                let reached = reachable_from(&unbranched, hi);
                for hj in heads_j.iter().filter(|hj| *hj != hi && reached.contains(*hj)) {
                    out.push(Finding::new(
                        NAME,
                        "cross-branch-path",
                        *hj,
                        format!(
                            "`{hi}`, the head of branch `{bi}` of router `{}`, reaches `{hj}`, the head of branch `{bj}`: selecting `{bi}` also runs the `{bj}` branch",
                            r.id
                        ),
                    ));
                }
            }
        }
    }
}

/// skipped-branch: a data-gate router with one branch output wired and another left unwired.
fn skipped_branches(wf: &Workflow, r: &Node, out: &mut Vec<Finding>) {
    let wired = |socket: &str| wf.edges.iter().any(|e| e.from.node == r.id && e.from.socket == socket);
    if !r.outputs.iter().any(|o| wired(&o.name)) {
        return;
    }
    for o in r.outputs.iter().filter(|o| !wired(&o.name)) {
        out.push(Finding::new(
            NAME,
            "skipped-branch",
            format!("{}.{}", r.id, o.name),
            format!("branch output `{}.{}` is not connected while a sibling branch output is; its value is lost when the router selects it", r.id, o.name),
        ));
    }
}

fn is_ungated(e: &Edge) -> bool {
    matches!(e.kind, EdgeKind::Data) && e.from.socket.is_empty() && e.branch.is_none()
}

/// ungated-branch-edge: a router that gates one branch with a conditional edge and wires another as a data edge.
fn ungated_branch_edges(wf: &Workflow, r: &Node, out: &mut Vec<Finding>) {
    let from_r = || wf.edges.iter().filter(|e| e.from.node == r.id);
    if !from_r().any(|e| matches!(e.kind, EdgeKind::Conditional) && e.branch.is_some()) {
        return;
    }
    for e in from_r().filter(|e| is_ungated(e)) {
        out.push(Finding::new(
            NAME,
            "ungated-branch-edge",
            format!("{}->{}", r.id, e.to.node),
            format!("router `{}` reaches `{}` by a plain data edge instead of a branch, so `{}` runs whether or not it is selected", r.id, e.to.node, e.to.node),
        ));
    }
}
