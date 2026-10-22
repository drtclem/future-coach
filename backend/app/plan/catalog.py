"""Read-only exercise facts the planner needs, loaded once from KG1."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from ..graph.ns import local
from ..graph.store import DomainGraph, domain_graph


@dataclass
class Ex:
    id: str
    name: str
    patterns: set[str] = field(default_factory=set)
    pattern_ancestors: set[str] = field(default_factory=set)
    muscles: set[str] = field(default_factory=set)
    is_reps: bool = True
    is_duration: bool = True
    unilateral: bool = False
    source: str = "catalog"
    aliases: set[str] = field(default_factory=set)


@dataclass
class Catalog:
    ex: dict[str, Ex]
    region_patterns: dict[str, set[str]]
    by_label: dict[str, str]  # lowercased name/alias -> id

    def lookup(self, name: str) -> Ex | None:
        i = self.by_label.get(name.strip().lower())
        return self.ex.get(i) if i else None


def build_catalog(g: DomainGraph) -> Catalog:
    ex: dict[str, Ex] = {}
    for r in g.query("""SELECT ?x ?n ?src ?reps ?dur ?uni WHERE { ?x a fc:Exercise ; skos:prefLabel ?n ; fc:source ?src ;
                         fc:is_reps ?reps ; fc:is_duration ?dur ; fc:unilateral ?uni }"""):
        i = local(r["x"].value)
        ex[i] = Ex(
            i,
            r["n"].value,
            is_reps=r["reps"].value == "true",
            is_duration=r["dur"].value == "true",
            unilateral=r["uni"].value == "true",
            source=r["src"].value,
        )
    for r in g.query("SELECT ?x ?p ?a WHERE { ?x a fc:Exercise ; fc:hasPattern ?p . ?p skos:broader* ?a }"):
        e = ex[local(r["x"].value)]
        e.patterns.add(local(r["p"].value))
        e.pattern_ancestors.add(local(r["a"].value))
    for r in g.query("SELECT ?x ?m WHERE { ?x a fc:Exercise ; fc:targets ?m }"):
        ex[local(r["x"].value)].muscles.add(local(r["m"].value))
    for r in g.query("SELECT ?x ?l WHERE { ?x a fc:Exercise ; skos:altLabel ?l }"):
        ex[local(r["x"].value)].aliases.add(r["l"].value)
    regions: dict[str, set[str]] = {}
    for r in g.query("SELECT ?g ?p WHERE { ?g a fc:BodyRegion . OPTIONAL { ?g fc:includesPattern ?p } }"):
        regions.setdefault(local(r["g"].value), set())
        if r["p"] is not None:
            regions[local(r["g"].value)].add(local(r["p"].value))
    by_label = {e.name.lower(): i for i, e in ex.items()}
    for i, e in ex.items():
        for a in e.aliases:
            by_label.setdefault(a.lower(), i)
    return Catalog(ex, regions, by_label)


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    return build_catalog(domain_graph())
