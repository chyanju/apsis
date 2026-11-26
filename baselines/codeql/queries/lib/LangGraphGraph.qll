/** A LangGraph StateGraph from builder calls with literal arguments; edges built at run time are absent. */

import python

class MethodCall extends Call {
  string method() { result = this.getFunc().(Attribute).getName() }
}

/** Resolve an edge-endpoint expression to a node id: a string literal, or a START/END sentinel. */
string nodeId(Expr e) {
  result = e.(StringLiteral).getText()
  or
  e.(Name).getId() = "START" and result = "__start__"
  or
  e.(Name).getId() = "END" and result = "__end__"
}

/** A declared node: `g.add_node("name", ...)`, or `g.add_node(func)`, which LangGraph names after `func`. */
predicate lgNode(string name) {
  exists(MethodCall c |
    c.method() = "add_node" and
    (
      name = c.getArg(0).(StringLiteral).getText()
      or
      name = c.getArg(0).(Name).getId()
    )
  )
}

/** A static edge `g.add_edge(src, dst)`, bound to its call for a finding location. */
predicate lgEdge(MethodCall c, string src, string dst) {
  c.method() = "add_edge" and src = nodeId(c.getArg(0)) and dst = nodeId(c.getArg(1))
}

/** A dynamic routing target: `Command(goto="x")`, or a path_map dict value in add_conditional_edges. */
predicate lgRoutingTarget(Expr loc, string target) {
  exists(Call c, Keyword k |
    c.getFunc().(Name).getId() = "Command" and
    k = c.getAKeyword() and
    k.getArg() = "goto" and
    loc = c and
    target = k.getValue().(StringLiteral).getText()
  )
  or
  exists(MethodCall c, Dict pm |
    c.method() = "add_conditional_edges" and
    pm = c.getArg(2) and
    loc = pm and
    target = pm.getAValue().(StringLiteral).getText()
  )
}

/** A declared node or the START/END sentinel. */
predicate lgKnownName(string name) {
  lgNode(name)
  or
  name = "__start__"
  or
  name = "__end__"
}
