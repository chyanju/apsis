//! apsis-ir — the workflow IR: the JSON a front-end writes for a built workflow ([`Workflow`], or [`Program`]
//! when it embeds others). It holds facts only; fields beyond the basic graph are optional.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub type Id = String;

/// How the engine interprets the graph: when a step runs and how shared state is merged.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum ExecutionModel {
    /// A step runs when its inputs are ready; edges bind typed sockets (Haystack).
    #[default]
    DataflowReadiness,
    /// Bulk-synchronous supersteps; edges are control flow and data moves through state channels (LangGraph).
    BspSuperstep,
    /// Message-passing agents and executors; a coordinator or handoffs pick who runs next (AutoGen, Agent Framework).
    GroupChatSpeaker,
    /// An exported visual-builder flow: typed component handles, condition and loop nodes (langflow, Flowise).
    VisualDataflow,
    Other(String),
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Provenance {
    /// e.g. "import", "import-file", "yaml", "flow-json", "dotnet-assembly".
    pub kind: String,
    pub path: Option<String>,
    pub extractor: Option<String>,
}

/// A workflow and the workflows it embeds, cross-referenced by [`Workflow::id`].
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Program {
    pub workflows: Vec<Workflow>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Workflow {
    pub execution_model: ExecutionModel,
    pub framework: String,
    pub framework_version: Option<String>,
    #[serde(default)]
    pub provenance: Provenance,
    /// Referenced by [`SubflowRef::workflow`]; optional for a single graph.
    #[serde(default)]
    pub id: Option<Id>,
    #[serde(default)]
    pub nodes: Vec<Node>,
    #[serde(default)]
    pub edges: Vec<Edge>,
    /// Named shared state: state keys, shared-state entries, message channels.
    #[serde(default)]
    pub channels: Vec<Channel>,
    #[serde(default)]
    pub start_nodes: Vec<Id>,
    /// Empty when the framework designates no output steps.
    #[serde(default)]
    pub output_nodes: Vec<Id>,
    #[serde(default)]
    pub max_runs_per_component: Option<u32>,
    /// Workflow-level facts; see [`attr`].
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub attrs: BTreeMap<String, String>,
}

/// How a channel merges writes; `LastValue` (no reducer) overwrites, and two writes in one step collide.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum Reducer {
    #[default]
    LastValue,
    Append,
    BinaryOp(String),
    Custom(String),
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Channel {
    pub name: String,
    #[serde(default)]
    pub type_repr: String,
    #[serde(default)]
    pub reducer: Reducer,
    #[serde(default)]
    pub writers: Vec<Id>,
    #[serde(default)]
    pub readers: Vec<Id>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum NodeKind {
    #[default]
    Component,
    Agent,
    Tool,
    /// A router or condition node, whose branch outputs are mutually exclusive.
    Router,
    Loop,
    HumanInput,
    Start,
    End,
    Subflow,
    /// A step with typed message handlers.
    Executor,
    Other(String),
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SubflowRef {
    /// The [`Workflow::id`] of the embedded workflow, in the same [`Program`].
    pub workflow: Id,
    /// Into the sub-workflow: a parent socket feeding an inner input, or a parent step answering an inner request.
    #[serde(default)]
    pub in_bindings: Vec<PortBinding>,
    /// Out of the sub-workflow: an inner output bound to a parent socket.
    #[serde(default)]
    pub out_bindings: Vec<PortBinding>,
}

/// A binding across a sub-workflow boundary: an outer (parent) socket paired with an inner socket.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PortBinding {
    pub outer: SocketRef,
    pub inner: SocketRef,
    /// The receiving side converts the value to its own type: the socket must exist, its type is not compared.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub converted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Node {
    pub id: Id,
    /// The step's class in its framework; for reporting only.
    pub type_name: String,
    #[serde(default)]
    pub kind: NodeKind,
    #[serde(default)]
    pub inputs: Vec<InputSocket>,
    #[serde(default)]
    pub outputs: Vec<OutputSocket>,
    /// Template variables the step's prompt references.
    #[serde(default)]
    pub requires_vars: Vec<String>,
    /// The name routing refers to the step by (an agent or speaker name), when it differs from `id`.
    #[serde(default)]
    pub name: Option<String>,
    /// The role the framework assigns the step, e.g. `manager`.
    #[serde(default)]
    pub role: Option<String>,
    /// Names the step may route to: path-map entries, handoff and loop-back targets, participants.
    #[serde(default)]
    pub declared_targets: Vec<String>,
    #[serde(default)]
    pub subflow_ref: Option<SubflowRef>,
    /// Identity of the object behind the step; equal ids are one object. Stable within one extraction.
    #[serde(default)]
    pub instance_id: Option<String>,
    /// Identity of the store the step reads or writes. Stable within one extraction.
    #[serde(default)]
    pub store_ref: Option<String>,
    /// `"read"` or `"write"`.
    #[serde(default)]
    pub store_role: Option<String>,
    /// Model-specific facts; see [`attr`].
    #[serde(default)]
    pub attrs: BTreeMap<String, String>,
}

/// `type_repr` uses the IR type grammar: `Any`, `Optional[T]`, `Union[A, B]` or `A | B`, lowercase `list[T]`.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct InputSocket {
    pub name: String,
    pub type_repr: String,
    #[serde(default)]
    pub has_default: bool,
    #[serde(default)]
    pub variadic: bool,
    #[serde(default)]
    pub mandatory: bool,
    /// A variadic socket that consumes the first value to arrive instead of waiting for all.
    #[serde(default)]
    pub greedy: bool,
    /// The reducer of the channel this input writes into, when it has one.
    #[serde(default)]
    pub reducer: Option<Reducer>,
    /// The engine supplies this input itself; no edge feeds it.
    #[serde(default)]
    pub injected: bool,
    /// Only an edge can fill this input (a model, tool or memory binding).
    #[serde(default)]
    pub connection_only: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct OutputSocket {
    pub name: String,
    pub type_repr: String,
    /// Some run may produce no value on this output (an over-approximation).
    #[serde(default)]
    pub may_emit: bool,
}

/// `Data`, the default, carries a value from an output socket to an input socket.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum EdgeKind {
    #[default]
    Data,
    Control,
    /// A branch of a router, taken when the router selects [`Edge::branch`].
    Conditional,
    /// A tool bound to the step that may call it.
    Tool,
    Model,
    /// Control passed between agents: a handoff, an allowed speaker transition, a dynamic route.
    Handoff,
    Subflow,
    PubSub,
}

/// A data edge names both sockets; for other kinds an empty socket makes it an edge between steps.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Edge {
    pub from: SocketRef,
    pub to: SocketRef,
    #[serde(default)]
    pub kind: EdgeKind,
    /// The label a conditional edge is taken on; [`branch`] lists labels with a fixed meaning.
    #[serde(default)]
    pub branch: Option<String>,
    /// The guard as text, when the front-end has it; not evaluated.
    #[serde(default)]
    pub condition: Option<String>,
    /// A route that could not be resolved: it may add a finding, never rule one out.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub possible: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SocketRef {
    pub node: Id,
    /// Empty when the endpoint is the step itself.
    #[serde(default)]
    pub socket: String,
}

