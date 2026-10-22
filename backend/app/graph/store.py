"""Builds the domain knowledge graph (KG1) in an embedded Oxigraph store.

Sources of truth (D15):
  backend/kg/*.ttl             hand-authored anatomy, equipment, patterns, rules
  data/exercises.json          the provided catalog (never modified)
  data/exercises_synthetic.json our documented additions (D1)

Ingestion normalizes the catalog (D5.1) and records every fix in
`normalization_log`, which the README and the provenance trace surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pyoxigraph import Literal, NamedNode, Quad, RdfFormat, Store

from .ns import FC, FCA, FCE, FCF, FCL, FCM, FCP, FCX, KG1, PREFIXES, RDF_TYPE, SKOS, XSD, slug

REPO = Path(__file__).resolve().parents[3]
KG_DIR = REPO / "backend" / "kg"
DATA_DIR = REPO / "data"


@dataclass
class DomainGraph:
    store: Store
    normalization_log: list[dict] = field(default_factory=list)

    def query(self, sparql: str):
        return self.store.query(PREFIXES + sparql, use_default_graph_as_union=True)


def _n(iri: str) -> NamedNode:
    return NamedNode(iri)


def _lit(value, datatype: str | None = None) -> Literal:
    if isinstance(value, bool):
        return Literal(str(value).lower(), datatype=NamedNode(XSD + "boolean"))
    if isinstance(value, int):
        return Literal(str(value), datatype=NamedNode(XSD + "integer"))
    if isinstance(value, float):
        return Literal(str(value), datatype=NamedNode(XSD + "decimal"))
    return Literal(str(value))


def _structure_iri(joint_label: str) -> str:
    return FCA + slug(joint_label)


def build_domain_graph(
    catalog: Path = DATA_DIR / "exercises.json",
    synthetic: Path | None = DATA_DIR / "exercises_synthetic.json",
) -> DomainGraph:
    store = Store()
    for ttl in sorted(KG_DIR.glob("*.ttl")):
        store.load(ttl.read_bytes(), format=RdfFormat.TURTLE, to_graph=KG1)
    g = DomainGraph(store)

    exercises = [dict(e, source=e.get("source", "catalog")) for e in json.loads(catalog.read_text())]
    if synthetic and synthetic.exists():
        exercises += json.loads(synthetic.read_text())
    ids = {e["id"] for e in exercises}

    quads: list[Quad] = []

    def add(s: str, p: str, o) -> None:
        quads.append(Quad(_n(s), _n(p), o if not isinstance(o, str) else _n(o), KG1))

    seen_patterns, seen_equipment, seen_muscles = set(), set(), set()
    for e in exercises:
        x = FCX + e["id"]
        add(x, RDF_TYPE, FC + "Exercise")
        add(x, SKOS + "prefLabel", _lit(e["name"]))
        for alias in e.get("aliases") or []:
            add(x, SKOS + "altLabel", _lit(alias))
        add(x, FC + "source", _lit(e["source"]))
        for key in ("is_reps", "is_duration", "supports_weight"):
            add(x, FC + key, _lit(bool(e.get(key))))
        add(x, FC + "estRepDuration", _lit(float(e.get("estimated_rep_duration") or 0)))

        # D5.1 / C1: is_bilateral=true actually means "one side of a mirrored pair".
        unilateral = bool(e.get("is_bilateral"))
        add(x, FC + "unilateral", _lit(unilateral))
        if e.get("side"):
            add(x, FC + "side", _lit(e["side"]))
        pair = e.get("bilateral_pair_id")
        if pair:
            add(x, FC + "pairedWith", FCX + pair)
            if pair not in ids:
                g.normalization_log.append(
                    {
                        "exercise": e["name"],
                        "issue": "bilateral_pair_id points to an exercise not in the catalog",
                        "fix": "kept as paired-with edge; rendered as 'each side'",
                    }
                )

        for m in e.get("muscle_groups") or []:
            add(x, FC + "targets", FCM + slug(m))
            if m not in seen_muscles:
                seen_muscles.add(m)
                add(FCM + slug(m), SKOS + "prefLabel", _lit(m))

        for p in e.get("movement_patterns") or []:
            add(x, FC + "hasPattern", FCP + slug(p))
            if p not in seen_patterns:
                seen_patterns.add(p)
                add(FCP + slug(p), RDF_TYPE, FC + "MovementPattern")
                add(FCP + slug(p), SKOS + "prefLabel", _lit(p))

        for i, req in enumerate(e.get("equipment_required") or []):
            label, qty = (req["equipment"], req.get("quantity", 1)) if isinstance(req, dict) else (req, 1)
            r = f"{x}/requirement/{i}"
            add(x, FC + "requires", r)
            add(r, FC + "equipment", FCE + slug(label))
            add(r, FC + "quantity", _lit(int(qty)))
            if label not in seen_equipment:
                seen_equipment.add(label)
                add(FCE + slug(label), RDF_TYPE, FC + "Equipment")
                add(FCE + slug(label), SKOS + "prefLabel", _lit(label))

        if e.get("family"):
            add(x, FC + "variantOf", FCF + slug(e["family"]))

        joints = e.get("joints_loaded") or []
        if len(set(joints)) != len(joints):
            g.normalization_log.append(
                {"exercise": e["name"], "issue": "duplicate joint in joints_loaded", "fix": "deduplicated"}
            )
        if not joints:
            g.normalization_log.append(
                {
                    "exercise": e["name"],
                    "issue": "empty joints_loaded",
                    "fix": "joints filled from movement-pattern implications (patterns.ttl)",
                }
            )
        e["_joints"] = sorted(set(joints))

    for q in quads:
        store.add(q)
    _derive_stresses(g, exercises)
    return g


def _derive_stresses(g: DomainGraph, exercises: list[dict]) -> None:
    """Materialize n-ary Stress nodes: exercise -> (structure, load type, derivation).

    Load on a structure = most demanding pattern implication; a joint listed in
    joints_loaded but not explained by any pattern gets load type 'unspecified';
    exercise-level overrides (stress_overrides.ttl) win.
    """
    implications: dict[str, list[tuple[str, str, bool]]] = {}
    q = "SELECT ?p ?s ?lt ?a WHERE { ?p fc:implies ?i . ?i fc:structure ?s ; fc:loadType ?lt OPTIONAL { ?i fc:always ?a } }"
    for row in g.query(q):
        always = row["a"] is not None and row["a"].value == "true"
        implications.setdefault(row["p"].value, []).append((row["s"].value, row["lt"].value, always))
    demand = {r["lt"].value: int(r["d"].value) for r in g.query("SELECT ?lt ?d WHERE { ?lt fc:demand ?d }")}
    overrides: dict[str, dict[str, str]] = {}
    for row in g.query("SELECT ?x ?s ?lt WHERE { ?x fc:loadOverride ?o . ?o fc:structure ?s ; fc:loadType ?lt }"):
        overrides.setdefault(row["x"].value, {})[row["s"].value] = row["lt"].value

    for e in exercises:
        x = FCX + e["id"]
        loads: dict[str, tuple[str, str]] = {}  # structure -> (load type, derivation)
        listed = {_structure_iri(j) for j in e["_joints"]}
        for p in e.get("movement_patterns") or []:
            for s, lt, always in implications.get(FCP + slug(p), []):
                if listed and s not in listed and not always:
                    continue  # refine listed joints only (empty joints_loaded: take all)
                if s not in loads or demand[lt] > demand[loads[s][0]]:
                    loads[s] = (lt, f"pattern:{p}")
        for j in e["_joints"]:
            s = _structure_iri(j)
            loads.setdefault(s, (FCL + "unspecified", "joints_loaded"))
        for s, lt in overrides.get(x, {}).items():
            loads[s] = (lt, "override")
        for s, (lt, how) in loads.items():
            node = NamedNode(f"{x}/stress/{s.rsplit('/', 1)[-1]}")
            for p, o in ((FC + "structure", NamedNode(s)), (FC + "loadType", NamedNode(lt)), (FC + "derivation", Literal(how))):
                g.store.add(Quad(node, NamedNode(p), o, KG1))
            g.store.add(Quad(NamedNode(x), NamedNode(FC + "stresses"), node, KG1))


@lru_cache(maxsize=1)
def domain_graph() -> DomainGraph:
    """Process-wide KG1, built once at startup (~50 ms)."""
    return build_domain_graph()
