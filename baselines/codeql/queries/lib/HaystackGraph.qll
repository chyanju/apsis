/** A Haystack pipeline graph from `pipeline.connect("a.out", "b.in")` calls with string-literal endpoints. */

import python

class ConnectCall extends Call {
  ConnectCall() {
    this.getFunc().(Attribute).getName() = "connect" and
    this.getArg(0) instanceof StringLiteral and
    this.getArg(1) instanceof StringLiteral
  }

  string senderLit() { result = this.getArg(0).(StringLiteral).getText() }

  string receiverLit() { result = this.getArg(1).(StringLiteral).getText() }
}

/** The component-name part of a `"component.socket"` endpoint (or the whole string if no dot). */
bindingset[s]
string componentOf(string s) {
  if s.matches("%.%") then result = s.splitAt(".", 0) else result = s
}

/** A declared component `pipeline.add_component("name", ...)`. */
predicate hsComponent(string name) {
  exists(Call c |
    c.getFunc().(Attribute).getName() = "add_component" and
    name = c.getArg(0).(StringLiteral).getText()
  )
}

/** An edge in the reconstructed pipeline: component `src` -> component `dst` (location = connect call). */
predicate hsEdge(ConnectCall c, string src, string dst) {
  src = componentOf(c.senderLit()) and dst = componentOf(c.receiverLit())
}
