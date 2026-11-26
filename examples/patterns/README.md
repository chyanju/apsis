# The pattern catalog, one minimal IR per clause

The paper's catalog (its Fig. 7) lists twelve detectors, β1 to β12, as nineteen clauses: one principal clause per detector plus the sub-clauses marked "+". Each file here is the smallest IR on which one clause holds; the number in its name is the number of the detector. No framework needs to be installed: run any of them with

```
./target/release/apsis check examples/patterns/07-racing-channel-write.json
```

and the analyzer reports the detector and rule in the fourth column, and nothing else. `crates/apsis-analysis/tests/catalog.rs` checks exactly that for all nineteen.

| Paper | Clause | Example | Detector / rule in the analyzer | What the example contains |
|---|---|---|---|---|
| β1 | starved-step | `01-starved-step.json` | `readiness-liveness` / `unfed-required-input` | Step `v` has a mandatory input that only an edge can fill, and no edge feeds it. |
| β1 | + deadlocked join | `01-deadlocked-join.json` | `readiness-liveness` / `deadlocked-join` | Join `j` waits for both `p1` and `p2`, which sit on two exclusive branches of router `r`. |
| β2 | runaway-loop | `02-runaway-loop.json` | `cycle-termination` / `closed-cycle` | Steps `a` and `b` feed each other and no edge leaves the cycle. |
| β3 | mistyped-handoff | `03-mistyped-handoff.json` | `type-contract` / `edge-type-mismatch` | Output `a.o` of type `str` is wired to input `b.i` of type `int`. |
| β3 | + undeclared channel write | `03-undeclared-channel-write.json` | `type-contract` / `undeclared-channel-write` | Step `v` writes the state key `y`; the state schema declares only `x`. |
| β3 | + message cannot route | `03-message-cannot-route.json` | `type-contract` / `no-handler-for-message` | Agent `a` emits a message of type `A`; the only handler of `b` takes `B`. |
| β4 | missing-route-target | `04-missing-route-target.json` | `target-resolution` / `unresolved-target` | Router `r` declares the target `x`, and no step is called `x`. |
| β4 | + double route | `04-double-route.json` | `target-resolution` / `double-route` | Step `v` has a static edge to `t` and also routes dynamically to `t` or `u`: the static edge runs `t` on every pass. |
| β5 | ungated-branch-merge | `05-ungated-branch-merge.json` | `router-branch-gating` / `branches-converge` | Both branches of router `r` lead to `t`, so `t` runs whichever branch is taken. |
| β6 | dead-end-branch | `06-dead-end-branch.json` | `dangling-output` / `dead-end-branch` | Branch `a` of router `r` reaches the end node; its sibling `b` reaches no terminal. |
| β7 | racing-channel-write | `07-racing-channel-write.json` | `channel-write-merge` / `concurrent-last-value-writes` | Steps `a` and `b` both write channel `c`, which has no reducer, and neither runs before the other. |
| β7 | + full-state overwrite | `07-full-state-overwrite.json` | `channel-write-merge` / `full-state-overwrite` | Step `v` replaces the whole state, which has two channels. |
| β7 | + fan-in barrier | `07-fan-in-barrier.json` | `channel-write-merge` / `fan-in-without-barrier` | Join `d` is fed by `a` (one step from the start) and `b2` (two steps), by separate edges and without a barrier. |
| β8 | aliased-instance | `08-aliased-instance.json` | `shared-instance-aliasing` / `shared-instance` | Steps `a` and `b` are the same object. |
| β9 | stale-read | `09-stale-read.json` | `read-after-write` / `unordered-store-read` | Step `w` writes a store that step `r` reads, and no path leads from `w` to `r`. |
| β10 | unwired-subflow-input | `10-unwired-subflow-input.json` | `subflow-port-binding` / `unbound-subflow-input` | Agent `ag` uses sub-flow `v` as a tool; the sub-flow has an input and `v` binds none. |
| β11 | over-privileged-coordinator | `11-over-privileged-coordinator.json` | `binding-capability` / `coordinator-declares-tools` | Manager `m` only selects the next speaker, yet declares tools of its own. |
| β12 | ungated-interrupt | `12-ungated-interrupt.json` | `interrupt-ordering` / `serial-interrupts` | Interrupt `h2` always follows interrupt `h1`; no router lies between them. |
| β12 | + interrupt before agent | `12-interrupt-before-agent.json` | `interrupt-ordering` / `interrupt-before-agent` | Interrupt `h` is reached from the start before any agent has run. |

The names differ between the paper and the code because the paper names the bug pattern and the code names the check; `docs/detectors.md` gives both for every detector.
