"""W3C PROV-O record of every plan, written into the graph store (SPEC_REVIEW 2.12, D19).

One named graph (KG_PROV) holds, per plan version:
  plan          prov:Entity, prov:wasGeneratedBy the compose activity, prov:wasAttributedTo the builder agent
  activities    resolve -> safety_filter -> compose -> validate (prov:wasInformedBy chain), each prov:used its inputs
  each item     prov:Entity, prov:specializationOf the catalog exercise, prov:wasGeneratedBy compose
  each exclusion  fc:ExcludedExercise, prov:wasGeneratedBy safety_filter, prov:specializationOf the exercise,
                prov:wasDerivedFrom the rule (a KG1 rule node or the member's injury in KG2), fc:reason, fc:path
The coach's prompt is referenced, never stored: free text stays out of the graph as it stays out of logs.
Built from the stored plan event, so the record is rebuilt identically when the event log replays at startup.
"""

from __future__ import annotations

from pyoxigraph import Literal, NamedNode, Quad, Store

from ..graph.ns import BASE, FC, RDF_TYPE

KG_PROV = NamedNode(BASE + "/graph/provenance")
PROV = "http://www.w3.org/ns/prov#"
XSD = "http://www.w3.org/2001/XMLSchema#"
ACTIVITIES = ("resolve", "safety_filter", "compose", "validate")


def _rule_iri(rule: str | None, member_key: str) -> NamedNode | None:
    if not rule:
        return None
    if rule.endswith("-note"):  # a care-team note on the member's injury (KG2)
        return NamedNode(f"{BASE}/member/{member_key}/injury/{rule.removesuffix('-note')}")
    return NamedNode(f"{BASE}/rule/{rule}")  # condition rules are fcr:<id> in KG1; others are named filter rules


def record(store: Store, member_key: str, p: dict) -> None:
    """Add the PROV-O quads for one stored plan event payload."""
    if not p.get("request_id"):
        return
    root = f"{BASE}/prov/{p['request_id']}"
    plan = NamedNode(f"{root}/plan")
    q: list[Quad] = []

    def add(s, pred, o):
        q.append(Quad(s, NamedNode(pred), o, KG_PROV))

    act = {a: NamedNode(f"{root}/{a}") for a in ACTIVITIES}
    prompt = NamedNode(f"{root}/coach-request")
    member = NamedNode(f"{BASE}/member/{member_key}")
    builder = (p.get("plan") or {}).get("builder", "deterministic")
    agent = NamedNode(f"{BASE}/agent/{'composer-model' if builder == 'llm' else 'deterministic-builder'}")

    add(prompt, RDF_TYPE, NamedNode(PROV + "Entity"))
    add(prompt, FC + "about", member)
    for i, a in enumerate(ACTIVITIES):
        add(act[a], RDF_TYPE, NamedNode(PROV + "Activity"))
        if i:
            add(act[a], PROV + "wasInformedBy", act[ACTIVITIES[i - 1]])
    add(act["resolve"], PROV + "used", prompt)
    add(act["safety_filter"], PROV + "used", member)
    add(act["safety_filter"], PROV + "used", NamedNode(f"{BASE}/graph/domain"))
    add(act["compose"], PROV + "wasAssociatedWith", agent)
    add(agent, RDF_TYPE, NamedNode(PROV + "SoftwareAgent"))
    if p.get("created"):
        add(act["validate"], PROV + "endedAtTime", Literal(p["created"], datatype=NamedNode(XSD + "dateTime")))

    add(plan, RDF_TYPE, NamedNode(PROV + "Entity"))
    add(plan, RDF_TYPE, NamedNode(FC + "Plan"))
    add(plan, PROV + "wasGeneratedBy", act["validate"])
    add(plan, PROV + "wasAttributedTo", agent)
    add(plan, FC + "version", Literal(int(p.get("version", 1))))
    add(plan, FC + "forMember", member)
    for n, it in enumerate((p.get("plan") or {}).get("items", [])):
        item = NamedNode(f"{root}/item-{n}")
        add(item, RDF_TYPE, NamedNode(PROV + "Entity"))
        add(item, PROV + "specializationOf", NamedNode(f"{BASE}/exercise/{it['exercise_id']}"))
        add(item, PROV + "wasGeneratedBy", act["compose"])
        add(plan, PROV + "hadMember", item)
        for why in it.get("why") or []:
            if why:
                add(item, FC + "why", Literal(why))

    for n, ex in enumerate((p.get("provenance") or {}).get("excluded", [])):
        e = NamedNode(f"{root}/excluded-{n}")
        add(e, RDF_TYPE, NamedNode(PROV + "Entity"))
        add(e, RDF_TYPE, NamedNode(FC + "ExcludedExercise"))
        add(e, PROV + "wasGeneratedBy", act["safety_filter"])
        add(e, PROV + "specializationOf", NamedNode(f"{BASE}/exercise/{ex['exercise_id']}"))
        add(e, FC + "reason", Literal(ex["text"]))
        if ex.get("path"):
            add(e, FC + "path", Literal(" -> ".join(ex["path"])))
        if rule := _rule_iri(ex.get("rule"), member_key):
            add(e, PROV + "wasDerivedFrom", rule)
        if ex.get("source"):
            add(e, FC + "source", Literal(ex["source"]))
    store.extend(q)
