from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["triples"] > 1000


def test_evaluate_excludes_deadlifts_over_http():
    r = client.post("/api/safety/evaluate", json={"excluded_families": ["deadlift"]})
    excluded = {d["name"] for d in r.json() if d["tier"] == "exclude"}
    assert "Trap Bar Deadlift" in excluded and "Kettlebell Swing" not in excluded


def test_resolve_endpoint_fails_closed():
    r = client.post("/api/resolve", json={"prompt": "she's in a lot of pain"}).json()
    assert r["blocking"]


def test_generate_endpoint_returns_plan_and_trace():
    r = client.post("/api/members/sam/generate", json={"prompt": "Full body, 30 min"}).json()
    assert r["status"] == "ok" and r["plan"]["items"] and r["trace"]["request_id"]


def test_member_message_replies_at_once_and_replans_in_the_background():
    client.post("/api/demo/reset", json={})
    client.post("/api/members/jordan/generate", json={"prompt": "Lower body, 40 min"})
    r = client.post("/api/members/jordan/messages", json={"text": "baby was up all night, I slept 4 hours"}).json()
    assert r["reply_to_member"] and r["replan"]["status"] == "pending"
    done = client.get("/api/members/jordan/replan").json()  # TestClient runs background tasks before returning
    assert done["status"] == "done" and done["version"] == 2
    client.post("/api/demo/reset", json={})
    assert client.get("/api/members/jordan/replan").json() is None


def test_plan_provenance_is_prov_o_in_the_graph_and_survives_replay(tmp_path):
    from pyoxigraph import RdfFormat, Store

    from app.graph.store import domain_graph
    from app.member.model import MemberRepo
    from app.plan.prov import KG_PROV

    r = client.post("/api/members/jordan/generate", json={"prompt": "Lower-body exercises that avoid aggravating a knee injury"})
    rid = r.json()["trace"]["request_id"]
    ttl = client.get(f"/api/prov/{rid}")
    assert ttl.status_code == 200
    s = Store()
    s.load(ttl.text.encode(), format=RdfFormat.TURTLE)

    def ask(q: str) -> bool:
        return bool(s.query("PREFIX prov: <http://www.w3.org/ns/prov#> PREFIX fc: <https://example.org/future-coach/kg#> " + q))

    assert ask(
        "ASK { ?c prov:wasInformedBy ?f . ?p a fc:Plan ; prov:wasGeneratedBy ?v ; prov:hadMember ?i . ?i prov:specializationOf ?x }"
    )
    assert ask("ASK { ?e a fc:ExcludedExercise ; prov:wasGeneratedBy ?sf ; prov:wasDerivedFrom ?rule ; fc:reason ?why }")
    assert "Lower-body" not in ttl.text  # the coach's words are referenced, never stored

    g = domain_graph()
    g.store.clear_graph(KG_PROV)
    MemberRepo(g)  # replaying the event log rebuilds the record
    assert client.get(f"/api/prov/{rid}").status_code == 200
