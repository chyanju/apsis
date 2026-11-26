//! apsis-analysis — the detector catalog over the IR. A detector is a set of rules for one bug pattern; a rule
//! specific to one execution model is guarded by that model or by the facts it provides.

use apsis_ir::{attr, Edge, EdgeKind, Program, SocketRef, Workflow, END, START};

pub mod detectors;
mod graph;
mod types;

pub use detectors::*;

/// One match of a rule.
#[derive(Debug, Clone)]
pub struct Finding {
    pub detector: &'static str,
    pub rule: &'static str,
    /// The IR element held responsible: a step, a socket (`step.socket`), an edge (`a->b`) or a channel.
    pub location: String,
    pub message: String,
}

impl Finding {
    pub(crate) fn new(
        detector: &'static str,
        rule: &'static str,
        location: impl Into<String>,
        message: String,
    ) -> Self {
        Finding { detector, rule, location: location.into(), message }
    }
}

pub trait Detector {
    fn name(&self) -> &'static str;

    fn check(&self, wf: &Workflow) -> Vec<Finding>;

    /// Checks each workflow on its own; detectors with cross-workflow rules override it.
    fn check_program(&self, prog: &Program) -> Vec<Finding> {
        prog.workflows.iter().flat_map(|w| self.check(w)).collect()
    }
}

/// The catalog: the twelve detectors, in the order of the paper's categories.
pub fn detectors() -> Vec<Box<dyn Detector>> {
    vec![
        Box::new(ReadinessLiveness),
        Box::new(CycleTermination),
        Box::new(TypeContract),
        Box::new(TargetResolution),
        Box::new(RouterBranchGating),
        Box::new(DanglingOutput),
        Box::new(ChannelWriteMerge),
        Box::new(SharedInstanceAliasing),
        Box::new(ReadAfterWrite),
        Box::new(SubflowPortBinding),
        Box::new(BindingCapability),
        Box::new(InterruptOrdering),
    ]
}

/// Runs the catalog on [`over_approximate`] and on [`definite`] and keeps the findings of either: an unresolved
/// route can add a finding, never remove one. `cycle-termination` handles possible edges itself.
pub fn analyze(prog: &Program) -> Vec<Finding> {
    let over = over_approximate(prog);
    let definite = definite(&over);
    let mut seen = std::collections::BTreeSet::new();
    let mut out = Vec::new();
    for d in detectors() {
        let mut found = d.check_program(&over);
        if d.name() != "cycle-termination" {
            found.extend(d.check_program(&definite));
        }
        for f in found {
            if seen.insert((f.detector, f.rule, f.location.clone())) {
                out.push(f);
            }
        }
    }
    out
}

/// Marks unresolved routes as possible edges ([`Edge::possible`]): a `goto_unresolved` step may route anywhere.
/// A target that only the possible edges of an unresolved routing function reach is no longer declared.
pub fn over_approximate(prog: &Program) -> Program {
    let mut prog = prog.clone();
    for wf in &mut prog.workflows {
        let steps: Vec<String> = wf.nodes.iter().map(|n| n.id.clone()).filter(|id| id != START && id != END).collect();
        for n in &mut wf.nodes {
            let spelled_out: Vec<String> = n
                .branch_attrs(attr::ROUTER_UNRESOLVED)
                .filter(|(b, v)| *v == "true" && n.attr(&format!("{}{b}", attr::ROUTER_MAP)).is_none())
                .map(|(b, _)| b.to_string())
                .collect();
            if spelled_out.is_empty() {
                continue;
            }
            for e in wf.edges.iter_mut().filter(|e| e.from.node == n.id) {
                if e.branch.as_deref().is_some_and(|b| spelled_out.iter().any(|s| s == b)) {
                    e.possible = true;
                }
            }
            let known: std::collections::BTreeSet<&str> =
                wf.edges.iter().filter(|e| e.from.node == n.id && !e.possible).map(|e| e.to.node.as_str()).collect();
            let possible: std::collections::BTreeSet<&str> =
                wf.edges.iter().filter(|e| e.from.node == n.id && e.possible).map(|e| e.to.node.as_str()).collect();
            n.declared_targets.retain(|t| known.contains(t.as_str()) || !possible.contains(t.as_str()));
        }
        let mut edges: Vec<Edge> = Vec::new();
        for n in wf.nodes.iter().filter(|n| n.flag(attr::GOTO_UNRESOLVED)) {
            for t in &steps {
                edges.push(Edge {
                    from: SocketRef { node: n.id.clone(), socket: String::new() },
                    to: SocketRef { node: t.clone(), socket: String::new() },
                    kind: EdgeKind::Handoff,
                    branch: None,
                    condition: None,
                    possible: true,
                });
            }
        }
        for e in edges {
            if !wf.edges.iter().any(|x| x.from.node == e.from.node && x.to.node == e.to.node) {
                wf.edges.push(e);
            }
        }
    }
    prog
}

/// Drops possible edges, and gives a `yields_unknown` output step no output type.
pub fn definite(prog: &Program) -> Program {
    let mut prog = prog.clone();
    for wf in &mut prog.workflows {
        wf.edges.retain(|e| !e.possible);
        for n in wf.nodes.iter_mut().filter(|n| n.flag(attr::YIELDS_UNKNOWN)) {
            n.attrs.entry(attr::WORKFLOW_OUTPUT_TYPES.to_string()).or_default();
        }
    }
    prog
}
