/**
 * @name Cycle with no exit
 * @description A node lies on a cycle it cannot leave: it reaches no off-cycle node and originates no conditional edge.
 * @kind problem
 * @problem.severity warning
 * @id apsis-baseline/cycle-termination
 */

import python
import lib.LangGraphGraph
import lib.HaystackGraph

predicate gEdge(Call site, string a, string b) {
  lgEdge(site, a, b)
  or
  exists(ConnectCall c | c = site and hsEdge(c, a, b))
}

predicate gReaches(string a, string b) {
  gEdge(_, a, b)
  or
  exists(string mid | gReaches(a, mid) and gEdge(_, mid, b))
}

predicate onCycle(string n) { gReaches(n, n) }

/** `n` originates a conditional edge, which may leave the cycle. */
predicate hasConditionalFrom(string n) {
  exists(MethodCall c | c.method() = "add_conditional_edges" and n = nodeId(c.getArg(0)))
}

/** `n` can leave its cycle: by a conditional edge, or by reaching a node off every cycle. */
predicate canExit(string n) {
  hasConditionalFrom(n)
  or
  exists(string m | gEdge(_, n, m) | not onCycle(m) or canExit(m))
}

/** The declaration call of a node/component, used as the finding location. */
predicate nodeDecl(Call site, string n) {
  exists(MethodCall m |
    m = site and m.method() = "add_node" and n = m.getArg(0).(StringLiteral).getText()
  )
  or
  site.getFunc().(Attribute).getName() = "add_component" and
  n = site.getArg(0).(StringLiteral).getText()
}

from Call site, string n
where
  onCycle(n) and
  not canExit(n) and
  nodeDecl(site, n)
select site,
  "Node '" + n + "' is on a cycle with no exit; control cannot leave the loop (potential nontermination)."
