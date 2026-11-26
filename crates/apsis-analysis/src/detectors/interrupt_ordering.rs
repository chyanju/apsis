//! `interrupt-ordering` (β12 ungated-interrupt): a human-in-the-loop step that blocks the flow at the wrong point.

use crate::graph::{reaches, succ_map};
use apsis_ir::EdgeKind;
use crate::{Detector, Finding};
use apsis_ir::{attr, ExecutionModel, Node, NodeKind, Workflow};

const NAME: &str = "interrupt-ordering";

pub struct InterruptOrdering;

impl Detector for InterruptOrdering {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        let mut found = shared_wait_keys(wf);
        found.extend(outputs_past_gates(wf));
        if !matches!(wf.execution_model, ExecutionModel::VisualDataflow) {
            return found;
        }
        found.extend(visual(wf));
        found
    }
}

/// shared-wait-key: concurrent instances of a step wait for input under one key, so one answer resumes one of them.
fn shared_wait_keys(wf: &Workflow) -> Vec<Finding> {
    wf.nodes
        .iter()
        .filter(|n| n.flag(attr::FANOUT) && n.attr(attr::WAIT_KEY) == Some("event"))
        .filter_map(|n| n.attr(attr::WAITS_FOR).map(|events| (n, events)))
        .map(|(n, events)| {
            Finding::new(
                NAME,
                "shared-wait-key",
                &n.id,
                format!(
                    "step `{}` runs as concurrent instances that each wait for {events} under a key derived from the event type alone; one answer resumes one of them, and the others wait until they time out",
                    n.id
                ),
            )
        })
        .collect()
}

/// output-bypasses-gate: a step on the loop a gate's branches close yields the workflow output itself, so what it
/// produces leaves without passing the gate.
fn outputs_past_gates(wf: &Workflow) -> Vec<Finding> {
    let succ = succ_map(wf);
    let gates: Vec<&str> = wf
        .nodes
        .iter()
        .map(|n| n.id.as_str())
        .filter(|g| wf.edges.iter().filter(|e| e.from.node == *g && matches!(e.kind, EdgeKind::Conditional)).count() > 1)
        .collect();
    let yields = |n: &Node| n.attr(attr::WORKFLOW_OUTPUT_TYPES).is_some_and(|t| !t.trim().is_empty());
    let mut out = Vec::new();
    for n in wf.nodes.iter().filter(|n| yields(n)) {
        if let Some(gate) = gates.iter().find(|&&g| g != n.id && reaches(&succ, g, &n.id) && reaches(&succ, &n.id, g)) {
            out.push(Finding::new(
                NAME,
                "output-bypasses-gate",
                &n.id,
                format!(
                    "step `{}` is on the loop that the branches of `{gate}` close, and yields the workflow output itself: what it produces leaves the workflow without passing `{gate}`",
                    n.id
                ),
            ));
        }
    }
    out
}

fn visual(wf: &Workflow) -> Vec<Finding> {
    let succ = succ_map(wf);
    let of_kind = |kind: NodeKind| wf.nodes.iter().filter(move |n| n.kind == kind);
    let interrupts: Vec<&Node> = of_kind(NodeKind::HumanInput).collect();
    let mut out = Vec::new();

    // serial-interrupts: one interrupt reaches another with no router between them.
    for h1 in &interrupts {
        for h2 in interrupts.iter().filter(|h2| h2.id != h1.id && reaches(&succ, &h1.id, &h2.id)) {
            let router_between =
                of_kind(NodeKind::Router).any(|r| reaches(&succ, &h1.id, &r.id) && reaches(&succ, &r.id, &h2.id));
            if !router_between {
                out.push(Finding::new(
                    NAME,
                    "serial-interrupts",
                    &h2.id,
                    format!("interrupt `{}` always follows interrupt `{}`, with no router between them; the flow blocks for input twice in a row", h2.id, h1.id),
                ));
            }
        }
    }

    // interrupt-before-agent: an interrupt reachable from the start with no agent upstream of it.
    let starts: Vec<&str> = if wf.start_nodes.is_empty() {
        of_kind(NodeKind::Start).map(|n| n.id.as_str()).collect()
    } else {
        wf.start_nodes.iter().map(String::as_str).collect()
    };
    for h in &interrupts {
        let from_start = starts.iter().any(|s| reaches(&succ, s, &h.id));
        let agent_upstream = of_kind(NodeKind::Agent).any(|a| reaches(&succ, &a.id, &h.id));
        if from_start && !agent_upstream {
            out.push(Finding::new(
                NAME,
                "interrupt-before-agent",
                &h.id,
                format!("interrupt `{}` is reached before any agent has run; it asks for input before the flow has done anything", h.id),
            ));
        }
    }
    out
}
