//! Relations over the IR graph: successors, reachability, strongly connected components, distances, fan-out.

use apsis_ir::{attr, Edge, EdgeKind, Program, Workflow};
use std::collections::{BTreeSet, HashMap};

pub(crate) type Succ<'a> = HashMap<&'a str, Vec<&'a str>>;

pub(crate) fn succ_over<'a>(wf: &'a Workflow, keep: impl Fn(&Edge) -> bool) -> Succ<'a> {
    let mut m: Succ = HashMap::new();
    for e in wf.edges.iter().filter(|e| keep(e)) {
        m.entry(e.from.node.as_str()).or_default().push(e.to.node.as_str());
    }
    m
}

pub(crate) fn succ_map(wf: &Workflow) -> Succ<'_> {
    succ_over(wf, |_| true)
}

pub(crate) fn is_routing_edge(e: &Edge) -> bool {
    matches!(e.kind, EdgeKind::Control | EdgeKind::Conditional | EdgeKind::Handoff)
}

/// Taken every time its source completes.
pub(crate) fn is_static_edge(e: &Edge) -> bool {
    matches!(e.kind, EdgeKind::Control) && e.branch.is_none()
}

/// A path of at least one edge leads from `from` to `to`.
pub(crate) fn reaches(succ: &Succ, from: &str, to: &str) -> bool {
    let mut stack: Vec<&str> = succ.get(from).cloned().unwrap_or_default();
    let mut seen = BTreeSet::new();
    while let Some(cur) = stack.pop() {
        if cur == to {
            return true;
        }
        if !seen.insert(cur) {
            continue;
        }
        if let Some(ss) = succ.get(cur) {
            stack.extend(ss.iter().copied());
        }
    }
    false
}

pub(crate) fn reaches_or_eq(succ: &Succ, from: &str, to: &str) -> bool {
    from == to || reaches(succ, from, to)
}

pub(crate) fn unordered(succ: &Succ, a: &str, b: &str) -> bool {
    !reaches(succ, a, b) && !reaches(succ, b, a)
}

/// The steps reached by a path of at least one edge.
pub(crate) fn reachable_from<'a>(succ: &Succ<'a>, from: &str) -> BTreeSet<&'a str> {
    let mut seen = BTreeSet::new();
    let mut stack: Vec<&str> = succ.get(from).cloned().unwrap_or_default();
    while let Some(cur) = stack.pop() {
        if seen.insert(cur) {
            stack.extend(succ.get(cur).into_iter().flatten().copied());
        }
    }
    seen
}

pub(crate) fn reaches_any(succ: &Succ, from: &str, targets: &BTreeSet<&str>) -> bool {
    targets.contains(from) || targets.iter().any(|t| reaches(succ, from, t))
}

/// SCCs under `succ`, singletons included, in `wf.nodes` order (a component's first member is its first step).
pub(crate) fn sccs<'a>(wf: &'a Workflow, succ: &Succ) -> Vec<Vec<&'a str>> {
    let ids: Vec<&str> = wf.nodes.iter().map(|n| n.id.as_str()).collect();
    let mut assigned: BTreeSet<&str> = BTreeSet::new();
    let mut comps = Vec::new();
    for &a in &ids {
        if !assigned.insert(a) {
            continue;
        }
        let mut comp = vec![a];
        for &b in &ids {
            if !assigned.contains(b) && reaches(succ, a, b) && reaches(succ, b, a) {
                assigned.insert(b);
                comp.push(b);
            }
        }
        comps.push(comp);
    }
    comps
}

pub(crate) fn is_cycle(comp: &[&str], succ: &Succ) -> bool {
    comp.len() > 1 || succ.get(comp[0]).is_some_and(|ss| ss.contains(&comp[0]))
}

/// Shortest path length from any of `starts`.
pub(crate) fn distances<'a>(succ: &Succ<'a>, starts: &[&'a str]) -> HashMap<&'a str, usize> {
    let mut dist: HashMap<&str, usize> = starts.iter().map(|&s| (s, 0)).collect();
    let mut frontier: Vec<&str> = starts.to_vec();
    let mut d = 0;
    while !frontier.is_empty() {
        d += 1;
        let mut next = Vec::new();
        for cur in frontier {
            for &nxt in succ.get(cur).into_iter().flatten() {
                if !dist.contains_key(nxt) {
                    dist.insert(nxt, d);
                    next.push(nxt);
                }
            }
        }
        frontier = next;
    }
    dist
}

/// The input has a default, or an edge from an output that every run produces.
pub(crate) fn must_fed(wf: &Workflow, node: &str, socket: &str, has_default: bool) -> bool {
    let may_emit = |e: &Edge| wf.node(&e.from.node).and_then(|n| n.output(&e.from.socket)).is_some_and(|o| o.may_emit);
    has_default || wf.edges_into(node, socket).any(|e| !may_emit(e))
}

/// Edges that activate every successor at once: static edges and the edges of a list-returning router.
pub(crate) fn fanout_succ_map(wf: &Workflow) -> Succ<'_> {
    let list_routers: BTreeSet<&str> = wf
        .nodes
        .iter()
        .filter(|n| n.branch_attrs(attr::ROUTER_FANOUT).next().is_some())
        .map(|n| n.id.as_str())
        .collect();
    let mut m = succ_over(wf, is_static_edge);
    for e in &wf.edges {
        if matches!(e.kind, EdgeKind::Conditional) && list_routers.contains(e.from.node.as_str()) {
            m.entry(e.from.node.as_str()).or_default().push(e.to.node.as_str());
        }
    }
    m
}

/// Some step fans out to two distinct successors, one of which is or reaches `a` and the other `b`.
pub(crate) fn parallel_siblings(succ: &Succ, fanout_succ: &Succ, a: &str, b: &str) -> bool {
    fanout_succ.values().any(|outs| {
        outs.iter().any(|&x| outs.iter().any(|&y| x != y && reaches_or_eq(succ, x, a) && reaches_or_eq(succ, y, b)))
    })
}

/// Fan-out edges `(n, t)` only the program shows: a workflow embedded by `n` routes to `t` (`command_parent`).
pub(crate) fn cross_graph_fanout<'a>(prog: &'a Program, wf: &'a Workflow) -> Vec<(&'a str, &'a str)> {
    let mut out = Vec::new();
    for n in &wf.nodes {
        let Some(child) = n.subflow_ref.as_ref().and_then(|r| prog.workflow(&r.workflow)) else { continue };
        for m in child.nodes.iter().filter(|m| m.flag(attr::COMMAND_PARENT)) {
            for t in m.declared_targets.iter().filter(|t| wf.node(t).is_some()) {
                out.push((n.id.as_str(), t.as_str()));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_distance_is_the_shortest_one() {
        // `a` is one step from `s` directly and three through `b` and `c`
        let succ: Succ = HashMap::from([("s", vec!["a", "b"]), ("b", vec!["c"]), ("c", vec!["a"]), ("a", vec!["s"])]);
        let dist = distances(&succ, &["s"]);
        assert_eq!(dist.get("s"), Some(&0));
        assert_eq!(dist.get("a"), Some(&1));
        assert_eq!(dist.get("b"), Some(&1));
        assert_eq!(dist.get("c"), Some(&2));
    }
}
