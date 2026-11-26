# Detectors

The analyzer runs the twelve detectors of the paper's catalog (β1–β12), whose patterns the paper defines; each is a module in `crates/apsis-analysis/src/detectors/`. A finding names the detector and, in parentheses, the rule that fired: a detector covers several failure modes of its bug pattern, one rule each.

| Paper | Category | Detector | Module | Reports |
|---|---|---|---|---|
| β1 starved-step | Stalled & Runaway Workflows | `readiness-liveness` | `readiness_liveness.rs` | a step that cannot become ready, or becomes ready too early |
| β2 runaway-loop | Stalled & Runaway Workflows | `cycle-termination` | `cycle_termination.rs` | a cycle the workflow cannot leave |
| β3 mistyped-handoff | Broken Data Handoffs | `type-contract` | `type_contract.rs` | a value handed to a step that does not accept its type |
| β4 missing-route-target | Misrouted Dispatch | `target-resolution` | `target_resolution.rs` | routing that names nothing, cannot proceed, or goes two ways |
| β5 ungated-branch-merge | Misrouted Dispatch | `router-branch-gating` | `router_branch_gating.rs` | a branch the router did not select still runs |
| β6 dead-end-branch | Misrouted Dispatch | `dangling-output` | `dangling_output.rs` | a branch, or a whole workflow, whose result reaches no output |
| β7 racing-channel-write | Corrupted Shared State | `channel-write-merge` | `channel_write_merge.rs` | a channel updated in a way its merge rule cannot reconcile |
| β8 aliased-instance | Corrupted Shared State | `shared-instance-aliasing` | `shared_instance_aliasing.rs` | one mutable object held by two steps |
| β9 stale-read | Corrupted Shared State | `read-after-write` | `read_after_write.rs` | a read of shared state that no write is ordered before |
| β10 unwired-subflow-input | Unwired Subflows | `subflow-port-binding` | `subflow_port_binding.rs` | something a sub-workflow needs from its parent that is not bound across the boundary |
| β11 over-privileged-coordinator | Role & Interrupt Violations | `binding-capability` | `binding_capability.rs` | a binding that the role of one of its endpoints does not allow |
| β12 ungated-interrupt | Role & Interrupt Violations | `interrupt-ordering` | `interrupt_ordering.rs` | a human-in-the-loop step placed where it blocks the flow at the wrong point |

[examples/patterns/](../examples/patterns/) holds a minimal IR for each pattern shown in the paper's Fig. 7, and `crates/apsis-analysis/tests/catalog.rs` checks that each is reported by its detector.
