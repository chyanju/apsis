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
    // one step of one graph in several of its runs: the runs hold its objects by construction
    fn run_of(w: &Workflow) -> Option<&str> {
        w.attrs.get(attr::RUN_OF).map(String::as_str)
    }
    let one_step_of_one_graph = |steps: &[(&Workflow, &str)]| {
        run_of(steps[0].0).is_some() && steps.iter().all(|(w, s)| run_of(w) == run_of(steps[0].0) && *s == steps[0].1)
    };
    for steps in holders.values().filter(|steps| steps.len() > 1 && !one_step_of_one_graph(steps)) {
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

    // shared-object-mutation: steps change an object that outlives the run: module-level, built with the workflow,
    // or handed over by the run that started it.
    let mut changed: BTreeMap<&str, Vec<(&Workflow, &str, &str, &str)>> = BTreeMap::new();
    for wf in workflows {
        for n in &wf.nodes {
            for item in n.attr(attr::MUTATES).into_iter().flat_map(|v| v.split(',')) {
                let Some((path, object)) = item.split_once(':') else { continue };
                let Some((kind, identity)) = object.rsplit_once('@') else { continue };
                changed.entry(identity).or_default().push((wf, &n.id, path, kind));
            }
        }
    }
    for uses in changed.values() {
        let mut steps: Vec<String> = Vec::new();
        for (wf, step, _, _) in uses {
            let name = wf.id.as_ref().map_or_else(|| step.to_string(), |id| format!("{id}::{step}"));
            if !steps.contains(&name) {
                steps.push(name);
            }
        }
        let paths: Vec<&str> = uses.iter().map(|u| u.2).collect::<std::collections::BTreeSet<_>>().into_iter().collect();
        let (_, step, path, kind) = uses[0];
        let root = path.split(['.', '[']).next().unwrap_or(path);
        out.push(Finding::new(
            NAME,
            "shared-object-mutation",
            format!("{step}:{root}"),
            format!(
                "steps {steps:?} change {paths:?} of one `{kind}` object that outlives the run (module-level, built with the workflow, or handed over by the run that started it); every run shares it, so concurrent runs overwrite each other's changes and what a run leaves stays for the next"
            ),
        ));
    }

    // shared-container: steps of separately built workflows read one dict, list or set from the objects they belong to.
    let mut containers: BTreeMap<&str, Vec<(&Workflow, &str, &str)>> = BTreeMap::new();
    for wf in workflows {
        for n in &wf.nodes {
            for item in n.attr(attr::HOLDS).into_iter().flat_map(|v| v.split(',')) {
                let Some((what, identity)) = item.rsplit_once('@') else { continue };
                containers.entry(identity).or_default().push((wf, &n.id, what));
            }
        }
    }
    for uses in containers.values() {
        let builds: std::collections::BTreeSet<Option<&str>> = uses.iter().map(|(wf, _, _)| wf.id.as_deref()).collect();
        if builds.len() < 2 {
            continue;
        }
        let steps: Vec<String> =
            uses.iter().map(|(wf, step, _)| format!("{}::{step}", wf.id.as_deref().unwrap_or("main"))).collect();
        let (_, step, what) = uses[0];
        let (field, kind) = what.split_once(':').unwrap_or((what, "object"));
        out.push(Finding::new(
            NAME,
            "shared-container",
            format!("{step}:{field}"),
            format!(
                "steps {steps:?} of separately built workflows read one `{kind}` `{field}`; a change a run makes to it, or to a value inside it, reaches every other workflow built the same way"
            ),
        ));
    }

    // shared-store: workflows that serve separate runs keep one long-term store.
    let mut stores: BTreeMap<&str, Vec<&Workflow>> = BTreeMap::new();
    for wf in workflows {
        if let Some((_, identity)) = wf.attrs.get(attr::STORE).and_then(|v| v.rsplit_once('@')) {
            stores.entry(identity).or_default().push(wf);
        }
    }
    for runs in stores.values().filter(|runs| runs.len() > 1) {
        let ids: Vec<&str> = runs.iter().map(|w| w.id.as_deref().unwrap_or("main")).collect();
        let kind = runs[0].attrs.get(attr::STORE).and_then(|v| v.rsplit_once('@')).map_or("store", |(k, _)| k);
        out.push(Finding::new(
            NAME,
            "shared-store",
            format!("{}:store", ids[0]),
            format!(
                "workflows {ids:?} serve separate runs and keep one long-term store (`{kind}`); what one run writes to it, every other run reads"
            ),
        ));
    }

    // shared-checkpoint: runs of differently shaped workflows resume from one checkpoint.
    let mut checkpoints: BTreeMap<&str, Vec<&Workflow>> = BTreeMap::new();
    for wf in workflows {
        if let Some(checkpoint) = wf.attrs.get(attr::CHECKPOINT) {
            checkpoints.entry(checkpoint.as_str()).or_default().push(wf);
        }
    }
    let steps = |w: &Workflow| -> std::collections::BTreeSet<String> {
        w.nodes.iter().map(|n| n.id.clone()).filter(|id| !id.starts_with("__")).collect()
    };
    for (checkpoint, runs) in &checkpoints {
        let first = steps(runs[0]);
        let Some(other) = runs[1..].iter().find(|w| steps(w) != first) else { continue };
        let theirs = steps(other);
        let (a, b) = (runs[0].id.as_deref().unwrap_or("main"), other.id.as_deref().unwrap_or("main"));
        let only_a: Vec<&String> = first.difference(&theirs).collect();
        let only_b: Vec<&String> = theirs.difference(&first).collect();
        let (saver, thread) = checkpoint.rsplit_once('#').unwrap_or((checkpoint, ""));
        out.push(Finding::new(
            NAME,
            "shared-checkpoint",
            format!("{a}:checkpoint"),
            format!(
                "workflows `{a}` and `{b}` resume from one checkpoint (thread `{thread}` of `{saver}`) but have different steps (only in `{a}`: {only_a:?}; only in `{b}`: {only_b:?}); a run continues from the state and the next steps the other saved"
            ),
        ));
    }

    // config-blind-tool: runs configured with different values share a tool that reads no run config and calls a
    // service with arguments fixed when it was built.
    let configured: Vec<&Workflow> = workflows.iter().copied().filter(|w| w.attrs.contains_key(attr::RUN_CONFIG)).collect();
    let values = |w: &Workflow| -> BTreeMap<String, String> {
        w.attrs[attr::RUN_CONFIG]
            .split(',')
            .filter_map(|kv| kv.split_once('='))
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    };
    let differing: std::collections::BTreeSet<String> = configured
        .iter()
        .flat_map(|w| values(w).into_keys())
        .filter(|k| configured.iter().map(|w| values(w).get(k).cloned()).collect::<std::collections::BTreeSet<_>>().len() > 1)
        .collect();
    if !differing.is_empty() {
        let ids: Vec<&str> = configured.iter().map(|w| w.id.as_deref().unwrap_or("main")).collect();
        let mut tools: BTreeMap<(&str, &str), Vec<&str>> = BTreeMap::new();
        for wf in &configured {
            for n in &wf.nodes {
                for item in n.attr(attr::FIXED_CALLS).into_iter().flat_map(|v| v.split(',')) {
                    if let Some((tool, call)) = item.split_once(':') {
                        let calls = tools.entry((n.id.as_str(), tool)).or_default();
                        if !calls.contains(&call) {
                            calls.push(call);
                        }
                    }
                }
            }
        }
        for ((step, tool), calls) in tools {
            out.push(Finding::new(
                NAME,
                "config-blind-tool",
                format!("{step}:{tool}"),
                format!(
                    "runs {ids:?} are configured with different {differing:?}, and tool `{tool}` reads no run config: it calls {calls:?} with values fixed when it was built, so every run reads and writes the same"
                ),
            ));
        }
    }

    // shared-resume-slot: a step resumes the run whose thread id a field of a long-lived object holds, and a step
    // that starts runs sets that field.
    for wf in workflows {
        let setters: Vec<(&str, &str)> = wf
            .nodes
            .iter()
            .filter(|n| n.flag(attr::STARTS_RUNS))
            .flat_map(|n| n.attr(attr::SETS).into_iter().flat_map(|v| v.split(',')).map(move |item| (n.id.as_str(), item)))
            .collect();
        for n in &wf.nodes {
            for item in n.attr(attr::RESUME_THREAD).into_iter().flat_map(|v| v.split(',')) {
                let starters: Vec<&str> = setters.iter().filter(|(_, s)| *s == item).map(|(id, _)| *id).collect();
                if starters.is_empty() {
                    continue;
                }
                let (field, object) = item.split_once(':').unwrap_or((item, ""));
                let kind = object.rsplit_once('@').map_or(object, |(k, _)| k);
                out.push(Finding::new(
                    NAME,
                    "shared-resume-slot",
                    format!("{}:{field}", n.id),
                    format!(
                        "`{}` resumes the run whose thread id the field `{field}` of the one `{kind}` object holds, and {starters:?} set that field each time they start a run; with several runs waiting, an answer resumes the run started last",
                        n.id
                    ),
                ));
            }
        }
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
