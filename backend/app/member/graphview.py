"""A member's neighbourhood across both graphs, read with SPARQL for the dashboard.

KG2 (member) -> KG1 (domain): injury instance-of condition, injury at structure,
structure part-of its parents, condition rules for the injury's stage, member
equipment -> equipment nodes. Columns: 0 member, 1 what the member has,
2 domain concepts it points at, 3 rules and parent anatomy.
"""

from __future__ import annotations

from ..graph.ns import FC, local
from ..graph.store import DomainGraph


def _h(s: str) -> str:
    return s.replace("_", " ").replace("-", " ")


def member_graph(g: DomainGraph, member_key: str) -> dict:
    me = f"<{FC.rstrip('#')}/member/{member_key}>"
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(i, label, kind, col, **kw):
        nodes.setdefault(i, {"id": i, "label": label, "kind": kind, "col": col, **kw})
        return i

    def edge(a, b, label, tier="allow"):
        if not any(e["from"] == a and e["to"] == b for e in edges):
            edges.append({"from": a, "to": b, "label": label, "tier": tier, "kind": "member"})

    name = next(iter(g.query(f"SELECT ?n WHERE {{ {me} skos:prefLabel ?n }}")), None)
    root = node("m", name["n"].value if name else member_key, "member", 0)

    injuries = g.query(f"""SELECT ?i ?status ?side ?c ?cl ?s ?sl ?code WHERE {{
        {me} fc:hasInjury ?i . ?i fc:instanceOf ?c ; fc:at ?s ; fc:status ?status .
        OPTIONAL {{ ?i fc:laterality ?side }} OPTIONAL {{ ?c skos:prefLabel ?cl }}
        OPTIONAL {{ ?s skos:prefLabel ?sl }} OPTIONAL {{ ?c skos:exactMatch ?code }} }}""")
    for r in injuries:
        status = r["status"].value
        side = local(r["side"].value).lower() if r["side"] else ""
        inj = node(f"i:{local(r['i'].value)}", f"{side} {_h(local(r['s'].value))} · {status}".strip(), "injury", 1)
        cond = node(
            f"c:{local(r['c'].value)}",
            r["cl"].value if r["cl"] else _h(local(r["c"].value)),
            "condition",
            2,
            source=f"SNOMED CT {local(r['code'].value)}" if r["code"] else None,
        )
        struct = node(f"a:{local(r['s'].value)}", r["sl"].value if r["sl"] else _h(local(r["s"].value)), "anatomy", 2)
        edge(root, inj, "has injury")
        edge(inj, cond, "instance of")
        edge(inj, struct, "at")
        for p in g.query(
            f"""SELECT ?up ?ul WHERE {{ <{r["s"].value}> fc:partOf+ ?up . OPTIONAL {{ ?up skos:prefLabel ?ul }} }}"""
        ):
            edge(
                struct,
                node(f"a:{local(p['up'].value)}", p["ul"].value if p["ul"] else _h(local(p["up"].value)), "anatomy", 3),
                "part of",
            )
        for q in g.query(f"""SELECT ?r ?lt ?tier WHERE {{ ?r a fc:Rule ; fc:condition <{r["c"].value}> ; fc:loadType ?lt ;
                fc:tier ?tier ; fc:stage ?st . FILTER(?st IN (fc:{status}, fc:anyStage)) }}"""):
            tier = local(q["tier"].value)
            edge(cond, node(f"r:{local(q['r'].value)}", f"{_h(local(q['lt'].value))} → {tier}", "rule", 3), "rule", tier)
        for q in g.query(f"SELECT ?lt WHERE {{ <{r['i'].value}> fc:memberRuleLoad ?lt }}"):
            n = node(f"n:{local(r['i'].value)}:{local(q['lt'].value)}", f"care team: avoid {_h(local(q['lt'].value))}", "rule", 3)
            edge(inj, n, "care-team note", "exclude")

    for r in g.query(f"SELECT ?gl ?l WHERE {{ {me} fc:hasGoal ?gl . ?gl skos:prefLabel ?l }}"):
        edge(root, node(f"g:{local(r['gl'].value)}", r["l"].value, "goal", 1), "goal")
    for r in g.query(f"SELECT ?e ?l WHERE {{ {me} fc:hasEquipment ?e . OPTIONAL {{ ?e skos:prefLabel ?l }} }}"):
        edge(root, node(f"e:{local(r['e'].value)}", r["l"].value if r["l"] else _h(local(r["e"].value)), "equipment", 1), "has")
    for pred, label in (("hasWorkout", "logged workouts"), ("hasMessage", "messages")):
        n = next(iter(g.query(f"SELECT (COUNT(?x) AS ?n) WHERE {{ {me} fc:{pred} ?x }}")))["n"].value
        if int(n):
            edge(root, node(f"k:{pred}", f"{n} {label}", "activity", 1), "has")
    return {"nodes": list(nodes.values()), "edges": edges}