impl Node {
    pub fn input(&self, name: &str) -> Option<&InputSocket> {
        self.inputs.iter().find(|s| s.name == name)
    }
    pub fn output(&self, name: &str) -> Option<&OutputSocket> {
        self.outputs.iter().find(|s| s.name == name)
    }
    pub fn attr(&self, key: &str) -> Option<&str> {
        self.attrs.get(key).map(String::as_str)
    }
    pub fn flag(&self, key: &str) -> bool {
        self.attr(key) == Some("true")
    }
    /// The attributes stored per router branch under `<prefix><branch>`, as `(branch, value)` pairs.
    pub fn branch_attrs<'a>(&'a self, prefix: &'a str) -> impl Iterator<Item = (&'a str, &'a str)> {
        self.attrs.iter().filter_map(move |(k, v)| k.strip_prefix(prefix).map(|branch| (branch, v.as_str())))
    }
}

/// The entry of a workflow in edges and routing targets.
pub const START: &str = "__start__";
/// The exit of a workflow in edges and routing targets.
pub const END: &str = "__end__";

/// Keys of [`Node::attrs`] that the analysis reads. Values are strings; a flag is set when its value is `"true"`.
pub mod attr {
    /// `"all"` when the step runs only once every predecessor has completed.
    pub const ACTIVATION: &str = "activation";
    /// Flag: a step on a cycle that the engine starts without waiting for its inputs from outside the cycle.
    pub const EAGER_START: &str = "eager_start";
    /// Flag: the step is the target of a barrier edge, which waits for all its sources.
    pub const BARRIER_JOIN: &str = "barrier_join";
    /// `"list"`: the messages of several producers arrive as one list; `"each"` or absent: one at a time.
    pub const FAN_IN_DELIVERY: &str = "fan_in_delivery";
    /// Flag: every message sent to the step reaches it, whatever its type; without it unhandled types are dropped.
    pub const TAKES_ALL_MESSAGES: &str = "takes_all_messages";
    /// Flag: the step routes to a target the front-end could not evaluate, so it may route anywhere.
    pub const GOTO_UNRESOLVED: &str = "goto_unresolved";
    /// Flag: the step's declared targets are steps of the parent graph.
    pub const COMMAND_PARENT: &str = "command_parent";
    /// Flag: the step runs once per item of a fan-out, as concurrent instances.
    pub const FANOUT: &str = "fanout";
    /// Flag: the step replaces the whole state instead of updating the channels it names.
    pub const FULL_STATE_UPDATE: &str = "full_state_update";
    /// The input that binds [`super::Node::requires_vars`].
    pub const TEMPLATE_VALUES_INPUT: &str = "template_values_input";
    pub const STREAM: &str = "stream";
    pub const ACCEPTS_STREAM: &str = "accepts_stream";
    /// Comma-separated types the step may yield as workflow output; empty when none, absent when unknown.
    pub const WORKFLOW_OUTPUT_TYPES: &str = "workflow_output_types";
    /// Comma-separated message types the step may send (others are rejected); absent: it may send anything.
    pub const DECLARED_SENDS: &str = "declared_sends";
    /// Comma-separated channels whose first access by the step, in source order, is a read.
    pub const READS_BEFORE_WRITE: &str = "reads_before_write";
    /// Flag: an output step whose output types the front-end could not read; it may yield nothing.
    pub const YIELDS_UNKNOWN: &str = "yields_unknown";
    /// Flag on a workflow: every caller gets this one workflow object, and one run owns it at a time.
    pub const SHARED_WORKFLOW: &str = "shared_workflow";
    /// Flag on a workflow: a run starts from the channels its previous run left.
    pub const KEEPS_STATE: &str = "keeps_state";
    /// On a workflow: comma-separated channels the run's input or the engine sets, with no step writing them.
    pub const PROVIDED_CHANNELS: &str = "provided_channels";
    /// Prefix: `supertypes:<T>` lists the types a message of type `T` sent by the step is also an instance of.
    pub const SUPERTYPES: &str = "supertypes:";
    /// Flag: the engine continues from this step without an outgoing edge.
    pub const IMPLICIT_RETURN: &str = "implicit_return";
    /// How a router's branches behave: [`BRANCH_TRANSITION`] or [`BRANCH_DATA_GATE`].
    pub const BRANCH_OUTPUTS: &str = "branch_outputs";
    /// The branches are mutually exclusive paths: the engine follows exactly one.
    pub const BRANCH_TRANSITION: &str = "transition";
    /// Each output carries the router's input when selected; all should be wired, and branches may meet again.
    pub const BRANCH_DATA_GATE: &str = "data-gate";
    /// `"restricted"` when a coordinator limits who may speak after whom; handoff edges are the allowed transitions.
    pub const SPEAKER_TRANSITIONS: &str = "speaker_transitions";
    /// Comma-separated agents that can propose a call of this tool.
    pub const CALLERS: &str = "callers";
    /// `"true"` or `"false"`: whether some agent can execute this tool.
    pub const HAS_EXECUTOR: &str = "has_executor";
    pub const DECLARES_TOOLS: &str = "declares_tools";
    /// Flag: the step issues a request to its environment and waits for the answer.
    pub const REQUEST_PORT: &str = "request_port";
    /// Flag: a sub-workflow host that passes its sub-workflow's requests on to its own caller.
    pub const PROPAGATES_REQUESTS: &str = "propagates_requests";
    /// Comma-separated channels a router reads although its input schema filters them out.
    pub const ROUTER_FILTERED_READS: &str = "router_filtered_reads";
    /// Prefix, per branch: the labels the branch's path map declares, comma-separated.
    pub const ROUTER_MAP: &str = "router_map:";
    /// Prefix, per branch: the labels the routing function can return, comma-separated.
    pub const ROUTER_RETURNS: &str = "router_returns:";
    /// Prefix, per branch, flag: a return value of the routing function could not be evaluated.
    pub const ROUTER_UNRESOLVED: &str = "router_unresolved:";
    /// Prefix, per branch, flag: the routing function returns a list of targets, which all run.
    pub const ROUTER_FANOUT: &str = "router_fanout:";
}

