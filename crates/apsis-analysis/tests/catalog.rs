//! Every clause of the paper's detector catalog (Fig. 7) fires on its minimal example, and only that clause.

use apsis_analysis::{analyze, detectors};
use apsis_ir::Program;

/// (example file, detector, rule) — one row per clause of the catalog.
const CLAUSES: &[(&str, &str, &str)] = &[
    ("01-starved-step", "readiness-liveness", "unfed-required-input"),
    ("01-deadlocked-join", "readiness-liveness", "deadlocked-join"),
    ("02-runaway-loop", "cycle-termination", "closed-cycle"),
    ("03-mistyped-handoff", "type-contract", "edge-type-mismatch"),
    ("03-undeclared-channel-write", "type-contract", "undeclared-channel-write"),
    ("03-message-cannot-route", "type-contract", "no-handler-for-message"),
    ("04-missing-route-target", "target-resolution", "unresolved-target"),
    ("04-double-route", "target-resolution", "double-route"),
    ("05-ungated-branch-merge", "router-branch-gating", "branches-converge"),
    ("06-dead-end-branch", "dangling-output", "dead-end-branch"),
    ("07-racing-channel-write", "channel-write-merge", "concurrent-last-value-writes"),
    ("07-full-state-overwrite", "channel-write-merge", "full-state-overwrite"),
    ("07-fan-in-barrier", "channel-write-merge", "fan-in-without-barrier"),
    ("08-aliased-instance", "shared-instance-aliasing", "shared-instance"),
    ("09-stale-read", "read-after-write", "unordered-store-read"),
    ("10-unwired-subflow-input", "subflow-port-binding", "unbound-subflow-input"),
    ("11-over-privileged-coordinator", "binding-capability", "coordinator-declares-tools"),
    ("12-ungated-interrupt", "interrupt-ordering", "serial-interrupts"),
    ("12-interrupt-before-agent", "interrupt-ordering", "interrupt-before-agent"),
];

#[test]
fn every_clause_fires_on_its_minimal_example_and_nothing_else_does() {
    for (file, detector, rule) in CLAUSES {
        let path = format!("{}/../../examples/patterns/{file}.json", env!("CARGO_MANIFEST_DIR"));
        let json = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path}: {e}"));
        let program = Program::from_json(&json).unwrap_or_else(|e| panic!("{path}: {e}"));
        let mut fired: Vec<(&str, &str)> = analyze(&program).iter().map(|f| (f.detector, f.rule)).collect();
        fired.sort();
        fired.dedup();
        assert_eq!(fired, vec![(*detector, *rule)], "{file}");
    }
}

#[test]
fn the_catalog_has_twelve_detectors_and_nineteen_clauses() {
    let mut detectors_covered: Vec<&str> = CLAUSES.iter().map(|c| c.1).collect();
    detectors_covered.sort();
    detectors_covered.dedup();
    assert_eq!(CLAUSES.len(), 19);
    assert_eq!(detectors_covered.len(), 12);
    assert_eq!(detectors().len(), 12);
}
