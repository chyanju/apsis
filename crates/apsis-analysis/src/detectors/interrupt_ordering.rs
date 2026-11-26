//! `interrupt-ordering` (β12 ungated-interrupt): a human-in-the-loop step that blocks the flow at the wrong point.

use crate::graph::{reaches, succ_map};
use crate::{Detector, Finding};
use apsis_ir::{ExecutionModel, Node, NodeKind, Workflow};

const NAME: &str = "interrupt-ordering";

pub struct InterruptOrdering;

impl Detector for InterruptOrdering {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        if !matches!(wf.execution_model, ExecutionModel::VisualDataflow) {
            return Vec::new();
        }
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
}
