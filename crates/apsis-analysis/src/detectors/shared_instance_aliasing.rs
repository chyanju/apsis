//! `shared-instance-aliasing` (β8 aliased-instance): one mutable object held by two steps.

use crate::{Detector, Finding};
use apsis_ir::{attr, Program, Workflow};
use std::collections::BTreeMap;

const NAME: &str = "shared-instance-aliasing";

pub struct SharedInstanceAliasing;

impl Detector for SharedInstanceAliasing {
    fn name(&self) -> &'static str {
        NAME
    }

    fn check(&self, wf: &Workflow) -> Vec<Finding> {
        check(&[wf])
    }

    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        check(&prog.workflows.iter().collect::<Vec<_>>())
    }
}

fn check(workflows: &[&Workflow]) -> Vec<Finding> {
    let mut out = Vec::new();

    // shared-instance: two steps with the same object identity, in one workflow or across the program.
    let mut holders: BTreeMap<&str, Vec<(&Workflow, &str)>> = BTreeMap::new();
    for wf in workflows {
        for n in &wf.nodes {
            if let Some(instance) = &n.instance_id {
                holders.entry(instance).or_default().push((wf, &n.id));
            }
        }
    }
    for steps in holders.values().filter(|steps| steps.len() > 1) {
        let names: Vec<String> = steps
            .iter()
            .map(|(wf, step)| match &wf.id {
                Some(id) => format!("{id}::{step}"),
                None => step.to_string(),
            })
            .collect();
        let across = steps.iter().any(|(wf, _)| wf.id != steps[0].0.id);
        let scope = if across { "across workflows" } else { "in one workflow" };
        out.push(Finding::new(
            NAME,
            "shared-instance",
            steps[0].1,
            format!("steps {names:?} are one object instance ({scope}); state it keeps is shared between them"),
        ));
    }

    // shared-workflow-instance: every caller gets the same workflow object, which one run owns at a time.
    for wf in workflows.iter().filter(|w| w.attrs.get(attr::SHARED_WORKFLOW).is_some_and(|v| v == "true")) {
        let id = wf.id.as_deref().unwrap_or("main");
        out.push(Finding::new(
            NAME,
            "shared-workflow-instance",
            id,
            format!("every caller gets the one workflow object `{id}`; a run owns it, so a run that starts while another is in progress fails"),
        ));
    }

    // shared-subworkflow-instance: two steps of one workflow embed the same sub-workflow object.
    for wf in workflows {
        let mut embedders: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
        for n in &wf.nodes {
            if let Some(sr) = &n.subflow_ref {
                embedders.entry(&sr.workflow).or_default().push(&n.id);
            }
        }
        for steps in embedders.values().filter(|steps| steps.len() > 1) {
            out.push(Finding::new(
                NAME,
                "shared-subworkflow-instance",
                steps[0],
                format!("steps {steps:?} embed one sub-workflow instance; state it keeps is shared between them"),
            ));
        }
    }
    out
}
