//! One test per rule: the smallest workflow on which the rule fires, and the nearest ones on which it does not.

use apsis_analysis::*;
use apsis_ir::*;

fn findings(w: &Workflow) -> Vec<Finding> {
    analyze(&Program { workflows: vec![w.clone()] })
}

fn n(id: &str, inputs: Vec<InputSocket>, outputs: Vec<OutputSocket>) -> Node {
    Node { id: id.into(), type_name: "test".into(), inputs, outputs, ..Default::default() }
}
fn isock(name: &str, ty: &str, has_default: bool, mandatory: bool) -> InputSocket {
    InputSocket { name: name.into(), type_repr: ty.into(), has_default, mandatory, ..Default::default() }
}
fn osock(name: &str, ty: &str, may_emit: bool) -> OutputSocket {
    OutputSocket { name: name.into(), type_repr: ty.into(), may_emit }
}
fn wf(nodes: Vec<Node>, edges: Vec<Edge>, max_runs: Option<u32>) -> Workflow {
    Workflow {
        execution_model: ExecutionModel::DataflowReadiness,
        framework: "test".into(),
        nodes,
        edges,
        max_runs_per_component: max_runs,
        ..Default::default()
    }
}
fn edge(fa: &str, fs: &str, ta: &str, ts: &str) -> Edge {
    Edge {
        from: SocketRef { node: fa.into(), socket: fs.into() },
        to: SocketRef { node: ta.into(), socket: ts.into() },
        ..Default::default()
    }
}

#[test]
fn coordinator_that_declares_tools() {
    let mut attrs = std::collections::BTreeMap::new();
    attrs.insert("declares_tools".to_string(), "true".to_string());
    let mgr = Node {
        id: "manager".into(),
        kind: NodeKind::Router,
        role: Some("manager".into()),
        attrs,
        ..Default::default()
    };
    let mut w = wf(vec![mgr], vec![], None);
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    let f = BindingCapability.check(&w);
    assert_eq!(f.len(), 1, "a manager declaring tools is a capability violation");
    assert_eq!(f[0].detector, "binding-capability");

    let mgr_ok = Node { id: "m2".into(), kind: NodeKind::Router, role: Some("manager".into()), ..Default::default() };
    let mut w2 = wf(vec![mgr_ok], vec![], None);
    w2.execution_model = ExecutionModel::GroupChatSpeaker;
    assert!(BindingCapability.check(&w2).is_empty());
}

#[test]
fn branch_that_reaches_no_terminal() {
    let start = Node { id: "start".into(), kind: NodeKind::Start, ..Default::default() };
    let router = Node { id: "router".into(), kind: NodeKind::Router, ..Default::default() };
    let dead = Node { id: "agent_dead".into(), kind: NodeKind::Agent, ..Default::default() };
    let end = Node { id: "end".into(), kind: NodeKind::End, ..Default::default() };
    let mut w = wf(
        vec![start, router, dead, end],
        vec![
            edge("start", "o", "router", "i"),
            edge("router", "t", "agent_dead", "i"),
            edge("router", "f", "end", "i"),
        ],
        None,
    );
    w.execution_model = ExecutionModel::VisualDataflow;
    let f = DanglingOutput.check(&w);
    assert_eq!(f.len(), 1, "the agent whose output goes nowhere is a dead-end");
    assert_eq!(f[0].location, "agent_dead");

    let mut w2 = w.clone();
    w2.edges.push(edge("agent_dead", "o", "end", "i2"));
    assert!(DanglingOutput.check(&w2).is_empty());
}

#[test]
fn defaulted_input_that_is_also_wired_fires_early() {
    let w = wf(
        vec![n("a", vec![], vec![osock("out", "str", false)]), n("b", vec![isock("x", "str", true, false)], vec![])],
        vec![edge("a", "out", "b", "x")],
        Some(1),
    );
    let f = findings(&w);
    assert!(f.iter().any(|f| f.detector == "readiness-liveness" && f.rule == "premature-default"));
}

#[test]
fn output_type_not_accepted_by_the_input() {
    let w = wf(
        vec![n("a", vec![], vec![osock("out", "int", false)]), n("b", vec![isock("x", "str", false, true)], vec![])],
        vec![edge("a", "out", "b", "x")],
        Some(1),
    );
    let f = findings(&w);
    assert!(f.iter().any(|f| f.detector == "type-contract"));
}

#[test]
fn cycle_without_an_exit() {
    let w = wf(
        vec![
            n("a", vec![isock("x", "str", false, true)], vec![osock("o", "str", false)]),
            n("b", vec![isock("y", "str", false, true)], vec![osock("o", "str", false)]),
        ],
        vec![edge("a", "o", "b", "y"), edge("b", "o", "a", "x")],
        None,
    );
    let f = findings(&w);
    assert!(f.iter().any(|f| f.detector == "cycle-termination"));
}

fn bsp(nodes: Vec<Node>, edges: Vec<Edge>, channels: Vec<Channel>) -> Workflow {
    Workflow {
        execution_model: ExecutionModel::BspSuperstep,
        framework: "langgraph".into(),
        nodes,
        edges,
        channels,
        ..Default::default()
    }
}
fn bn(id: &str) -> Node {
    Node { id: id.into(), type_name: "fn".into(), ..Default::default() }
}
fn kedge(a: &str, b: &str, kind: EdgeKind, branch: Option<&str>) -> Edge {
    Edge {
        from: SocketRef { node: a.into(), socket: String::new() },
        to: SocketRef { node: b.into(), socket: String::new() },
        kind,
        branch: branch.map(str::to_string),
        condition: None,
        possible: false,
    }
}
fn fired(f: &[Finding], det: &str) -> Vec<String> {
    f.iter().filter(|x| x.detector == det).map(|x| x.location.clone()).collect()
}

