import backend.state as state


async def test_shows_lists_seeded_session(client):
    db = state.get_db()
    await db.add_session({"session_id": "x1", "title": "maischberger", "visibility": "public"})
    resp = await client.get("/api/config/shows")
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()["shows"]]
    assert "x1" in keys


async def test_session_config_404(client):
    resp = await client.get("/api/config/nope")
    assert resp.status_code == 404


async def test_health_reports_active_sessions(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert "active_sessions" in resp.json()
