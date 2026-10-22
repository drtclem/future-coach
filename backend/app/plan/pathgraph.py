"""The safety filter's recorded graph paths, as typed nodes and edges for the dashboard.

Every path the filter writes has one of four shapes (see safety/filter.py):
  injury   [exercise, "stresses <structure> (<load type>)", "related via part-of to <structure>", condition, rule?]
  requires [exercise, "requires", equipment]
  family   [exercise, "variant-of", family]
  targets  [exercise, "targets", muscle, condition]
Nodes get a column (0 exercise, 1 load/need, 2 anatomy, 3 condition, 4 rule) so the
frontend can lay them out left to right without a layout engine.
"""

from __future__ import annotations

import re

from ..safety.filter import Decision

_STRESS = re.compile(r"stresses (\S+) \((\S+)\)")


def _h(s: str) -> str:
    return s.replace("_", " ").replace("-", " ")


def _rule_label(rule: str) -> str:
    if rule.endswith("-note"):
        return "care-team note"
    if rule.startswith("default-"):
        return f"stage default ({rule[8:]})"
    return _h(rule)


def path_graph(decisions: dict[str, Decision], chosen: set[str]) -> dict:
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], dict] = {}

    def node(i: str, label: str, kind: str, col: int, **kw) -> str:
        nodes.setdefault(i, {"id": i, "label": label, "kind": kind, "col": col, **kw})
        return i

    def edge(a: str, b: str, label: str, tier: str, kind: str) -> None:
        e = edges.setdefault((a, b, kind), {"from": a, "to": b, "label": label, "tier": tier, "kind": kind})
        if tier == "exclude":
            e["tier"] = "exclude"

    for d in decisions.values():
        status = "chosen" if d.exercise in chosen else d.tier
        if status not in ("chosen", "exclude", "downrank"):
            continue
        for r in d.reasons:
            p = r.path
            if not p or (status != "chosen" and r.tier != status):
                continue  # for left-out exercises, draw only the paths that left them out
            x = node(f"x:{d.exercise}", d.name, "exercise", 0, status=status)
            tier = "exclude" if status == "exclude" and r.tier == "exclude" else r.tier
            k = "picked" if status == "chosen" else r.kind
            rule = f"r:{r.rule}" if r.rule else None
            if rule:
                node(rule, _rule_label(r.rule), "rule", 4, source=r.source)

            if len(p) >= 4 and (m := _STRESS.match(p[1])):
                load = node(f"l:{m[1]}:{m[2]}", f"{_h(m[1])} · {_h(m[2])}", "load", 1)
                part = node(f"a:{p[2].rsplit(' ', 1)[-1]}", _h(p[2].rsplit(" ", 1)[-1]), "anatomy", 2)
                cond = node(f"c:{p[3]}", p[3].upper() if len(p[3]) <= 4 else _h(p[3]), "condition", 3)
                edge(x, load, "stresses", tier, k)
                edge(load, part, "part-of", tier, k)
                edge(part, cond, "affected by", tier, k)
                if rule:
                    edge(cond, rule, "rule", tier, k)
            elif len(p) >= 3 and p[1] in ("requires", "variant-of", "targets"):
                kind = {"requires": "equipment", "variant-of": "family", "targets": "muscle"}[p[1]]
                t = node(f"{kind[0]}:{p[2]}", _h(p[2]), kind, 1)
                edge(x, t, p[1], tier, k)
                if p[1] == "targets" and len(p) >= 4:
                    cond = node(f"c:{p[3]}", p[3].upper() if len(p[3]) <= 4 else _h(p[3]), "condition", 3)
                    edge(t, cond, "recommended for", "uprank", k)
                elif rule:
                    edge(t, rule, "rule", tier, k)
    linked = {e["from"] for e in edges.values()} | {e["to"] for e in edges.values()}
    return {"nodes": [n for n in nodes.values() if n["id"] in linked], "edges": list(edges.values())}
