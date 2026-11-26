//! `dangling-output` (β6 dead-end-branch): a branch, or a whole workflow, whose result reaches no output.

use crate::graph::{reaches_any, succ_map};
use crate::{Detector, Finding};
use apsis_ir::{attr, ExecutionModel, NodeKind, Workflow};
use std::collections::BTreeSet;

const NAME: &str = "dangling-output";

pub struct DanglingOutput;

impl Detector for DanglingOutput {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        let mut out = Vec::new();
        outputs_without_type(wf, &mut out);
        if matches!(wf.execution_model, ExecutionModel::VisualDataflow) {
            dead_end_branches(wf, &mut out);
        }
        out
    }
}

/// output-without-type: every output step carries `workflow_output_types`, and none lists a type.
fn outputs_without_type(wf: &Workflow, out: &mut Vec<Finding>) {
    let declared: Vec<&str> =
        wf.output_nodes.iter().filter_map(|o| wf.node(o).and_then(|n| n.attr(attr::WORKFLOW_OUTPUT_TYPES))).collect();
    let known_for_all = !wf.output_nodes.is_empty() && declared.len() == wf.output_nodes.len();
    if known_for_all && declared.iter().all(|types| types.is_empty()) {
        out.push(Finding::new(
            NAME,
            "output-without-type",
            wf.output_nodes.join(","),
            format!(
                "the workflow designates output step(s) {:?}, but none declares a type it yields as workflow output",
                wf.output_nodes
            ),
        ));
    }
}

/// dead-end-branch (visual model): a router branch reaches no terminal while a sibling branch does.
fn dead_end_branches(wf: &Workflow, out: &mut Vec<Finding>) {
    let terminals: BTreeSet<&str> = wf
        .nodes
        .iter()
        .filter(|n| {
            matches!(n.kind, NodeKind::End | NodeKind::HumanInput | NodeKind::Subflow) || n.flag(attr::IMPLICIT_RETURN)
        })
        .map(|n| n.id.as_str())
        .chain(wf.output_nodes.iter().map(String::as_str))
        .collect();
    let succ = succ_map(wf);
    for r in wf.nodes.iter().filter(|n| matches!(n.kind, NodeKind::Router)) {
        let targets: BTreeSet<&str> =
            wf.edges.iter().filter(|e| e.from.node == r.id).map(|e| e.to.node.as_str()).collect();
        let dead: Vec<&str> = targets.iter().copied().filter(|t| !reaches_any(&succ, t, &terminals)).collect();
        if targets.len() < 2 || dead.is_empty() || dead.len() == targets.len() {
            continue;
        }
        for t in dead {
            out.push(Finding::new(
                NAME,
                "dead-end-branch",
                t,
                format!("branch `{t}` of router `{}` reaches no terminal while a sibling branch does; its result is discarded", r.id),
            ));
        }
    }
}
