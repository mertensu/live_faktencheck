"""Tests for the sessions API."""


async def test_create_session_returns_id(client):
    resp = await client.post("/api/sessions", json={
        "title": "Mein Interview",
        "guests": ["Moderator (Host)", "Gast (Experte)"],
        "context": "Thema X",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"]
    assert body["status"] == "active"
    assert body["visibility"] == "private"


async def test_get_session(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "T"


async def test_get_missing_session_404(client):
    resp = await client.get("/api/sessions/does-not-exist")
    assert resp.status_code == 404


async def test_end_session(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.post(f"/api/sessions/{sid}/end")
    assert resp.status_code == 200
    assert (await client.get(f"/api/sessions/{sid}")).json()["status"] == "ended"


async def test_create_session_accepts_conversation_type(client):
    resp = await client.post("/api/sessions", json={"title": "I", "conversation_type": "private"})
    assert resp.status_code == 201
    assert resp.json()["conversation_type"] == "private"


async def test_create_session_defaults_conversation_type(client):
    resp = await client.post("/api/sessions", json={"title": "T"})
    assert resp.status_code == 201
    assert resp.json()["conversation_type"] == "debate"


async def test_create_session_accepts_excluded_speakers(client):
    resp = await client.post("/api/sessions", json={
        "title": "Talk",
        "guests": ["Caren Miosga (Moderatorin)", "Gast (CDU)"],
        "excluded_speakers": ["Caren Miosga"],
    })
    assert resp.status_code == 201
    assert resp.json()["excluded_speakers"] == ["Caren Miosga"]


async def test_create_session_defaults_excluded_speakers_empty(client):
    resp = await client.post("/api/sessions", json={"title": "T"})
    assert resp.status_code == 201
    assert resp.json()["excluded_speakers"] == []


async def test_session_response_includes_auto_check_default_false(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.get(f"/api/sessions/{sid}")
    assert resp.json()["auto_check"] is False


async def test_set_auto_check_toggles_flag(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.post(f"/api/sessions/{sid}/auto-check", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["auto_check"] is True
    assert (await client.get(f"/api/sessions/{sid}")).json()["auto_check"] is True


async def test_set_auto_check_unknown_session_404(client):
    resp = await client.post("/api/sessions/does-not-exist/auto-check", json={"enabled": True})
    assert resp.status_code == 404


async def test_set_auto_check_requires_code(no_auth_client):
    resp = await no_auth_client.post("/api/sessions/whatever/auto-check", json={"enabled": True})
    assert resp.status_code == 401
