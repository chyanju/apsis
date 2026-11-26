//! `subflow-port-binding` (β10 unwired-subflow-input): something a sub-workflow needs from its parent is not
//! bound across the boundary.

use crate::graph::{reaches, succ_map};
use crate::{Detector, Finding};
use apsis_ir::{attr, EdgeKind, ExecutionModel, Node, NodeKind, Program, SubflowRef, Workflow};

const NAME: &str = "subflow-port-binding";

pub struct SubflowPortBinding;

impl Detector for SubflowPortBinding {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, _wf: &Workflow) -> Vec<Finding> {
        Vec::new()
    }

    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        let mut out = Vec::new();
        for wf in &prog.workflows {
            for host in &wf.nodes {
                let Some(sr) = &host.subflow_ref else { continue };
                let Some(sub) = prog.workflow(&sr.workflow) else { continue };
                match wf.execution_model {
                    ExecutionModel::VisualDataflow => unbound_input(wf, host, sr, sub, &mut out),
                    ExecutionModel::GroupChatSpeaker => unbridged_shared_state(wf, host, sr, sub, &mut out),
                    ExecutionModel::BspSuperstep => unbridged_channel(host, sr, sub, &mut out),
                    _ => {}
                }
                unanswered_requests(host, sr, sub, &mut out);
                unbound_outputs(host, sr, sub, &mut out);
            }
        }
        out
    }
}

/// unbound-subflow-output: an out-binding names an inner step or output the sub-workflow does not have.
fn unbound_outputs(host: &Node, sr: &SubflowRef, sub: &Workflow, out: &mut Vec<Finding>) {
    for b in &sr.out_bindings {
        let (node, socket) = (&b.inner.node, &b.inner.socket);
        if node == apsis_ir::START || node == apsis_ir::END || socket.is_empty() {
            continue;
        }
        let missing = match sub.node(node) {
            None => true,
            Some(n) => !n.outputs.is_empty() && n.output(socket).is_none(),
        };
        if missing {
            out.push(Finding::new(
                NAME,
                "unbound-subflow-output",
                format!("{}.{}", host.id, b.outer.socket),
                format!(
                    "output `{}` of `{}` reads output `{socket}` of `{node}` in `{}`, which `{node}` does not produce",
                    b.outer.socket, host.id, sr.workflow
                ),
            ));
        }
    }
}

/// unbound-subflow-input (visual model): a sub-flow bound as a tool declares an input and the host binds none.
fn unbound_input(wf: &Workflow, host: &Node, sr: &SubflowRef, sub: &Workflow, out: &mut Vec<Finding>) {
    let declares_input = !sub.start_nodes.is_empty() || sub.nodes.iter().any(|n| matches!(n.kind, NodeKind::Start));
    let bound_as_tool = wf.edges.iter().any(|e| e.from.node == host.id && matches!(e.kind, EdgeKind::Tool));
    if declares_input && bound_as_tool && sr.in_bindings.is_empty() {
        out.push(Finding::new(
            NAME,
            "unbound-subflow-input",
            &host.id,
            format!("`{}` is bound as a tool and embeds `{}`, which declares an input, but binds none; the input cannot be supplied", host.id, sr.workflow),
        ));
    }
}

/// unanswered-subflow-request: an inner request that no parent step answers and the host does not pass on.
fn unanswered_requests(host: &Node, sr: &SubflowRef, sub: &Workflow, out: &mut Vec<Finding>) {
    if host.flag(attr::PROPAGATES_REQUESTS) {
        return;
    }
    for port in sub.nodes.iter().filter(|p| p.flag(attr::REQUEST_PORT)) {
        if !sr.in_bindings.iter().any(|b| b.inner.node == port.id) {
            out.push(Finding::new(
                NAME,
                "unanswered-subflow-request",
                &host.id,
                format!(
                    "`{}` embeds `{}`, whose step `{}` issues a request and waits for the answer, but no step of the parent is bound to answer it",
                    host.id, sr.workflow, port.id
                ),
            ));
        }
    }
}

/// unbridged-shared-state (group-chat model): an unbridged key the parent writes and the sub-workflow reads first.
fn unbridged_shared_state(wf: &Workflow, host: &Node, sr: &SubflowRef, sub: &Workflow, out: &mut Vec<Finding>) {
    let written_in_parent = |key: &str| wf.channels.iter().any(|c| c.name == key && !c.writers.is_empty());
    let bridged = |key: &str| sr.in_bindings.iter().any(|b| b.inner.socket == key);
    let reads_first = |step: &str, key: &str| {
        sub.node(step)
            .and_then(|n| n.attr(attr::READS_BEFORE_WRITE))
            .is_some_and(|channels| channels.split(',').any(|c| c.trim() == key))
    };
    let unwritten_before_read = |c: &&apsis_ir::Channel| c.writers.iter().all(|w| reads_first(w, &c.name));
    for c in sub.channels.iter().filter(|c| !c.readers.is_empty()).filter(unwritten_before_read) {
        if written_in_parent(&c.name) && !bridged(&c.name) {
            out.push(Finding::new(
                NAME,
                "unbridged-shared-state",
                &host.id,
                format!("`{}` embeds a sub-workflow that reads shared-state key `{}`, which only the parent writes and `{}` does not bridge", host.id, c.name, host.id),
            ));
        }
    }
}

/// unbridged-shared-state (bulk-synchronous model): an inner read no inner write precedes, not handed over.
fn unbridged_channel(host: &Node, sr: &SubflowRef, sub: &Workflow, out: &mut Vec<Finding>) {
    if sub.attrs.get(attr::KEEPS_STATE).map(String::as_str) == Some("true") {
        return;
    }
    let succ = succ_map(sub);
    let handed_over = |key: &str| sr.in_bindings.iter().any(|b| b.inner.socket == key);
    for c in sub.channels.iter().filter(|c| !handed_over(&c.name)) {
        let unwritten: Vec<&str> = c
            .readers
            .iter()
            .filter(|r| !c.writers.iter().any(|w| reaches(&succ, w, r)))
            .map(String::as_str)
            .collect();
        if let Some(reader) = unwritten.first() {
            out.push(Finding::new(
                NAME,
                "unbridged-shared-state",
                &host.id,
                format!(
                    "`{}` embeds `{}`, whose step `{reader}` reads channel `{}` before any write of the sub-workflow; `{}` does not hand it over, so it is empty on every run of the sub-workflow",
                    host.id, sr.workflow, c.name, host.id
                ),
            ));
        }
    }
}
