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


async def test_count_active_sessions_ignores_stale_and_ended(client):
    # active_sessions must mean "live now", not "ever started": the 'active' flag never
    # clears on its own, so the count keys off recent activity instead.
    from datetime import datetime, timedelta
    db = state.get_db()
    now = datetime.now()
    recent = now.isoformat()
    old = (now - timedelta(hours=2)).isoformat()
    await db.add_session({"session_id": "live", "status": "active", "created_at": recent})
    await db.add_session({"session_id": "stale", "status": "active", "created_at": old})
    await db.add_session({"session_id": "done", "status": "ended", "created_at": recent})
    # Stale creation but a fresh fact-check → still live, via the EXISTS branch.
    await db.add_session({"session_id": "revived", "status": "active", "created_at": old})
    await db.add_fact_check({"timestamp": recent, "session_id": "revived"})
    assert await db.count_active_sessions(within_minutes=30) == 2


async def test_health_in_flight_zero_when_idle(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["in_flight"] == 0


async def test_health_in_flight_counts_only_unfinished_blocks(client):
    # in_flight reflects real work a restart would drop, not terminal blocks.
    state.pipeline_events["b1"] = {"status": "processing"}
    state.pipeline_events["b2"] = {"status": "slow"}
    state.pipeline_events["b3"] = {"status": "done"}
    state.pipeline_events["b4"] = {"status": "error"}
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["in_flight"] == 2


async def test_session_config_omits_owner_code(client):
    db = state.get_db()
    await db.add_session({"session_id": "sec1", "title": "t", "owner_code": "SECRET"})
    resp = await client.get("/api/config/sec1")
    assert resp.status_code == 200
    assert "owner_code" not in resp.json()


async def test_shows_excludes_private_sessions(client):
    db = state.get_db()
    await db.add_session({"session_id": "pub1", "title": "maischberger", "visibility": "public"})
    await db.add_session({"session_id": "priv1", "title": "user session", "visibility": "private"})
    resp = await client.get("/api/config/shows")
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()["shows"]]
    assert "pub1" in keys
    assert "priv1" not in keys
