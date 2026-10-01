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


async def test_keyterms_set_with_the_session(client):
    sid = (await client.post("/api/sessions", json={
        "title": "T", "keyterms": [" Katharina Reiche ", "", "katharina reiche", "Bundesnetzagentur"],
    })).json()["session_id"]
    assert (await client.get(f"/api/sessions/{sid}")).json()["keyterms"] == ["Katharina Reiche", "Bundesnetzagentur"]
    assert (await client.get(f"/api/config/{sid}")).json()["keyterms"] == ["Katharina Reiche", "Bundesnetzagentur"]
    other = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    assert (await client.get(f"/api/sessions/{other}")).json()["keyterms"] == []


# --- Meine Checks: GET /api/my/sessions -------------------------------------

async def _add_check(sid, consistency, status="done"):
    from backend import state
    await state.get_db().add_fact_check({
        "sprecher": "A", "behauptung": "x", "consistency": consistency,
        "timestamp": "2026-09-30T20:00:00", "session_id": sid, "status": status,
    })


async def test_my_sessions_lists_only_own_sessions_with_counts(client):
    from backend import state
    await state.get_db().add_code("other-code", "other")
    mine = (await client.post("/api/sessions", json={"title": "Meine"})).json()["session_id"]
    theirs = (await client.post(
        "/api/sessions", json={"title": "Fremd"}, headers={"X-Access-Code": "other-code"},
    )).json()["session_id"]
    await _add_check(mine, "hoch")
    await _add_check(mine, "Niedrig")
    await _add_check(mine, "hoch", status="discarded")
    await _add_check(theirs, "hoch")

    resp = await client.get("/api/my/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert [s["session_id"] for s in body] == [mine]
    assert body[0]["claims"] == 2
    assert (body[0]["hoch"], body[0]["niedrig"], body[0]["unklar"]) == (1, 1, 0)
    assert "owner_code" not in body[0]


async def test_my_sessions_includes_empty_sessions_newest_first(client):
    first = (await client.post("/api/sessions", json={"title": "Erste"})).json()["session_id"]
    second = (await client.post("/api/sessions", json={"title": "Zweite"})).json()["session_id"]
    body = (await client.get("/api/my/sessions")).json()
    assert [s["session_id"] for s in body] == [second, first]
    assert body[0]["claims"] == 0


async def test_my_sessions_requires_code(no_auth_client):
    assert (await no_auth_client.get("/api/my/sessions")).status_code == 401


# --- Deleting own sessions: DELETE /api/sessions/{id} ------------------------

async def test_delete_own_session_removes_it_and_its_checks(client):
    from backend import state
    sid = (await client.post("/api/sessions", json={"title": "Weg"})).json()["session_id"]
    keep = (await client.post("/api/sessions", json={"title": "Bleibt"})).json()["session_id"]
    await _add_check(sid, "hoch")
    await _add_check(keep, "hoch")

    resp = await client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 404
    assert await state.get_db().get_fact_checks(session_id=sid) == []
    assert len(await state.get_db().get_fact_checks(session_id=keep)) == 1
    assert [s["session_id"] for s in (await client.get("/api/my/sessions")).json()] == [keep]


async def test_delete_other_owners_session_is_404(client):
    from backend import state
    await state.get_db().add_code("other-code", "other")
    sid = (await client.post(
        "/api/sessions", json={"title": "Fremd"}, headers={"X-Access-Code": "other-code"},
    )).json()["session_id"]
    assert (await client.delete(f"/api/sessions/{sid}")).status_code == 404
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 200


async def test_delete_ownerless_session_is_404(client):
    from backend import state
    await state.get_db().add_session({"session_id": "legacy-ep", "title": "Alt"})
    assert (await client.delete("/api/sessions/legacy-ep")).status_code == 404
    assert (await client.get("/api/sessions/legacy-ep")).status_code == 200


async def test_delete_session_while_streaming_is_409(client):
    from backend import state
    sid = (await client.post("/api/sessions", json={"title": "Live"})).json()["session_id"]
    state.streaming_sessions[sid] = object()
    try:
        assert (await client.delete(f"/api/sessions/{sid}")).status_code == 409
    finally:
        state.streaming_sessions.pop(sid, None)
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 200


async def test_delete_session_requires_code(no_auth_client):
    assert (await no_auth_client.delete("/api/sessions/x")).status_code == 401


async def test_cors_preflight_allows_delete(no_auth_client):
    """Browsers preflight DELETE from the frontend origin; without DELETE in the CORS
    methods the request never leaves the browser ("Failed to fetch")."""
    resp = await no_auth_client.options("/api/sessions/x", headers={
        "Origin": "https://live-faktencheck.de",
        "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "x-access-code,content-type",
    })
    assert resp.status_code == 200
    assert "DELETE" in resp.headers["access-control-allow-methods"]