/// Values of [`Edge::branch`] with a fixed meaning.
pub mod branch {
    /// On a control edge into a controller: the source's turn starts the controller's nested chat.
    pub const NESTED_CHAT_TRIGGER: &str = "nested-chat-trigger";
    /// On a subflow edge out of a controller: the target takes part in the controller's nested chat.
    pub const NESTED_CHAT: &str = "nested-chat";
}

impl Program {
    /// Accepts a `{"workflows": [...]}` object or a bare [`Workflow`] (a program of one).
    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        match serde_json::from_str::<Program>(s) {
            Ok(p) if !p.workflows.is_empty() => Ok(p),
            _ => Ok(Program { workflows: vec![Workflow::from_json(s)?] }),
        }
    }

    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string_pretty(self)
    }

    pub fn workflow(&self, id: &str) -> Option<&Workflow> {
        self.workflows.iter().find(|w| w.id.as_deref() == Some(id))
    }
}

impl Workflow {
    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(s)
    }

    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string_pretty(self)
    }

    pub fn node(&self, id: &str) -> Option<&Node> {
        self.nodes.iter().find(|n| n.id == id)
    }

    pub fn channel(&self, name: &str) -> Option<&Channel> {
        self.channels.iter().find(|c| c.name == name)
    }

    pub fn edges_into<'a>(&'a self, node: &'a str, socket: &'a str) -> impl Iterator<Item = &'a Edge> {
        self.edges.iter().filter(move |e| e.to.node == node && e.to.socket == socket)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrips_through_json() {
        let wf = Workflow {
            execution_model: ExecutionModel::DataflowReadiness,
            framework: "haystack".into(),
            framework_version: Some("2.25.0".into()),
            provenance: Provenance { kind: "yaml".into(), path: None, extractor: None },
            nodes: vec![Node {
                id: "retriever".into(),
                type_name: "haystack...InMemoryBM25Retriever".into(),
                inputs: vec![InputSocket {
                    name: "query".into(),
                    type_repr: "str".into(),
                    mandatory: true,
                    ..Default::default()
                }],
                outputs: vec![OutputSocket {
                    name: "documents".into(),
                    type_repr: "List[Document]".into(),
                    may_emit: false,
                }],
                instance_id: Some("0x1".into()),
                ..Default::default()
            }],
            max_runs_per_component: Some(1),
            ..Default::default()
        };
        let json = wf.to_json().unwrap();
        let back = Workflow::from_json(&json).unwrap();
        assert_eq!(back.nodes.len(), 1);
        assert_eq!(back.framework_version.as_deref(), Some("2.25.0"));
        assert!(back.nodes[0].inputs[0].mandatory);
    }

    #[test]
    fn json_with_only_the_basic_graph_parses() {
        let basic_graph = r#"{
            "execution_model": "dataflow-readiness",
            "framework": "haystack",
            "framework_version": "2.30.2",
            "nodes": [
                {"id": "a", "type_name": "A",
                 "inputs": [{"name": "x", "type_repr": "str", "mandatory": true}],
                 "outputs": [{"name": "o", "type_repr": "str"}]}
            ],
            "edges": [{"from": {"node": "a", "socket": "o"}, "to": {"node": "a", "socket": "x"}}]
        }"#;
        let wf = Workflow::from_json(basic_graph).unwrap();
        assert_eq!(wf.nodes.len(), 1);
        assert_eq!(wf.nodes[0].kind, NodeKind::Component);
        assert_eq!(wf.edges[0].kind, EdgeKind::Data);
        assert!(wf.nodes[0].attrs.is_empty());
    }

    #[test]
    fn all_facts_roundtrip() {
        let sub = Workflow {
            execution_model: ExecutionModel::BspSuperstep,
            framework: "langgraph".into(),
            id: Some("child".into()),
            nodes: vec![Node { id: "inner".into(), type_name: "Inner".into(), ..Default::default() }],
            ..Default::default()
        };
        let main = Workflow {
            execution_model: ExecutionModel::VisualDataflow,
            framework: "flowise".into(),
            id: Some("main".into()),
            channels: vec![Channel {
                name: "messages".into(),
                type_repr: "list[Message]".into(),
                reducer: Reducer::Append,
                writers: vec!["a".into(), "b".into()],
                readers: vec!["c".into()],
            }],
            nodes: vec![
                Node {
                    id: "router".into(),
                    type_name: "ConditionalRouter".into(),
                    kind: NodeKind::Router,
                    declared_targets: vec!["x".into(), "y".into()],
                    outputs: vec![OutputSocket { name: "true_result".into(), type_repr: "Any".into(), may_emit: true }],
                    ..Default::default()
                },
                Node {
                    id: "run".into(),
                    type_name: "RunFlow".into(),
                    kind: NodeKind::Subflow,
                    subflow_ref: Some(SubflowRef {
                        workflow: "child".into(),
                        in_bindings: vec![],
                        out_bindings: vec![PortBinding {
                            outer: SocketRef { node: "run".into(), socket: "out".into() },
                            inner: SocketRef { node: "inner".into(), socket: "result".into() },
                            converted: false,
                        }],
                    }),
                    ..Default::default()
                },
            ],
            edges: vec![Edge {
                from: SocketRef { node: "router".into(), socket: "true_result".into() },
                to: SocketRef { node: "run".into(), socket: "".into() },
                kind: EdgeKind::Conditional,
                branch: Some("true_result".into()),
                condition: None,
                possible: false,
            }],
            start_nodes: vec!["router".into()],
            ..Default::default()
        };
        let prog = Program { workflows: vec![main, sub] };
        let json = prog.to_json().unwrap();
        let back = Program::from_json(&json).unwrap();
        assert_eq!(back.workflows.len(), 2);
        let m = back.workflow("main").unwrap();
        assert_eq!(m.channel("messages").unwrap().reducer, Reducer::Append);
        assert_eq!(m.node("router").unwrap().kind, NodeKind::Router);
        assert_eq!(m.node("router").unwrap().declared_targets, vec!["x", "y"]);
        assert_eq!(m.edges[0].kind, EdgeKind::Conditional);
        assert_eq!(m.edges[0].branch.as_deref(), Some("true_result"));
        let sr = m.node("run").unwrap().subflow_ref.as_ref().unwrap();
        assert_eq!(sr.workflow, "child");
        assert!(back.workflow("child").is_some());
    }

    #[test]
    fn program_accepts_bare_workflow() {
        let wf = Workflow {
            execution_model: ExecutionModel::DataflowReadiness,
            framework: "haystack".into(),
            nodes: vec![Node { id: "a".into(), type_name: "A".into(), ..Default::default() }],
            ..Default::default()
        };
        let prog = Program::from_json(&wf.to_json().unwrap()).unwrap();
        assert_eq!(prog.workflows.len(), 1);
        assert_eq!(prog.workflows[0].nodes[0].id, "a");
    }
}