#[test]
fn double_route_static_edge_overrides_dynamic_route() {
    let mut sup = bn("supervisor");
    sup.declared_targets = vec!["workers".into(), "__end__".into()];
    let w = bsp(
        vec![sup, bn("workers")],
        vec![
            kedge("__start__", "supervisor", EdgeKind::Control, None),
            kedge("supervisor", "workers", EdgeKind::Control, None),
            kedge("supervisor", "workers", EdgeKind::Conditional, Some("router")),
            kedge("supervisor", "__end__", EdgeKind::Conditional, Some("router")),
            kedge("workers", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    assert_eq!(fired(&TargetResolution.check(&w), "target-resolution"), vec!["supervisor->workers"]);
    // the static edge goes to END, which schedules no step
    let mut analyze = bn("analyze");
    analyze.declared_targets = vec!["end".into()];
    let w2 = bsp(
        vec![bn("gather"), analyze, bn("end")],
        vec![
            kedge("__start__", "gather", EdgeKind::Control, None),
            kedge("gather", "analyze", EdgeKind::Control, None),
            kedge("analyze", "__end__", EdgeKind::Control, None),
            kedge("analyze", "end", EdgeKind::Handoff, None),
            kedge("end", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    assert!(fired(&TargetResolution.check(&w2), "target-resolution").is_empty());
    // the dynamic route can only name the static target
    let mut start_flow = bn("start_flow");
    start_flow.declared_targets = vec!["chat".into()];
    let w3 = bsp(
        vec![start_flow, bn("chat")],
        vec![
            kedge("__start__", "start_flow", EdgeKind::Control, None),
            kedge("start_flow", "chat", EdgeKind::Control, None),
            kedge("start_flow", "chat", EdgeKind::Handoff, None),
            kedge("chat", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    assert!(fired(&TargetResolution.check(&w3), "target-resolution").is_empty());
}

#[test]
fn router_label_missing_from_path_map() {
    let mut r = bn("supervisor");
    r.attrs.insert("router_map:router".into(), "workers,end".into());
    r.attrs.insert("router_returns:router".into(), "end,supevisor,workers".into());
    let w = bsp(
        vec![r, bn("workers")],
        vec![
            kedge("__start__", "supervisor", EdgeKind::Control, None),
            kedge("supervisor", "workers", EdgeKind::Conditional, Some("router")),
            kedge("supervisor", "__end__", EdgeKind::Conditional, Some("router")),
            kedge("workers", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    assert_eq!(rule_locations(&TargetResolution.check(&w)), vec!["label-outside-path-map@supervisor:supevisor"]);
}

#[test]
fn fan_in_at_unequal_depths_needs_a_barrier() {
    // a fans out to b and c; b reaches d directly, c through c2, so the branches arrive in different steps
    let edges = |fanout: EdgeKind, branch: Option<&'static str>| {
        vec![
            kedge("__start__", "a", EdgeKind::Control, None),
            kedge("a", "b", fanout.clone(), branch),
            kedge("a", "c", fanout, branch),
            kedge("c", "c2", EdgeKind::Control, None),
            kedge("b", "d", EdgeKind::Control, None),
            kedge("c2", "d", EdgeKind::Control, None),
            kedge("d", "__end__", EdgeKind::Control, None),
        ]
    };
    let nodes = |d: Node| vec![bn("a"), bn("b"), bn("c"), bn("c2"), d];
    let w = bsp(nodes(bn("d")), edges(EdgeKind::Control, None), vec![]);
    assert_eq!(fired(&ChannelWriteMerge.check(&w), "channel-write-merge"), vec!["d"]);
    let mut d = bn("d");
    d.attrs.insert("barrier_join".into(), "true".into());
    let w2 = bsp(nodes(d), edges(EdgeKind::Control, None), vec![]);
    assert!(fired(&ChannelWriteMerge.check(&w2), "channel-write-merge").is_empty());
    let w3 = bsp(nodes(bn("d")), edges(EdgeKind::Conditional, Some("route")), vec![]);
    assert!(fired(&ChannelWriteMerge.check(&w3), "channel-write-merge").is_empty());
    // branches of equal depth arrive together
    let w4 = bsp(
        vec![bn("a"), bn("b"), bn("c"), bn("d")],
        vec![
            kedge("__start__", "a", EdgeKind::Control, None),
            kedge("a", "b", EdgeKind::Control, None),
            kedge("a", "c", EdgeKind::Control, None),
            kedge("b", "d", EdgeKind::Control, None),
            kedge("c", "d", EdgeKind::Control, None),
            kedge("d", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    assert!(fired(&ChannelWriteMerge.check(&w4), "channel-write-merge").is_empty());
}

#[test]
fn step_that_no_route_leads_to() {
    let mut w = bsp(
        vec![bn("agent"), bn("branch"), bn("stray")],
        vec![
            kedge("__start__", "agent", EdgeKind::Control, None),
            kedge("agent", "branch", EdgeKind::Control, None),
            kedge("branch", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    assert_eq!(fired(&ReadinessLiveness.check(&w), "readiness-liveness"), vec!["stray"]);
    // `branch` now ends the run without an edge to END
    w.edges.pop();
    assert_eq!(fired(&ReadinessLiveness.check(&w), "readiness-liveness"), vec!["stray"]);
    // an unresolved route from `branch` may reach `stray` but does not clear the finding
    w.nodes[1].attrs.insert("goto_unresolved".into(), "true".into());
    let found = rule_locations(&analyze(&Program { workflows: vec![w] }));
    assert!(found.contains(&"unreachable-node@stray".to_string()), "{found:?}");
    assert!(found.contains(&"unresolved-route@branch".to_string()), "{found:?}");
}

fn rule_locations(findings: &[Finding]) -> Vec<String> {
    let mut v: Vec<String> = findings.iter().map(|f| format!("{}@{}", f.rule, f.location)).collect();
    v.sort();
    v
}

#[test]
fn an_unresolved_route_adds_findings_and_never_removes_one() {
    let mut supervisor = bn("supervisor");
    supervisor.attrs.insert(attr::GOTO_UNRESOLVED.into(), "true".into());
    let w = bsp(
        vec![supervisor, bn("worker_a"), bn("worker_b")],
        vec![
            kedge("__start__", "supervisor", EdgeKind::Control, None),
            kedge("worker_a", "supervisor", EdgeKind::Control, None),
            kedge("worker_b", "supervisor", EdgeKind::Control, None),
        ],
        vec![],
    );
    // the route may close a loop, and shows neither a way out nor a path to a worker
    assert_eq!(
        rule_locations(&analyze(&Program { workflows: vec![w] })),
        vec![
            "closed-cycle@supervisor",
            "unreachable-node@worker_a",
            "unreachable-node@worker_b",
            "unresolved-route@supervisor"
        ]
    );
}

#[test]
fn a_message_of_unknown_type_may_have_no_handler() {
    let case = |handler: &str| {
        let exec = |id: &str, inputs: Vec<InputSocket>, outputs: Vec<OutputSocket>| Node {
            kind: NodeKind::Executor,
            ..n(id, inputs, outputs)
        };
        let sender = exec("sender", vec![isock("run", "str", false, true)], vec![]);
        let receiver = exec("receiver", vec![isock("handle", handler, false, true)], vec![]);
        let mut w = wf(vec![sender, receiver], vec![kedge("sender", "receiver", EdgeKind::Control, None)], None);
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        TypeContract.check(&w).iter().map(|f| f.rule).collect::<Vec<_>>()
    };
    assert_eq!(case("str"), vec!["no-handler-for-message"]);
    assert!(case("Any").is_empty());
}

#[test]
fn an_output_step_whose_output_types_are_unknown_may_yield_nothing() {
    let exec = |id: &str| Node { id: id.into(), kind: NodeKind::Executor, ..Default::default() };
    let mut critic = exec("critic");
    critic.attrs.insert(attr::YIELDS_UNKNOWN.into(), "true".into());
    let mut w = wf(
        vec![exec("drafter"), critic],
        vec![kedge("drafter", "critic", EdgeKind::Control, None), kedge("critic", "drafter", EdgeKind::Control, None)],
        None,
    );
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    w.output_nodes = vec!["critic".into()];
    let found = rule_locations(&analyze(&Program { workflows: vec![w] }));
    assert!(found.contains(&"closed-cycle@drafter".to_string()), "{found:?}");
    assert!(found.contains(&"output-without-type@critic".to_string()), "{found:?}");
}

#[test]
fn cycle_with_declared_end_exit_is_bounded() {
    let mut chat = bn("chat");
    chat.declared_targets = vec!["tools".into(), "__end__".into()];
    let edges = vec![
        kedge("__start__", "chat", EdgeKind::Control, None),
        kedge("chat", "tools", EdgeKind::Handoff, None),
        kedge("tools", "chat", EdgeKind::Control, None),
    ];
    let w = bsp(vec![chat.clone(), bn("tools")], edges.clone(), vec![]);
    assert!(fired(&CycleTermination.check(&w), "cycle-termination").is_empty());
    chat.declared_targets = vec!["tools".into()];
    let w2 = bsp(vec![chat, bn("tools")], edges, vec![]);
    assert_eq!(fired(&CycleTermination.check(&w2), "cycle-termination"), vec!["chat"]);
}

#[test]
fn self_loop_without_counter_is_a_runaway() {
    let mut chat = bn("chat");
    chat.declared_targets = vec!["chat".into(), "tools".into(), "__end__".into()];
    chat.outputs = vec![osock("messages", "list[BaseMessage]", true)];
    let edges = vec![
        kedge("__start__", "chat", EdgeKind::Control, None),
        kedge("chat", "chat", EdgeKind::Handoff, None),
        kedge("chat", "tools", EdgeKind::Handoff, None),
        kedge("tools", "chat", EdgeKind::Control, None),
    ];
    let w = bsp(vec![chat.clone(), bn("tools")], edges.clone(), vec![]);
    assert_eq!(rule_locations(&CycleTermination.check(&w)), vec!["self-loop-without-counter@chat"]);
    chat.outputs.push(osock("retries", "int", false));
    let w2 = bsp(vec![chat, bn("tools")], edges, vec![]);
    assert!(fired(&CycleTermination.check(&w2), "cycle-termination").is_empty());
}

#[test]
fn unordered_writers_of_a_lastvalue_channel_collide() {
    let mut a = bn("a");
    a.outputs = vec![osock("out", "str", false)];
    let mut b = bn("b");
    b.outputs = vec![osock("out", "str", false)];
    let ch = |reducer: Reducer| Channel {
        name: "out".into(),
        type_repr: "str".into(),
        reducer,
        writers: vec!["a".into(), "b".into()],
        readers: vec![],
    };
    let edges = vec![
        kedge("__start__", "f", EdgeKind::Control, None),
        kedge("f", "a", EdgeKind::Control, None),
        kedge("f", "b", EdgeKind::Control, None),
        kedge("a", "__end__", EdgeKind::Control, None),
        kedge("b", "__end__", EdgeKind::Control, None),
    ];
    let w = bsp(vec![bn("f"), a.clone(), b.clone()], edges.clone(), vec![ch(Reducer::LastValue)]);
    assert_eq!(fired(&ChannelWriteMerge.check(&w), "channel-write-merge"), vec!["out"]);
    let w2 = bsp(vec![bn("f"), a.clone(), b.clone()], edges, vec![ch(Reducer::Append)]);
    assert!(fired(&ChannelWriteMerge.check(&w2), "channel-write-merge").is_empty());
    let w3 = bsp(
        vec![a, b],
        vec![
            kedge("__start__", "a", EdgeKind::Control, None),
            kedge("a", "b", EdgeKind::Control, None),
            kedge("b", "__end__", EdgeKind::Control, None),
        ],
        vec![ch(Reducer::LastValue)],
    );
    assert!(fired(&ChannelWriteMerge.check(&w3), "channel-write-merge").is_empty());
}

#[test]
fn parent_goto_target_is_a_parallel_branch() {
    // child step `k` routes to `s`, so `sg` fans out to `b` and `s`, which reach `j` at unequal depths
    let mut sg = bn("sg");
    sg.subflow_ref = Some(apsis_ir::SubflowRef { workflow: "child".into(), ..Default::default() });
    let mut parent = bsp(
        vec![sg, bn("b"), bn("c"), bn("s"), bn("j")],
        vec![
            kedge("__start__", "sg", EdgeKind::Control, None),
            kedge("sg", "b", EdgeKind::Control, None),
            kedge("b", "c", EdgeKind::Control, None),
            kedge("c", "j", EdgeKind::Control, None),
            kedge("s", "j", EdgeKind::Control, None),
            kedge("j", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    parent.id = Some("parent".into());
    let mut k = bn("k");
    k.declared_targets = vec!["s".into()];
    k.attrs.insert("command_parent".into(), "true".into());
    let mut child = bsp(vec![k], vec![kedge("__start__", "k", EdgeKind::Control, None)], vec![]);
    child.id = Some("child".into());
    assert!(fired(&ChannelWriteMerge.check(&parent), "channel-write-merge").is_empty());
    let prog = apsis_ir::Program { workflows: vec![parent, child] };
    assert_eq!(fired(&ChannelWriteMerge.check_program(&prog), "channel-write-merge"), vec!["j"]);
}

#[test]
fn list_returning_router_is_a_fanout() {
    let mut r = bn("r");
    r.attrs.insert("router_fanout:route".into(), "true".into());
    let w = bsp(
        vec![r, bn("b"), bn("c"), bn("c2"), bn("d")],
        vec![
            kedge("__start__", "r", EdgeKind::Control, None),
            kedge("r", "b", EdgeKind::Conditional, Some("route")),
            kedge("r", "c", EdgeKind::Conditional, Some("route")),
            kedge("c", "c2", EdgeKind::Control, None),
            kedge("b", "d", EdgeKind::Control, None),
            kedge("c2", "d", EdgeKind::Control, None),
            kedge("d", "__end__", EdgeKind::Control, None),
        ],
        vec![],
    );
    assert_eq!(fired(&ChannelWriteMerge.check(&w), "channel-write-merge"), vec!["d"]);
}

#[test]
fn participant_without_allowed_next_speaker() {
    // restricted transitions: `a` and `b` follow each other, and none starts at `user`
    let agent = |id: &str| Node { id: id.into(), name: Some(id.into()), kind: NodeKind::Agent, ..Default::default() };
    let mut mgr = Node {
        id: "manager".into(),
        kind: NodeKind::Router,
        role: Some("manager".into()),
        declared_targets: vec!["user".into(), "a".into(), "b".into()],
        ..Default::default()
    };
    mgr.attrs.insert("speaker_transitions".into(), "restricted".into());
    let mut w = wf(
        vec![agent("user"), agent("a"), agent("b"), mgr],
        vec![kedge("a", "b", EdgeKind::Handoff, None), kedge("b", "a", EdgeKind::Handoff, None)],
        None,
    );
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    assert_eq!(rule_locations(&TargetResolution.check(&w)), vec!["no-next-speaker@user"]);
    w.edges.push(kedge("user", "a", EdgeKind::Handoff, None));
    assert!(fired(&TargetResolution.check(&w), "target-resolution").is_empty());
    // without the manager's restriction no edge is needed
    w.edges.clear();
    w.nodes[3].attrs.clear();
    assert!(fired(&TargetResolution.check(&w), "target-resolution").is_empty());
}

#[test]
fn explicit_cycle_in_a_group_chat_graph_needs_an_exit() {
    let exec = |id: &str| Node { id: id.into(), kind: NodeKind::Executor, ..Default::default() };
    let mut w = wf(
        vec![exec("drafter"), exec("critic")],
        vec![kedge("drafter", "critic", EdgeKind::Control, None), kedge("critic", "drafter", EdgeKind::Control, None)],
        None,
    );
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    assert_eq!(fired(&CycleTermination.check(&w), "cycle-termination"), vec!["drafter"]);
    w.nodes[1].attrs.insert("workflow_output_types".into(), "str".into());
    assert!(CycleTermination.check(&w).is_empty());
    // an output step with unknown or no output types shows no way out
    w.nodes[1].attrs.clear();
    w.output_nodes = vec!["critic".into()];
    assert_eq!(fired(&CycleTermination.check(&w), "cycle-termination"), vec!["drafter"]);
    w.nodes[1].attrs.insert("workflow_output_types".into(), "".into());
    assert_eq!(fired(&CycleTermination.check(&w), "cycle-termination"), vec!["drafter"]);
    w.nodes[1].attrs.clear();
    w.output_nodes.clear();
    w.nodes.push(exec("publish"));
    w.edges.push(kedge("critic", "publish", EdgeKind::Conditional, Some("approved")));
    assert!(CycleTermination.check(&w).is_empty());
    let agent = |id: &str| Node { id: id.into(), kind: NodeKind::Agent, ..Default::default() };
    let mut chat = wf(
        vec![agent("a"), agent("b")],
        vec![kedge("a", "b", EdgeKind::Handoff, None), kedge("b", "a", EdgeKind::Handoff, None)],
        None,
    );
    chat.execution_model = ExecutionModel::GroupChatSpeaker;
    assert!(CycleTermination.check(&chat).is_empty());
}

#[test]
fn handoff_endpoints_must_be_agents() {
    let agent = |id: &str| Node { id: id.into(), kind: NodeKind::Agent, ..Default::default() };
    let exec = Node { id: "refund".into(), kind: NodeKind::Executor, ..Default::default() };
    let mut w = wf(
        vec![agent("triage"), agent("order"), exec],
        vec![
            kedge("triage", "order", EdgeKind::Handoff, None),
            kedge("triage", "refund", EdgeKind::Handoff, None),
            kedge("order", "refund", EdgeKind::Handoff, None),
        ],
        None,
    );
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    let f = BindingCapability.check(&w);
    assert_eq!(
        f.iter().map(|f| (f.rule, f.location.as_str())).collect::<Vec<_>>(),
        vec![("handoff-to-non-agent", "refund")]
    );
    w.nodes[2].kind = NodeKind::Agent;
    assert!(BindingCapability.check(&w).is_empty());
    w.nodes[2].kind = NodeKind::Executor;
    w.execution_model = ExecutionModel::BspSuperstep;
    assert!(BindingCapability.check(&w).is_empty());
}

#[test]
fn tool_binding_needs_a_declared_tool_output() {
    let agent = Node {
        id: "agent".into(),
        kind: NodeKind::Agent,
        inputs: vec![isock("tools", "Tool", false, false)],
        ..Default::default()
    };
    let search = n("search", vec![], vec![osock("run_model", "Data", false)]);
    let mut e = edge("search", "build_tool", "agent", "tools");
    e.kind = EdgeKind::Tool;
    let mut w = wf(vec![agent, search], vec![e], None);
    w.execution_model = ExecutionModel::VisualDataflow;
    let f = BindingCapability.check(&w);
    assert_eq!(
        f.iter().map(|f| (f.rule, f.location.as_str())).collect::<Vec<_>>(),
        vec![("tool-from-undeclared-output", "search.build_tool")]
    );
    // target-resolution leaves the tool binding to binding-capability
    assert!(fired(&TargetResolution.check(&w), "target-resolution").is_empty());
    w.nodes[1].outputs.push(osock("build_tool", "Tool", false));
    assert!(BindingCapability.check(&w).is_empty());
}

#[test]
fn subflow_request_needs_an_answering_parent_step() {
    let mut ask = Node { id: "ask".into(), kind: NodeKind::Executor, ..Default::default() };
    ask.attrs.insert("request_port".into(), "true".into());
    let mut inner = wf(vec![ask], vec![], None);
    inner.execution_model = ExecutionModel::GroupChatSpeaker;
    inner.id = Some("inner".into());
    let host = Node {
        id: "host".into(),
        kind: NodeKind::Subflow,
        subflow_ref: Some(SubflowRef { workflow: "inner".into(), ..Default::default() }),
        ..Default::default()
    };
    let mut parent = wf(vec![host], vec![], None);
    parent.execution_model = ExecutionModel::GroupChatSpeaker;
    parent.id = Some("parent".into());
    let mut prog = Program { workflows: vec![parent, inner] };
    let rules = |p: &Program| {
        SubflowPortBinding.check_program(p).iter().map(|f| (f.rule, f.location.clone())).collect::<Vec<_>>()
    };
    assert_eq!(rules(&prog), vec![("unanswered-subflow-request", "host".to_string())]);
    prog.workflows[0].nodes[0].subflow_ref.as_mut().unwrap().in_bindings.push(PortBinding {
        outer: SocketRef { node: "answerer".into(), socket: "Response".into() },
        inner: SocketRef { node: "ask".into(), socket: String::new() },
        converted: false,
    });
    assert!(rules(&prog).is_empty());
    prog.workflows[0].nodes[0].subflow_ref.as_mut().unwrap().in_bindings.clear();
    prog.workflows[0].nodes[0].attrs.insert("propagates_requests".into(), "true".into());
    assert!(rules(&prog).is_empty());
}

#[test]
fn shared_state_read_with_no_writer_is_a_stale_read() {
    let mut w = wf(vec![n("reader", vec![], vec![])], vec![], None);
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    w.channels.push(Channel { name: "currency".into(), readers: vec!["reader".into()], ..Default::default() });
    let f = ReadAfterWrite.check(&w);
    assert_eq!(
        f.iter().map(|f| (f.detector, f.rule, f.location.as_str())).collect::<Vec<_>>(),
        vec![("read-after-write", "read-without-writer", "currency")]
    );
    assert!(ChannelWriteMerge.check(&w).is_empty());
    w.channels[0].writers.push("reader".into());
    assert!(ReadAfterWrite.check(&w).is_empty());
    w.channels[0].writers.clear();
    w.execution_model = ExecutionModel::BspSuperstep;
    assert_eq!(ReadAfterWrite.check(&w).len(), 1);
    w.attrs.insert("provided_channels".into(), "currency".into());
    assert!(ReadAfterWrite.check(&w).is_empty());
    w.attrs.clear();
    // under BSP a write of the key in the parent counts
    let mut parent = wf(vec![n("writer", vec![], vec![osock("currency", "str", false)])], vec![], None);
    parent.execution_model = ExecutionModel::BspSuperstep;
    parent.id = Some("main".into());
    w.id = Some("main::sub".into());
    let prog = Program { workflows: vec![parent, w] };
    assert!(ReadAfterWrite.check_program(&prog).is_empty());
}

#[test]
fn every_message_type_needs_a_handler_where_the_consumer_takes_all() {
    let a = n("a", vec![], vec![osock("T", "T", true), osock("U", "U", true)]);
    let mut b = n("b", vec![isock("T", "T", false, false)], vec![]);
    let mut e = edge("a", "", "b", "");
    e.kind = EdgeKind::Control;
    let mut w = wf(vec![a.clone(), b.clone()], vec![e], None);
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    assert!(TypeContract.check(&w).is_empty());
    b.attrs.insert("takes_all_messages".into(), "true".into());
    w.nodes = vec![a, b];
    let f = TypeContract.check(&w);
    assert_eq!(
        f.iter().map(|f| (f.detector, f.rule, f.location.as_str())).collect::<Vec<_>>(),
        vec![("type-contract", "no-handler-for-message", "a->b")]
    );
}

#[test]
fn store_read_must_be_ordered_after_the_write() {
    let mut writer = n("writer", vec![isock("documents", "list[Document]", false, true)], vec![]);
    let mut reader =
        n("retriever", vec![isock("query", "str", false, true)], vec![osock("documents", "list[Document]", false)]);
    writer.store_ref = Some("0xS".into());
    writer.store_role = Some("write".into());
    reader.store_ref = Some("0xS".into());
    reader.store_role = Some("read".into());
    let mut w = wf(vec![writer, reader], vec![], None);
    let f = ReadAfterWrite.check(&w);
    assert_eq!(
        f.iter().map(|f| (f.rule, f.location.as_str())).collect::<Vec<_>>(),
        vec![("unordered-store-read", "retriever")]
    );
    w.nodes.push(n("gate", vec![], vec![]));
    w.edges.push(edge("writer", "", "gate", ""));
    w.edges.push(edge("gate", "", "retriever", "query"));
    assert!(ReadAfterWrite.check(&w).is_empty());
}

#[test]
fn two_steps_that_are_one_object() {
    let mut a = n("a", vec![], vec![]);
    let mut b = n("b", vec![], vec![]);
    a.instance_id = Some("0xDEAD".into());
    b.instance_id = Some("0xDEAD".into());
    let w = wf(vec![a, b], vec![], Some(1));
    let f = SharedInstanceAliasing.check(&w);
    assert!(f.iter().any(|f| f.detector == "shared-instance-aliasing"));
}

/// `start` fans out to `a` and `b`, which send `str` to `agg`, whose one handler takes `handler`.
fn fan_in(handler: &str, delivery: Option<&str>) -> Workflow {
    let exec = |id: &str, inputs: Vec<InputSocket>, outputs: Vec<OutputSocket>| Node {
        kind: NodeKind::Executor,
        ..n(id, inputs, outputs)
    };
    let mut agg = exec("agg", vec![isock("aggregate", handler, false, true)], vec![osock("str", "str", true)]);
    if let Some(d) = delivery {
        agg.attrs.insert(attr::FAN_IN_DELIVERY.into(), d.into());
    }
    let mut w = wf(
        vec![
            exec("start", vec![isock("run", "str", false, true)], vec![osock("str", "str", true)]),
            exec("a", vec![isock("run", "str", false, true)], vec![osock("str", "str", true)]),
            exec("b", vec![isock("run", "str", false, true)], vec![osock("str", "str", true)]),
            agg,
        ],
        vec![
            kedge("start", "a", EdgeKind::Control, None),
            kedge("start", "b", EdgeKind::Control, None),
            kedge("a", "agg", EdgeKind::Control, None),
            kedge("b", "agg", EdgeKind::Control, None),
        ],
        None,
    );
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    w
}

#[test]
fn fan_in_handler_must_match_how_the_fan_in_delivers() {
    let rules = |w: &Workflow| -> Vec<String> {
        TypeContract.check(w).iter().map(|f| format!("{}@{}", f.rule, f.location)).collect()
    };

    assert_eq!(
        rules(&fan_in("str", Some("list"))),
        vec!["no-handler-for-message@a->agg", "no-handler-for-message@b->agg"]
    );
    assert!(rules(&fan_in("list[str]", Some("list"))).is_empty());

    assert!(rules(&fan_in("str", Some("each"))).is_empty());
    assert_eq!(
        rules(&fan_in("list[str]", Some("each"))),
        vec!["no-handler-for-message@a->agg", "no-handler-for-message@b->agg"]
    );

    assert!(rules(&fan_in("str", None)).is_empty());
    assert_eq!(
        rules(&fan_in("list[str]", None)),
        vec!["no-handler-for-message@a->agg", "no-handler-for-message@b->agg"]
    );
}

#[test]
fn a_step_must_declare_what_it_sends_where_declarations_are_checked() {
    let step = |declared: Option<&str>| {
        let mut router = Node {
            kind: NodeKind::Executor,
            ..n(
                "router",
                vec![isock("ChatInput", "ChatInput", false, true)],
                vec![osock("list[Intent]", "list[Intent]", true)],
            )
        };
        if let Some(d) = declared {
            router.attrs.insert(attr::DECLARED_SENDS.into(), d.into());
        }
        let mut w = wf(vec![router], vec![], None);
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        TypeContract.check(&w).iter().map(|f| format!("{}@{}", f.rule, f.location)).collect::<Vec<_>>()
    };
    assert_eq!(step(Some("list[ChatMessage]")), vec!["send-of-undeclared-type@router.list[Intent]"]);
    assert_eq!(step(Some("")), vec!["send-of-undeclared-type@router.list[Intent]"]);
    assert!(step(Some("list[ChatMessage], list[Intent]")).is_empty());
    assert!(step(None).is_empty());
}

#[test]
fn a_sub_workflow_reads_state_only_its_parent_wrote() {
    // the parent writes `Scope/*`; the only step of the embedded `trim` reads it and may write it back
    let case = |trim_writes: bool, reads_first: bool| {
        let host = Node {
            id: "trim_host".into(),
            kind: NodeKind::Subflow,
            subflow_ref: Some(SubflowRef { workflow: "trim".into(), ..Default::default() }),
            ..Default::default()
        };
        let channel = |writers: Vec<&str>, readers: Vec<&str>| Channel {
            name: "Scope/*".into(),
            writers: writers.into_iter().map(String::from).collect(),
            readers: readers.into_iter().map(String::from).collect(),
            ..Default::default()
        };
        let mut parent =
            wf(vec![n("read", vec![], vec![]), host], vec![kedge("read", "trim_host", EdgeKind::Control, None)], None);
        parent.execution_model = ExecutionModel::GroupChatSpeaker;
        parent.channels = vec![channel(vec!["read"], vec![])];
        let mut step = n("trim_step", vec![], vec![]);
        if reads_first {
            step.attrs.insert(attr::READS_BEFORE_WRITE.into(), "Scope/*".into());
        }
        let mut sub = wf(vec![step], vec![], None);
        sub.id = Some("trim".into());
        sub.execution_model = ExecutionModel::GroupChatSpeaker;
        sub.channels = vec![channel(if trim_writes { vec!["trim_step"] } else { vec![] }, vec!["trim_step"])];
        SubflowPortBinding
            .check_program(&Program { workflows: vec![parent, sub] })
            .iter()
            .map(|f| f.rule)
            .collect::<Vec<_>>()
    };
    assert_eq!(case(false, false), vec!["unbridged-shared-state"]); // read, never written inside
    assert_eq!(case(true, true), vec!["unbridged-shared-state"]); // written back only after the read
    assert!(case(true, false).is_empty()); // written inside before it is read
}

#[test]
fn one_workflow_object_for_every_caller() {
    let mut w =
        wf(vec![n("start", vec![], vec![]), n("end", vec![], vec![])], vec![edge("start", "", "end", "")], None);
    w.id = Some("pricing".into());
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    assert!(SharedInstanceAliasing.check(&w).is_empty());
    w.attrs.insert(attr::SHARED_WORKFLOW.into(), "true".into());
    let f = SharedInstanceAliasing.check(&w);
    assert_eq!(
        f.iter().map(|f| (f.rule, f.location.as_str())).collect::<Vec<_>>(),
        vec![("shared-workflow-instance", "pricing")]
    );
}

#[test]
fn a_subclass_message_reaches_a_handler_of_its_base_where_dispatch_follows_instances() {
    let case = |supertypes: Option<&str>| {
        let exec = |id: &str, inputs: Vec<InputSocket>, outputs: Vec<OutputSocket>| Node {
            kind: NodeKind::Executor,
            ..n(id, inputs, outputs)
        };
        let mut sender =
            exec("dispatch", vec![isock("run", "str", false, true)], vec![osock("Derived", "Derived", true)]);
        if let Some(s) = supertypes {
            sender.attrs.insert(format!("{}Derived", attr::SUPERTYPES), s.into());
        }
        let receiver = exec("introspect", vec![isock("handle", "Base", false, true)], vec![]);
        let mut w = wf(vec![sender, receiver], vec![kedge("dispatch", "introspect", EdgeKind::Control, None)], None);
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        TypeContract.check(&w).iter().map(|f| f.rule).collect::<Vec<_>>()
    };
    assert_eq!(case(None), vec!["no-handler-for-message"]);
    assert!(case(Some("Base")).is_empty());
}

#[test]
fn a_send_of_a_subtype_of_a_declared_type_passes_the_protocol_check() {
    let case = |supertypes: Option<&str>| {
        let mut sender = Node {
            kind: NodeKind::Executor,
            ..n("dispatch", vec![isock("run", "str", false, true)], vec![osock("Derived", "Derived", true)])
        };
        sender.attrs.insert(attr::DECLARED_SENDS.into(), "Base".into());
        if let Some(s) = supertypes {
            sender.attrs.insert(format!("{}Derived", attr::SUPERTYPES), s.into());
        }
        let mut w = wf(vec![sender], vec![], None);
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        TypeContract.check(&w).iter().map(|f| f.rule).collect::<Vec<_>>()
    };
    assert_eq!(case(None), vec!["send-of-undeclared-type"]);
    assert!(case(Some("Base, IMark")).is_empty());
}

#[test]
fn a_step_without_inputs_is_never_scheduled() {
    let mut w = wf(
        vec![
            n("retriever", vec![], vec![osock("documents", "list[Document]", false)]),
            n("answer", vec![isock("documents", "list[Document]", false, true)], vec![]),
        ],
        vec![edge("retriever", "documents", "answer", "documents")],
        None,
    );
    assert_eq!(rule_locations(&ReadinessLiveness.check(&w)), vec!["no-input-component@retriever"]);
    w.nodes[0].inputs.push(isock("query", "str", true, false));
    assert!(ReadinessLiveness.check(&w).is_empty());
    w.nodes[0].inputs.clear();
    w.execution_model = ExecutionModel::VisualDataflow;
    assert!(ReadinessLiveness.check(&w).is_empty());
}

#[test]
fn a_sink_fed_only_by_outputs_that_may_be_omitted_can_get_no_value() {
    let mut w = wf(
        vec![
            n("router", vec![isock("query", "str", false, true)], vec![osock("yes", "str", true)]),
            n("reply", vec![isock("text", "str", false, true)], vec![]),
        ],
        vec![edge("router", "yes", "reply", "text")],
        None,
    );
    assert_eq!(rule_locations(&ReadinessLiveness.check(&w)), vec!["conditional-producers-only@reply.text"]);
    w.nodes[0].outputs[0].may_emit = false;
    assert!(ReadinessLiveness.check(&w).is_empty());
    // two starvable sinks are the router's alternative outputs
    w.nodes[0].outputs[0].may_emit = true;
    w.nodes[0].outputs.push(osock("no", "str", true));
    w.nodes.push(n("fallback", vec![isock("text", "str", false, true)], vec![]));
    w.edges.push(edge("router", "no", "fallback", "text"));
    assert!(ReadinessLiveness.check(&w).is_empty());
}

#[test]
fn a_prompt_whose_template_values_input_is_not_wired_renders_empty() {
    let mut prompt =
        n("prompt", vec![isock("promptValues", "json", false, false)], vec![osock("prompt", "str", false)]);
    prompt.requires_vars = vec!["topic".into()];
    prompt.attrs.insert(attr::TEMPLATE_VALUES_INPUT.into(), "promptValues".into());
    let mut w = wf(vec![prompt], vec![], None);
    w.execution_model = ExecutionModel::VisualDataflow;
    assert_eq!(rule_locations(&ReadinessLiveness.check(&w)), vec!["unbound-template-variable@prompt"]);
    w.nodes.push(n("values", vec![], vec![osock("json", "json", false)]));
    w.edges.push(edge("values", "json", "prompt", "promptValues"));
    assert!(ReadinessLiveness.check(&w).is_empty());
}

#[test]
fn a_loop_whose_input_comes_only_from_its_own_body_never_starts() {
    let lp = Node {
        kind: NodeKind::Loop,
        ..n("loop", vec![isock("data", "list[Data]", false, true)], vec![osock("item", "Data", false)])
    };
    let body = n("body", vec![isock("item", "Data", false, true)], vec![osock("result", "list[Data]", false)]);
    let mut w =
        wf(vec![lp, body], vec![edge("loop", "item", "body", "item"), edge("body", "result", "loop", "data")], None);
    w.execution_model = ExecutionModel::VisualDataflow;
    assert_eq!(rule_locations(&ReadinessLiveness.check(&w)), vec!["loop-seeded-from-own-cycle@loop.data"]);
    w.nodes.push(n("source", vec![], vec![osock("data", "list[Data]", false)]));
    w.edges.push(edge("source", "data", "loop", "data"));
    assert!(ReadinessLiveness.check(&w).is_empty());
}

#[test]
fn a_step_that_sends_nothing_cannot_feed_a_required_input() {
    let case = |sent: &str| {
        let exec = |id: &str, inputs: Vec<InputSocket>, outputs: Vec<OutputSocket>| Node {
            kind: NodeKind::Executor,
            ..n(id, inputs, outputs)
        };
        let mut w = wf(
            vec![
                exec("logger", vec![isock("run", "str", false, true)], vec![osock(sent, sent, true)]),
                exec("summarize", vec![isock("handle", "str", false, true)], vec![]),
            ],
            vec![kedge("logger", "summarize", EdgeKind::Control, None)],
            None,
        );
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        rule_locations(&TypeContract.check(&w))
    };
    assert_eq!(case("Never"), vec!["never-emitter-into-required-input@logger->summarize"]);
    assert!(case("str").is_empty());
}

#[test]
fn a_message_posted_to_the_group_that_a_member_handed_everything_cannot_take() {
    let case = |takes_all: bool| {
        let writer = n("writer", vec![], vec![osock("T", "T", true), osock("U", "U", true)]);
        let mut reader = n("reader", vec![isock("T", "T", false, false)], vec![]);
        if takes_all {
            reader.attrs.insert(attr::TAKES_ALL_MESSAGES.into(), "true".into());
        }
        let mut w = wf(vec![writer, reader], vec![], None);
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        w.channels.push(Channel {
            name: "messages".into(),
            writers: vec!["writer".into(), "reader".into()],
            readers: vec!["writer".into(), "reader".into()],
            ..Default::default()
        });
        rule_locations(&TypeContract.check(&w))
    };
    assert_eq!(case(true), vec!["no-handler-for-message@writer->reader"]);
    assert!(case(false).is_empty());
}

#[test]
fn a_stream_into_a_step_that_does_not_take_one() {
    let case = |accepts_stream: bool| {
        let mut model = n("model", vec![], vec![]);
        model.attrs.insert(attr::STREAM.into(), "true".into());
        let mut sink = n("sink", vec![], vec![]);
        if accepts_stream {
            sink.attrs.insert(attr::ACCEPTS_STREAM.into(), "true".into());
        }
        let mut w = wf(vec![model, sink], vec![edge("model", "text_output", "sink", "input_value")], None);
        w.execution_model = ExecutionModel::VisualDataflow;
        rule_locations(&TypeContract.check(&w))
    };
    assert_eq!(case(false), vec!["stream-into-non-chat-sink@model->sink"]);
    assert!(case(true).is_empty());
}

#[test]
fn a_loop_that_loops_back_to_a_step_that_cannot_run_its_body() {
    let case = |target: NodeKind| {
        let lp = Node {
            id: "loop".into(),
            kind: NodeKind::Loop,
            declared_targets: vec!["next".into()],
            ..Default::default()
        };
        let next = Node { id: "next".into(), kind: target, ..Default::default() };
        let mut w = wf(vec![lp, next], vec![], None);
        w.execution_model = ExecutionModel::VisualDataflow;
        rule_locations(&TypeContract.check(&w))
    };
    assert_eq!(case(NodeKind::Router), vec!["loop-target-cannot-host-body@loop->next"]);
    assert!(case(NodeKind::Component).is_empty());
}

#[test]
fn an_edge_to_a_step_that_does_not_exist() {
    let case = |target: &str| {
        rule_locations(&TargetResolution.check(&wf(
            vec![n("a", vec![], vec![])],
            vec![edge("a", "", target, "")],
            None,
        )))
    };
    assert_eq!(case("summarizer"), vec!["unresolved-edge-endpoint@summarizer"]);
    assert!(case(END).is_empty());
}

#[test]
fn a_wire_from_an_output_the_step_does_not_declare() {
    let case = |socket: &str| {
        let w = wf(
            vec![
                n("llm", vec![], vec![osock("replies", "list[str]", false)]),
                n("parser", vec![isock("text", "list[str]", false, true)], vec![]),
            ],
            vec![edge("llm", socket, "parser", "text")],
            None,
        );
        rule_locations(&TargetResolution.check(&w))
    };
    assert_eq!(case("reply"), vec!["undeclared-output-port@llm.reply"]);
    assert!(case("replies").is_empty());
}

#[test]
fn a_router_that_reads_a_channel_its_input_schema_filters_out() {
    let case = |filtered: &str| {
        let mut route = bn("route");
        route.attrs.insert(attr::ROUTER_FILTERED_READS.into(), filtered.into());
        let w = bsp(vec![route], vec![kedge(START, "route", EdgeKind::Control, None)], vec![]);
        rule_locations(&TargetResolution.check(&w))
    };
    assert_eq!(case("documents"), vec!["stale-route@route"]);
    assert!(case("").is_empty());
}

#[test]
fn a_router_that_has_no_route() {
    let router = Node { id: "condition".into(), kind: NodeKind::Router, ..Default::default() };
    let mut w = wf(vec![router, n("next", vec![], vec![])], vec![], None);
    w.execution_model = ExecutionModel::VisualDataflow;
    assert_eq!(rule_locations(&TargetResolution.check(&w)), vec!["router-without-route@condition"]);
    w.edges.push(kedge("condition", "next", EdgeKind::Conditional, Some("true")));
    assert!(TargetResolution.check(&w).is_empty());
    // under BSP a route may be computed at run time
    w.edges.clear();
    w.execution_model = ExecutionModel::BspSuperstep;
    assert!(TargetResolution.check(&w).is_empty());
}

#[test]
fn a_participant_name_must_be_a_valid_routing_key() {
    let case = |name: &str| {
        let agent =
            Node { id: "researcher".into(), name: Some(name.into()), kind: NodeKind::Agent, ..Default::default() };
        let mut w = wf(vec![agent], vec![], None);
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        rule_locations(&TargetResolution.check(&w))
    };
    assert_eq!(case("research assistant"), vec!["invalid-participant-name@researcher"]);
    assert_eq!(case(""), vec!["invalid-participant-name@researcher"]);
    assert!(case("research_assistant").is_empty());
}

#[test]
fn a_start_agent_that_can_hand_off_to_nobody() {
    let agent = |id: &str| Node { id: id.into(), kind: NodeKind::Agent, ..Default::default() };
    let mut w = wf(
        vec![agent("triage"), agent("billing"), agent("refunds")],
        vec![kedge("billing", "refunds", EdgeKind::Handoff, None)],
        None,
    );
    w.execution_model = ExecutionModel::GroupChatSpeaker;
    w.start_nodes = vec!["triage".into()];
    assert_eq!(rule_locations(&TargetResolution.check(&w)), vec!["coordinator-without-handoff@triage"]);
    w.edges.push(kedge("triage", "billing", EdgeKind::Handoff, None));
    assert!(TargetResolution.check(&w).is_empty());
}

#[test]
fn a_tool_that_an_agent_can_propose_and_no_agent_can_execute() {
    let case = |has_executor: &str| {
        let mut tool = Node { id: "get_weather".into(), kind: NodeKind::Tool, ..Default::default() };
        tool.attrs.insert(attr::CALLERS.into(), "assistant".into());
        tool.attrs.insert(attr::HAS_EXECUTOR.into(), has_executor.into());
        let assistant = Node { id: "assistant".into(), kind: NodeKind::Agent, ..Default::default() };
        let mut w = wf(vec![assistant, tool], vec![], None);
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        rule_locations(&TargetResolution.check(&w))
    };
    assert_eq!(case("false"), vec!["tool-without-executor@get_weather"]);
    assert!(case("true").is_empty());
}

#[test]
fn a_branch_head_that_reaches_the_head_of_another_branch() {
    let mut condition = Node { id: "condition".into(), kind: NodeKind::Router, ..Default::default() };
    condition.attrs.insert(attr::BRANCH_OUTPUTS.into(), attr::BRANCH_TRANSITION.into());
    let mut w = wf(
        vec![condition, n("approve", vec![], vec![]), n("reject", vec![], vec![])],
        vec![
            kedge("condition", "approve", EdgeKind::Conditional, Some("true")),
            kedge("condition", "reject", EdgeKind::Conditional, Some("false")),
            kedge("approve", "reject", EdgeKind::Control, None),
        ],
        None,
    );
    w.execution_model = ExecutionModel::VisualDataflow;
    assert_eq!(rule_locations(&RouterBranchGating.check(&w)), vec!["cross-branch-path@reject"]);
    w.edges.pop();
    assert!(RouterBranchGating.check(&w).is_empty());
}

#[test]
fn a_data_gate_branch_output_that_is_not_wired() {
    let mut router = Node {
        kind: NodeKind::Router,
        ..n(
            "router",
            vec![isock("input_text", "str", false, true)],
            vec![osock("true_result", "Message", true), osock("false_result", "Message", true)],
        )
    };
    router.attrs.insert(attr::BRANCH_OUTPUTS.into(), attr::BRANCH_DATA_GATE.into());
    let branch_edge = |socket: &str, label: &str, to: &str| Edge {
        kind: EdgeKind::Conditional,
        branch: Some(label.into()),
        ..edge("router", socket, to, "input_value")
    };
    let consumer = |id: &str| n(id, vec![isock("input_value", "Message", false, true)], vec![]);
    let mut w = wf(
        vec![router, consumer("on_true"), consumer("on_false")],
        vec![branch_edge("true_result", "true", "on_true")],
        None,
    );
    w.execution_model = ExecutionModel::VisualDataflow;
    assert_eq!(rule_locations(&RouterBranchGating.check(&w)), vec!["skipped-branch@router.false_result"]);
    w.edges.push(branch_edge("false_result", "false", "on_false"));
    assert!(RouterBranchGating.check(&w).is_empty());
}

#[test]
fn a_router_edge_that_is_not_a_branch() {
    let case = |to_support: Edge| {
        let classify = Node {
            kind: NodeKind::Router,
            ..n("classify", vec![], vec![osock("billing", "str", true), osock("support", "str", true)])
        };
        let mut w = wf(
            vec![classify, n("billing", vec![], vec![]), n("support", vec![], vec![])],
            vec![kedge("classify", "billing", EdgeKind::Conditional, Some("billing")), to_support],
            None,
        );
        w.execution_model = ExecutionModel::VisualDataflow;
        rule_locations(&RouterBranchGating.check(&w))
    };
    assert_eq!(case(kedge("classify", "support", EdgeKind::Data, None)), vec!["ungated-branch-edge@classify->support"]);
    assert!(case(kedge("classify", "support", EdgeKind::Conditional, Some("support"))).is_empty());
}

#[test]
fn a_reducer_channel_whose_type_admits_none() {
    let case = |type_repr: &str, reducer: Reducer| {
        let ch = Channel { name: "messages".into(), type_repr: type_repr.into(), reducer, ..Default::default() };
        rule_locations(&ChannelWriteMerge.check(&bsp(vec![], vec![], vec![ch])))
    };
    let add = || Reducer::BinaryOp("operator.add".into());
    assert_eq!(case("Optional[list[str]]", add()), vec!["nullable-reducer-channel@messages"]);
    assert!(case("list[str]", add()).is_empty());
    assert!(case("Optional[list[str]]", Reducer::LastValue).is_empty());
}

#[test]
fn two_steps_that_embed_one_sub_workflow_object() {
    let host = |id: &str, inner: &str| Node {
        id: id.into(),
        kind: NodeKind::Subflow,
        subflow_ref: Some(SubflowRef { workflow: inner.into(), ..Default::default() }),
        ..Default::default()
    };
    let w = wf(vec![host("draft", "writer"), host("revise", "writer")], vec![], None);
    assert_eq!(rule_locations(&SharedInstanceAliasing.check(&w)), vec!["shared-subworkflow-instance@draft"]);
    let w2 = wf(vec![host("draft", "writer"), host("revise", "editor")], vec![], None);
    assert!(SharedInstanceAliasing.check(&w2).is_empty());
}

#[test]
fn an_agent_that_starts_a_nested_chat_it_takes_part_in() {
    let case = |trigger: &str| {
        let agent = |id: &str| Node { id: id.into(), kind: NodeKind::Agent, ..Default::default() };
        let mut w = wf(
            vec![agent("user"), agent("controller"), agent("writer"), agent("critic")],
            vec![
                kedge(trigger, "controller", EdgeKind::Control, Some(branch::NESTED_CHAT_TRIGGER)),
                kedge("controller", "writer", EdgeKind::Subflow, Some(branch::NESTED_CHAT)),
                kedge("controller", "critic", EdgeKind::Subflow, Some(branch::NESTED_CHAT)),
            ],
            None,
        );
        w.execution_model = ExecutionModel::GroupChatSpeaker;
        rule_locations(&BindingCapability.check(&w))
    };
    assert_eq!(case("writer"), vec!["nested-chat-self-trigger@writer"]);
    assert!(case("user").is_empty());
}

#[test]
fn a_route_into_the_parent_graph_is_not_a_double_route() {
    // sub-workflow step `tools` has a static edge back to `agent` and hands off to the parent's `billing`
    let case = |targets: &[&str]| {
        let mut host = bn("assistant");
        host.subflow_ref = Some(SubflowRef { workflow: "assistant".into(), ..Default::default() });
        let mut parent = bsp(
            vec![host, bn("billing")],
            vec![kedge(START, "assistant", EdgeKind::Control, None), kedge("billing", END, EdgeKind::Control, None)],
            vec![],
        );
        parent.id = Some("main".into());
        let mut tools = bn("tools");
        tools.declared_targets = targets.iter().map(|t| t.to_string()).collect();
        tools.attrs.insert(attr::COMMAND_PARENT.into(), "true".into());
        let mut edges = vec![
            kedge(START, "agent", EdgeKind::Control, None),
            kedge("agent", "tools", EdgeKind::Conditional, Some("tools_condition")),
            kedge("agent", END, EdgeKind::Conditional, Some("tools_condition")),
            kedge("tools", "agent", EdgeKind::Control, None),
        ];
        edges.extend(targets.iter().map(|t| kedge("tools", t, EdgeKind::Handoff, None)));
        let mut child = bsp(vec![bn("agent"), tools, bn("review")], edges, vec![]);
        child.id = Some("assistant".into());
        rule_locations(&TargetResolution.check_program(&Program { workflows: vec![parent, child] }))
    };
    assert!(case(&["billing"]).is_empty());
    // `review` is a step of the sub-workflow
    assert_eq!(case(&["billing", "review"]), vec!["double-route@tools->agent"]);
}

/// Data-gate router `r`: output `t` feeds `p1`, `second_output` feeds `p2`, and an AND-join `j` takes both.
fn data_gate_join(second_output: &str) -> Workflow {
    let mut attrs = std::collections::BTreeMap::new();
    attrs.insert("branch_outputs".to_string(), "data-gate".to_string());
    let router = Node {
        id: "r".into(),
        kind: NodeKind::Router,
        outputs: vec![osock("t", "Message", true), osock("f", "Message", true)],
        attrs,
        ..Default::default()
    };
    let mut join = n("j", vec![isock("a", "Message", false, false), isock("b", "Message", false, false)], vec![]);
    join.attrs.insert("activation".into(), "all".into());
    let cond = |out: &str, to: &str| Edge { kind: EdgeKind::Conditional, branch: Some(out.into()), ..edge("r", out, to, "x") };
    let mut w = wf(
        vec![
            router,
            n("p1", vec![isock("x", "Message", false, false)], vec![osock("o", "Message", false)]),
            n("p2", vec![isock("x", "Message", false, false)], vec![osock("o", "Message", false)]),
            join,
        ],
        vec![cond("t", "p1"), cond(second_output, "p2"), edge("p1", "o", "j", "a"), edge("p2", "o", "j", "b")],
        None,
    );
    w.execution_model = ExecutionModel::VisualDataflow;
    w
}

#[test]
fn a_join_of_the_two_outputs_of_a_data_gate_router_waits_forever() {
    let f = findings(&data_gate_join("f"));
    assert!(f.iter().any(|f| f.rule == "deadlocked-join" && f.location == "j"));
    let f = findings(&data_gate_join("t"));
    assert!(!f.iter().any(|f| f.rule == "deadlocked-join"));
}

/// A loop `l` on a cycle with its body `b`, seeded by `src`. `outside` feeds the body when `with_outside_input`.
fn eager_loop(with_outside_input: bool) -> Workflow {
    let mut l = n("l", vec![isock("data", "Data", false, true)], vec![osock("item", "Data", true), osock("done", "Data", true)]);
    l.kind = NodeKind::Loop;
    l.attrs.insert("eager_start".into(), "true".into());
    let mut nodes = vec![
        n("src", vec![], vec![osock("data", "Data", false)]),
        l,
        n("b", vec![isock("x", "Data", false, false), isock("y", "Message", false, false)], vec![osock("o", "Data", false)]),
    ];
    let mut edges = vec![edge("src", "data", "l", "data"), edge("l", "item", "b", "x"), edge("b", "o", "l", "item")];
    if with_outside_input {
        nodes.push(n("outside", vec![], vec![osock("o", "Message", false)]));
        edges.push(edge("outside", "o", "b", "y"));
    }
    let mut w = wf(nodes, edges, None);
    w.execution_model = ExecutionModel::VisualDataflow;
    w
}

#[test]
fn an_eager_loop_can_start_before_its_seed_when_another_step_feeds_its_body() {
    let f = findings(&eager_loop(true));
    assert!(f.iter().any(|f| f.rule == "premature-default" && f.location == "l.data"));
    let f = findings(&eager_loop(false));
    assert!(!f.iter().any(|f| f.rule == "premature-default"));
}

fn bind(outer_node: &str, outer: &str, inner_node: &str, inner: &str) -> PortBinding {
    PortBinding {
        outer: SocketRef { node: outer_node.into(), socket: outer.into() },
        inner: SocketRef { node: inner_node.into(), socket: inner.into() },
        converted: false,
    }
}
fn chan(name: &str, reducer: Reducer, writers: &[&str], readers: &[&str]) -> Channel {
    Channel {
        name: name.into(),
        type_repr: "list[str]".into(),
        reducer,
        writers: writers.iter().map(|s| s.to_string()).collect(),
        readers: readers.iter().map(|s| s.to_string()).collect(),
    }
}
fn ctl(a: &str, b: &str) -> Edge {
    let mut e = edge(a, "", b, "");
    e.kind = EdgeKind::Control;
    e
}
/// A bulk-synchronous parent `START -> host -> END` whose step `host` embeds `inner` (`START -> step -> END`).
fn bsp_pair(parent_channels: Vec<Channel>, inner_channels: Vec<Channel>) -> Program {
    let mut inner = wf(vec![n("step", vec![], vec![])], vec![ctl(START, "step"), ctl("step", END)], None);
    inner.execution_model = ExecutionModel::BspSuperstep;
    inner.id = Some("inner".into());
    inner.start_nodes = vec!["step".into()];
    inner.channels = inner_channels;
    let host = Node {
        id: "host".into(),
        kind: NodeKind::Subflow,
        subflow_ref: Some(SubflowRef { workflow: "inner".into(), ..Default::default() }),
        ..Default::default()
    };
    let mut parent = wf(vec![host], vec![ctl(START, "host"), ctl("host", END)], None);
    parent.execution_model = ExecutionModel::BspSuperstep;
    parent.id = Some("parent".into());
    parent.channels = parent_channels;
    Program { workflows: vec![parent, inner] }
}
fn rules_of(fs: Vec<Finding>) -> Vec<(&'static str, String)> {
    fs.iter().map(|f| (f.rule, f.location.clone())).collect()
}

#[test]
fn bsp_subflow_channel_read_before_any_write_must_be_handed_over() {
    let mut prog = bsp_pair(vec![], vec![chan("count", Reducer::LastValue, &["step"], &["step"])]);
    let rules = |p: &Program| rules_of(SubflowPortBinding.check_program(p));
    assert_eq!(rules(&prog), vec![("unbridged-shared-state", "host".to_string())]);
    prog.workflows[0].nodes[0].subflow_ref.as_mut().unwrap().in_bindings.push(bind("host", "count", START, "count"));
    assert!(rules(&prog).is_empty());
    prog.workflows[0].nodes[0].subflow_ref.as_mut().unwrap().in_bindings.clear();
    prog.workflows[1].attrs.insert("keeps_state".into(), "true".into());
    assert!(rules(&prog).is_empty());
    // a self-loop orders the write before the next read
    prog.workflows[1].attrs.clear();
    prog.workflows[1].edges.push(ctl("step", "step"));
    assert!(rules(&prog).is_empty());
}

/// Visual host `run` binds its `Data` output `result` to the `Message` output `out.text` of `inner`.
fn run_flow(converted: bool) -> Program {
    let mut inner = wf(vec![n("out", vec![], vec![osock("text", "Message", false)])], vec![], None);
    inner.execution_model = ExecutionModel::VisualDataflow;
    inner.id = Some("inner".into());
    let host = Node {
        id: "run".into(),
        kind: NodeKind::Subflow,
        outputs: vec![osock("result", "Data", false)],
        subflow_ref: Some(SubflowRef {
            workflow: "inner".into(),
            out_bindings: vec![PortBinding { converted, ..bind("run", "result", "out", "text") }],
            ..Default::default()
        }),
        ..Default::default()
    };
    let mut parent = wf(vec![host], vec![], None);
    parent.execution_model = ExecutionModel::VisualDataflow;
    parent.id = Some("main".into());
    Program { workflows: vec![parent, inner] }
}

#[test]
fn a_value_handed_back_across_the_boundary_must_fit_the_output() {
    assert_eq!(
        rules_of(TypeContract.check_program(&run_flow(false))),
        vec![("edge-type-mismatch", "out.text->run.result".to_string())]
    );
    assert!(rules_of(TypeContract.check_program(&run_flow(true))).is_empty());
}

#[test]
fn an_output_bound_to_an_inner_output_needs_it_to_exist() {
    let mut prog = run_flow(true);
    assert!(rules_of(SubflowPortBinding.check_program(&prog)).is_empty());
    prog.workflows[0].nodes[0].subflow_ref.as_mut().unwrap().out_bindings[0].inner.socket = "message".into();
    assert_eq!(rules_of(SubflowPortBinding.check_program(&prog)), vec![("unbound-subflow-output", "run.result".to_string())]);
    prog.workflows[0].nodes[0].subflow_ref.as_mut().unwrap().out_bindings[0].inner.node = "gone".into();
    assert_eq!(rules_of(SubflowPortBinding.check_program(&prog)), vec![("unbound-subflow-output", "run.result".to_string())]);
}
