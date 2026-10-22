"""Ingestion and data-quality checks (D5.1, SPEC_REVIEW 3.1)."""

import json

from app.graph.store import DATA_DIR


def count(graph, sparql):
    return int(next(iter(graph.query(sparql)))["n"].value)


def test_catalog_counts_match_the_spec():
    ex = json.loads((DATA_DIR / "exercises.json").read_text())
    assert len(ex) == 50
    for key, n in {"muscle_groups": 19, "joints_loaded": 9, "movement_patterns": 36, "equipment_required": 32}.items():
        assert len({v for e in ex for v in e[key]}) == n, key


def test_catalog_file_is_untouched_and_synthetic_is_tagged():
    syn = json.loads((DATA_DIR / "exercises_synthetic.json").read_text())
    assert all(e["source"] == "synthetic" and e["reason"] for e in syn)
    assert "source" not in json.loads((DATA_DIR / "exercises.json").read_text())[0]


def test_every_exercise_is_ingested(graph):
    assert count(graph, "SELECT (COUNT(?x) AS ?n) WHERE { ?x a fc:Exercise }") == 50 + 20


def test_normalization_log_records_the_known_data_issues(graph):
    issues = [(r["exercise"], r["issue"]) for r in graph.normalization_log]
    assert ("Alternating Dumbbell Decline Bench Press", "empty joints_loaded") in issues
    assert ("Alternating Low Plank To Low Side Plank", "duplicate joint in joints_loaded") in issues
    assert sum(1 for _, i in issues if i.startswith("bilateral_pair_id")) == 18


def test_unilateral_is_the_real_meaning_of_is_bilateral(graph):
    n = count(graph, "SELECT (COUNT(?x) AS ?n) WHERE { ?x fc:unilateral true ; fc:side ?s }")
    assert n == 18


def test_empty_joints_are_filled_from_patterns(graph):
    q = """SELECT (COUNT(?st) AS ?n) WHERE { ?x skos:prefLabel "Alternating Dumbbell Decline Bench Press" ;
           fc:stresses ?st . ?st fc:structure fca:shoulder }"""
    assert count(graph, q) == 1


def test_ontology_alignments_attach_to_real_nodes(graph):
    """Every EXMO/NCIT mapping hangs off a concept the graph already defines (no typo nodes)."""
    from pathlib import Path

    from pyoxigraph import RdfFormat, Store

    s = Store()
    s.load((Path(__file__).parents[1] / "kg" / "ontology_alignment.ttl").read_bytes(), format=RdfFormat.TURTLE)
    subjects = {q.subject.value for q in s}
    assert len(subjects) > 40
    for iri in subjects:
        assert bool(graph.query(f"ASK {{ {{ <{iri}> a ?t }} UNION {{ ?x a <{iri}> }} }}")), f"{iri} is not in the graph"
    targets = {q.object.value for q in s if "skos/core#" in q.predicate.value}
    assert all(t.startswith("http://purl.obolibrary.org/obo/") for t in targets)


def test_ontology_alignment_never_widens_equipment(graph):
    """Loop band and band-with-handles share an EXMO broadMatch; that must not make one stand in for the other."""
    from app.graph.ns import FCE
    from app.safety.filter import SafetyFilter

    avail = SafetyFilter(graph).available_equipment(["Resistance Band - Loop"], set())
    assert FCE + "resistance-band-with-handles" not in avail
    assert not [k for k in avail if k.startswith("http://purl.obolibrary.org/")]
