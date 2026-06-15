"""Two sessions must not see each other's data."""


async def test_fact_checks_isolated_by_session(client):
    a = (await client.post("/api/sessions", json={"title": "A"})).json()["session_id"]
    b = (await client.post("/api/sessions", json={"title": "B"})).json()["session_id"]

    await client.post("/api/fact-checks", json={
        "sprecher": "X", "behauptung": "claim-A", "session_id": a,
    })
    await client.post("/api/fact-checks", json={
        "sprecher": "Y", "behauptung": "claim-B", "session_id": b,
    })

    fa = (await client.get(f"/api/fact-checks?session_id={a}")).json()
    fb = (await client.get(f"/api/fact-checks?session_id={b}")).json()
    assert [f["behauptung"] for f in fa] == ["claim-A"]
    assert [f["behauptung"] for f in fb] == ["claim-B"]


async def test_pending_claims_isolated_by_session(client):
    a = (await client.post("/api/sessions", json={"title": "A"})).json()["session_id"]
    b = (await client.post("/api/sessions", json={"title": "B"})).json()["session_id"]
    await client.post("/api/pending-claims", json={
        "claims": [{"name": "X", "claim": "c"}], "session_id": a,
    })
    pa = (await client.get(f"/api/pending-claims?session_id={a}")).json()
    pb = (await client.get(f"/api/pending-claims?session_id={b}")).json()
    assert len(pa) == 1 and len(pb) == 0
