//! One module per detector; `docs/detectors.md` maps them to the paper's catalog.

mod binding_capability;
mod channel_write_merge;
mod cycle_termination;
mod dangling_output;
mod interrupt_ordering;
mod read_after_write;
mod readiness_liveness;
mod router_branch_gating;
mod shared_instance_aliasing;
mod subflow_port_binding;
mod target_resolution;
mod type_contract;

pub use binding_capability::BindingCapability;
pub use channel_write_merge::ChannelWriteMerge;
pub use cycle_termination::CycleTermination;
pub use dangling_output::DanglingOutput;
pub use interrupt_ordering::InterruptOrdering;
pub use read_after_write::ReadAfterWrite;
pub use readiness_liveness::ReadinessLiveness;
pub use router_branch_gating::RouterBranchGating;
pub use shared_instance_aliasing::SharedInstanceAliasing;
pub use subflow_port_binding::SubflowPortBinding;
pub use target_resolution::TargetResolution;
pub use type_contract::TypeContract;
