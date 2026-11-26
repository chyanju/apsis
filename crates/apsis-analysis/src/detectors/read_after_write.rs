//! `read-after-write` (β9 stale-read): a read of shared state that no write is ordered before.

use crate::graph::{reaches, succ_map};
use crate::{Detector, Finding};
use apsis_ir::{attr, ExecutionModel, Program, Workflow};
use std::collections::BTreeSet;

const NAME: &str = "read-after-write";

pub struct ReadAfterWrite;

impl Detector for ReadAfterWrite {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        check(wf, &BTreeSet::new())
    }

    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        // A bulk-synchronous sub-workflow shares its parent's state; a step's outputs are the channels it writes.
        let written_bsp: BTreeSet<&str> = prog
            .workflows
            .iter()
            .filter(|w| matches!(w.execution_model, ExecutionModel::BspSuperstep))
            .flat_map(|w| {
                w.channels
                    .iter()
                    .filter(|c| !c.writers.is_empty())
                    .map(|c| c.name.as_str())
                    .chain(w.nodes.iter().flat_map(|n| n.outputs.iter().map(|o| o.name.as_str())))
            })
            .collect();
        prog.workflows.iter().flat_map(|w| check(w, &written_bsp)).collect()
    }
}

fn check(wf: &Workflow, written_bsp: &BTreeSet<&str>) -> Vec<Finding> {
    let mut out = Vec::new();

    // unordered-store-read: a step reads a store that another step writes, and no path orders the write first.
    let succ = succ_map(wf);
    let accessing = |writes: bool| {
        wf.nodes.iter().filter(move |n| {
            n.store_ref.is_some() && n.store_role.as_deref().is_some_and(|role| (role == "write") == writes)
        })
    };
    for r in accessing(false) {
        let unordered_writer = accessing(true).find(|w| w.store_ref == r.store_ref && !reaches(&succ, &w.id, &r.id));
        if let Some(w) = unordered_writer {
            out.push(Finding::new(
                NAME,
                "unordered-store-read",
                &r.id,
                format!(
                    "`{}` reads a store that `{}` writes, and no path orders the write before the read",
                    r.id, w.id
                ),
            ));
        }
    }

    // read-without-writer: a key that is read, written by no step and not in `provided_channels`.
    let bsp = matches!(wf.execution_model, ExecutionModel::BspSuperstep);
    if bsp || matches!(wf.execution_model, ExecutionModel::GroupChatSpeaker) {
        let provided: BTreeSet<&str> = wf
            .attrs
            .get(attr::PROVIDED_CHANNELS)
            .map(|v| v.split(',').map(str::trim).filter(|t| !t.is_empty()).collect())
            .unwrap_or_default();
        let unwritten = |name: &str| !(bsp && written_bsp.contains(name));
        for ch in wf.channels.iter().filter(|ch| {
            !ch.readers.is_empty() && ch.writers.is_empty() && !provided.contains(ch.name.as_str()) && unwritten(&ch.name)
        }) {
            out.push(Finding::new(
                NAME,
                "read-without-writer",
                &ch.name,
                format!(
                    "shared-state key `{}` is read by {:?}, and no step writes it and neither the run's input nor the engine provides it, so the read sees no value",
                    ch.name, ch.readers
                ),
            ));
        }
    }
    out
}
