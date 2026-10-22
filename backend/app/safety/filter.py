"""Deterministic safety and feasibility filter (D2, D3, D4, D1).

Every decision is a graph traversal plus a rule lookup -- no LLM is involved.
Each exercise gets a tier (excluded / downranked / allowed, plus an uprank
flag) and a list of human-readable reasons with the graph path that produced
them, which the provenance trace records.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..graph.ns import FCA, FCC, FCE, FCF, FCP, local, slug
from ..graph.store import DomainGraph

SEVERITY = {"exclude": 3, "downrank": 2, "allow": 1}
STAGE_DEFAULT = {"acute": "exclude", "recovering": "downrank", "cleared": "allow"}


@dataclass(frozen=True)
class InjuryRule:
    """A member-specific rule, e.g. from a care-team note (D2)."""

    load_type: str  # local name, e.g. "impact"
    tier: str  # exclude | downrank | allow
    source: str
    cue: str | None = None


@dataclass(frozen=True)
class Injury:
    id: str
    label: str
    structure: str  # local anatomy name, e.g. "knee" or "patellofemoral-joint"
    status: str  # acute | recovering | cleared
    condition: str = "unspecified-complaint"  # local condition name
    side: str | None = None  # D3: used in text only, never in the filter
    extra_rules: tuple[InjuryRule, ...] = ()


@dataclass
class Constraints:
    injuries: list[Injury] = field(default_factory=list)
    equipment: list[str] | None = None  # equipment labels/slugs; None = no equipment constraint
    excluded_families: set[str] = field(default_factory=set)
    excluded_patterns: set[str] = field(default_factory=set)
    excluded_equipment: set[str] = field(default_factory=set)  # e.g. {"barbell-family"}
    equipment_quantity: dict[str, int] = field(default_factory=dict)  # stated counts, e.g. {"kettlebell": 1}


@dataclass
class Reason:
    kind: str  # injury | equipment | family | pattern | uprank
    tier: str
    text: str
    path: list[str]
    rule: str | None = None
    source: str | None = None


@dataclass
class Decision:
    exercise: str  # local id
    name: str
    tier: str = "allow"
    uprank: bool = False
    reasons: list[Reason] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # e.g. closeMatch equipment assumptions

    def apply(self, reason: Reason) -> None:
        self.reasons.append(reason)
        if reason.kind == "uprank":
            self.uprank = True
        elif SEVERITY[reason.tier] > SEVERITY[self.tier]:
            self.tier = reason.tier


class SafetyFilter:
    def __init__(self, g: DomainGraph):
        self.g = g
        self._load()

    # -- graph reads (once per filter) -------------------------------------
    def _load(self) -> None:
        g = self.g
        self.names = {r["x"].value: r["n"].value for r in g.query("SELECT ?x ?n WHERE { ?x a fc:Exercise ; skos:prefLabel ?n }")}
        self.stresses: dict[str, list[tuple[str, str, str]]] = {}
        q = "SELECT ?x ?s ?lt ?how WHERE { ?x fc:stresses ?st . ?st fc:structure ?s ; fc:loadType ?lt ; fc:derivation ?how }"
        for r in g.query(q):
            self.stresses.setdefault(r["x"].value, []).append((r["s"].value, r["lt"].value, r["how"].value))
        self.requirements: dict[str, list[tuple[str, int]]] = {}
        for r in g.query("SELECT ?x ?e ?q WHERE { ?x fc:requires ?r . ?r fc:equipment ?e ; fc:quantity ?q }"):
            self.requirements.setdefault(r["x"].value, []).append((r["e"].value, int(r["q"].value)))
        self.targets: dict[str, set[str]] = {}
        for r in g.query("SELECT ?x ?m WHERE { ?x fc:targets ?m }"):
            self.targets.setdefault(r["x"].value, set()).add(r["m"].value)

    def related_structures(self, structure: str) -> set[str]:
        """part-of traversal in BOTH directions (SPEC_REVIEW 1.4)."""
        s = FCA + structure
        q = f"SELECT DISTINCT ?r WHERE {{ {{ ?r fc:partOf* <{s}> }} UNION {{ <{s}> fc:partOf* ?r }} }}"
        return {r["r"].value for r in self.g.query(q)}

    def rules_for(self, condition: str, load_type: str, stage: str) -> list[dict]:
        q = f"""SELECT ?rule ?tier ?cue ?src ?conf WHERE {{
            ?rule a fc:Rule ; fc:condition <{FCC + condition}> ; fc:tier ?tier ; fc:stage ?st ; fc:loadType ?lt ; fc:source ?src ; fc:confidence ?conf .
            FILTER(?st IN (fc:{stage}, fc:anyStage)) FILTER(?lt IN (<{load_type}>, fc:anyLoad))
            OPTIONAL {{ ?rule fc:cue ?cue }} }}"""
        return [
            {
                "rule": local(r["rule"].value),
                "tier": local(r["tier"].value),
                "cue": r["cue"].value if r["cue"] else None,
                "source": r["src"].value,
                "confidence": r["conf"].value,
            }
            for r in self.g.query(q)
        ]

    def muscle_upranks(self, condition: str) -> list[tuple[str, str, str]]:
        q = f"SELECT ?rule ?m ?src WHERE {{ ?rule fc:condition <{FCC + condition}> ; fc:tier fc:uprank ; fc:targetsMuscle ?m ; fc:source ?src }}"
        return [(local(r["rule"].value), r["m"].value, r["src"].value) for r in self.g.query(q)]

    def members_of(self, family: str) -> set[str]:
        q = f"SELECT ?x WHERE {{ ?x fc:variantOf/skos:broader* <{FCF + family}> }}"
        return {r["x"].value for r in self.g.query(q)}

    def with_pattern(self, pattern: str) -> set[str]:
        q = f"SELECT DISTINCT ?x WHERE {{ ?x fc:hasPattern/skos:broader* <{FCP + pattern}> }}"
        return {r["x"].value for r in self.g.query(q)}

    def available_equipment(
        self, labels: list[str], excluded: set[str], stated_qty: dict[str, int] | None = None
    ) -> dict[str, tuple[int, str | None]]:
        """Closure of what the member can use: given items + ambient, expanded through
        fc:provides and skos:closeMatch. Value = (quantity, flag-if-assumed)."""
        avail: dict[str, tuple[int, str | None]] = {}
        given = [FCE + slug(label) for label in labels]
        banned = set()
        for fam in excluded:
            banned |= {r["e"].value for r in self.g.query(f"SELECT ?e WHERE {{ ?e skos:broader* <{FCE + fam}> }}")}
        ambient = [r["e"].value for r in self.g.query("SELECT ?e WHERE { ?e a fc:Ambient }")]
        for e in given + ambient:
            if e in banned:
                continue
            qty_rows = list(self.g.query(f"SELECT ?q WHERE {{ <{e}> fc:defaultQuantity ?q }}"))
            qty = int(qty_rows[0]["q"].value) if qty_rows else 1
            qty = (stated_qty or {}).get(local(e), qty)
            avail[e] = (max(qty, avail.get(e, (0, None))[0]), None)
            q = f"SELECT ?y WHERE {{ <{e}> fc:provides+ ?y }}"
            for r in self.g.query(q):
                y = r["y"].value
                if y not in banned:
                    avail.setdefault(y, (qty, None))
        for e in list(avail):
            q = f'SELECT ?y WHERE {{ <{e}> skos:closeMatch ?y . FILTER(STRSTARTS(STR(?y), "{FCE}")) }}'
            for r in self.g.query(q):  # our own equipment only; ontology alignments never widen availability
                y = r["y"].value
                if y not in avail and y not in banned:
                    avail[y] = (avail[e][0], f"assumes {local(e)} works as {local(y)}")
        return avail

    # -- the filter ----------------------------------------------------------
    def evaluate(self, c: Constraints) -> dict[str, Decision]:
        decisions = {x: Decision(exercise=local(x), name=n) for x, n in self.names.items()}

        for fam in c.excluded_families:
            for x in self.members_of(fam):
                decisions[x].apply(
                    Reason(
                        "family",
                        "exclude",
                        f"variant of excluded family '{fam}'",
                        [local(x), "variant-of", fam],
                        rule="coach-exclusion",
                    )
                )
        for pat in c.excluded_patterns:
            for x in self.with_pattern(pat):
                decisions[x].apply(
                    Reason(
                        "pattern",
                        "exclude",
                        f"uses excluded movement pattern '{pat}'",
                        [local(x), "has-pattern", pat],
                        rule="coach-exclusion",
                    )
                )

        if c.equipment is not None:
            avail = self.available_equipment(c.equipment, c.excluded_equipment, c.equipment_quantity)
            for x, reqs in self.requirements.items():
                for e, qty in reqs:
                    have = avail.get(e)
                    if have is None:
                        decisions[x].apply(
                            Reason(
                                "equipment",
                                "exclude",
                                f"requires {local(e)}, which is not available",
                                [local(x), "requires", local(e)],
                                rule="equipment-feasibility",
                            )
                        )
                    elif have[0] < qty:
                        decisions[x].apply(
                            Reason(
                                "equipment",
                                "exclude",
                                f"requires {qty}x {local(e)}; only {have[0]} available",
                                [local(x), "requires", f"{qty}x {local(e)}"],
                                rule="equipment-quantity",
                            )
                        )
                    elif have[1]:
                        decisions[x].flags.append(have[1])

        for inj in c.injuries:
            if inj.status == "cleared":
                continue  # D2: a cleared injury is inactive
            related = self.related_structures(inj.structure)
            where = inj.label if not inj.side or inj.side in inj.label else f"{inj.side} {inj.label}"
            for x, loads in self.stresses.items():
                for s, lt, how in loads:
                    if s not in related:
                        continue
                    self._judge(decisions[x], inj, where, s, lt, how)
            for rule, muscle, src in self.muscle_upranks(inj.condition):
                for x, ms in self.targets.items():
                    if muscle in ms:
                        decisions[x].apply(
                            Reason(
                                "uprank",
                                "allow",
                                f"targets {local(muscle)}: recommended for {inj.label}",
                                [local(x), "targets", local(muscle), inj.condition],
                                rule=rule,
                                source=src,
                            )
                        )
        return decisions

    def _judge(self, d: Decision, inj: Injury, where: str, s: str, lt: str, how: str) -> None:
        lt_name = local(lt)
        path = [d.exercise, f"stresses {local(s)} ({lt_name})", f"related via part-of to {inj.structure}", inj.condition]
        if lt_name == "contact_only":
            d.apply(Reason("injury", "allow", f"{local(s)} is touched, not loaded ({where})", path, rule="contact-only"))
            return
        rules = self.rules_for(inj.condition, lt, inj.status)
        for r in rules:
            if r["tier"] == "uprank":  # a recommended load is also an explicit "allow"
                d.apply(
                    Reason(
                        "uprank",
                        "allow",
                        f"{lt_name} loading is recommended for {inj.label}",
                        path,
                        rule=r["rule"],
                        source=r["source"],
                    )
                )
        matched = [dict(r, tier="allow") if r["tier"] == "uprank" else r for r in rules]
        matched += [
            {"rule": f"{inj.id}-note", "tier": r.tier, "cue": r.cue, "source": r.source, "confidence": "care-team"}
            for r in inj.extra_rules
            if r.load_type == lt_name
        ]
        if not matched:
            tier = STAGE_DEFAULT[inj.status]
            d.apply(
                Reason(
                    "injury",
                    tier,
                    f"loads {local(s)} ({lt_name}) with {where} {inj.status}; no specific rule, stage default",
                    path,
                    rule=f"default-{inj.status}",
                )
            )
            return
        worst = max(matched, key=lambda r: SEVERITY[r["tier"]])
        cue = next((r["cue"] for r in matched if r["cue"] and r["tier"] == worst["tier"]), None)
        text = f"loads {local(s)} ({lt_name}); {where} is {inj.status}" + (
            f". Cue: {cue}" if cue and worst["tier"] == "downrank" else ""
        )
        d.apply(Reason("injury", worst["tier"], text, path + [worst["rule"]], rule=worst["rule"], source=worst["source"]))
