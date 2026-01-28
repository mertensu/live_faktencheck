"""
Tests for fact-checks API endpoints.

Tests:
- GET /api/fact-checks
- GET /api/fact-checks?episode=xxx
- POST /api/fact-checks
- PUT /api/fact-checks/{id}
- GET /api/health
"""

import pytest

from backend import state


class TestGetFactChecks:
    """Tests for GET /api/fact-checks endpoint."""

    async def test_get_fact_checks_empty(self, client):
        """GET /api/fact-checks returns empty list when no fact-checks."""
        response = await client.get("/api/fact-checks")

        assert response.status_code == 200
        assert response.json() == []

    async def test_get_fact_checks_returns_all(self, client):
        """GET /api/fact-checks returns all stored fact-checks."""
        # Add some fact-checks to state
        state.fact_checks.extend([
            {
                "id": 1,
                "sprecher": "Speaker A",
                "behauptung": "Claim 1",
                "consistency": "hoch",
                "begruendung": "Evidence 1",
                "quellen": [],
                "timestamp": "2024-01-01T10:00:00",
                "episode_key": "ep1",
            },
            {
                "id": 2,
                "sprecher": "Speaker B",
                "behauptung": "Claim 2",
                "consistency": "niedrig",
                "begruendung": "Evidence 2",
                "quellen": [],
                "timestamp": "2024-01-01T11:00:00",
                "episode_key": "ep2",
            },
        ])

        response = await client.get("/api/fact-checks")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["sprecher"] == "Speaker A"
        assert data[1]["sprecher"] == "Speaker B"

    async def test_get_fact_checks_with_episode_filter(self, client):
        """GET /api/fact-checks?episode=xxx filters by episode."""
        state.fact_checks.extend([
            {"id": 1, "sprecher": "A", "episode_key": "episode-1", "behauptung": "C1"},
            {"id": 2, "sprecher": "B", "episode_key": "episode-2", "behauptung": "C2"},
            {"id": 3, "sprecher": "C", "episode_key": "episode-1", "behauptung": "C3"},
        ])

        response = await client.get("/api/fact-checks?episode=episode-1")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(fc["episode_key"] == "episode-1" for fc in data)

    async def test_get_fact_checks_episode_filter_no_match(self, client):
        """GET /api/fact-checks?episode=xxx returns empty if no match."""
        state.fact_checks.append({
            "id": 1, "sprecher": "A", "episode_key": "ep1", "behauptung": "C"
        })

        response = await client.get("/api/fact-checks?episode=nonexistent")

        assert response.status_code == 200
        assert response.json() == []


class TestPostFactCheck:
    """Tests for POST /api/fact-checks endpoint."""

    async def test_post_fact_check_german_fields(self, client):
        """POST /api/fact-checks accepts German field names."""
        payload = {
            "sprecher": "Angela Merkel",
            "behauptung": "Deutschland hat 80 Millionen Einwohner",
            "consistency": "hoch",
            "begruendung": "Laut Statistischem Bundesamt korrekt.",
            "quellen": ["https://destatis.de"],
            "episode_key": "test-ep",
        }

        response = await client.post("/api/fact-checks", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["id"] == 1

        # Verify stored correctly
        assert len(state.fact_checks) == 1
        fc = state.fact_checks[0]
        assert fc["sprecher"] == "Angela Merkel"
        assert fc["consistency"] == "hoch"

    async def test_post_fact_check_english_fields(self, client):
        """POST /api/fact-checks accepts English field names."""
        payload = {
            "speaker": "Joe Biden",
            "claim": "The economy is growing",
            "consistency": "hoch",
            "evidence": "According to official statistics.",
            "sources": ["https://example.com"],
            "episode": "test-ep",
        }

        response = await client.post("/api/fact-checks", json=payload)

        assert response.status_code == 201

        # Verify mapped to German field names in storage
        fc = state.fact_checks[0]
        assert fc["sprecher"] == "Joe Biden"
        assert fc["behauptung"] == "The economy is growing"

    async def test_post_fact_check_mixed_fields(self, client):
        """POST /api/fact-checks handles mixed German/English fields."""
        payload = {
            "sprecher": "Mixed Speaker",
            "claim": "Mixed claim",
            "consistency": "unklar",
        }

        response = await client.post("/api/fact-checks", json=payload)

        assert response.status_code == 201
        fc = state.fact_checks[0]
        assert fc["sprecher"] == "Mixed Speaker"
        assert fc["behauptung"] == "Mixed claim"

    async def test_post_fact_check_list_sources(self, client):
        """POST /api/fact-checks handles list sources correctly."""
        payload = {
            "sprecher": "Test",
            "behauptung": "Test claim",
            "quellen": ["https://source1.com", "https://source2.com"],
        }

        response = await client.post("/api/fact-checks", json=payload)

        assert response.status_code == 201
        fc = state.fact_checks[0]
        assert isinstance(fc["quellen"], list)
        assert len(fc["quellen"]) == 2
        assert fc["quellen"][0] == "https://source1.com"

    async def test_post_fact_check_increments_id(self, client):
        """POST /api/fact-checks assigns incrementing IDs."""
        for i in range(3):
            await client.post("/api/fact-checks", json={
                "sprecher": f"Speaker {i}",
                "behauptung": f"Claim {i}",
            })

        assert len(state.fact_checks) == 3
        assert state.fact_checks[0]["id"] == 1
        assert state.fact_checks[1]["id"] == 2
        assert state.fact_checks[2]["id"] == 3

    async def test_post_fact_check_uses_current_episode(self, client):
        """POST /api/fact-checks uses current episode if not specified."""
        state.current_episode_key = "current-ep"

        response = await client.post("/api/fact-checks", json={
            "sprecher": "Test",
            "behauptung": "Claim",
        })

        assert response.status_code == 201
        assert state.fact_checks[0]["episode_key"] == "current-ep"


class TestPutFactCheck:
    """Tests for PUT /api/fact-checks/{id} endpoint."""

    async def test_put_fact_check_not_found(self, client):
        """PUT /api/fact-checks/{id} returns 404 for unknown ID."""
        payload = {
            "name": "Speaker",
            "claim": "Updated claim",
        }

        response = await client.put("/api/fact-checks/999", json=payload)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_put_fact_check_starts_recheck(self, client, mock_all_services):
        """PUT /api/fact-checks/{id} starts background re-check."""
        # Add existing fact-check
        state.fact_checks.append({
            "id": 1,
            "sprecher": "Original",
            "behauptung": "Original claim",
            "consistency": "unklar",
            "episode_key": "ep1",
        })

        payload = {
            "name": "Updated Speaker",
            "claim": "Updated claim text",
        }

        response = await client.put("/api/fact-checks/1", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "processing"


class TestHealthEndpoint:
    """Tests for GET /api/health endpoint."""

    async def test_health_returns_ok(self, client):
        """GET /api/health returns status ok."""
        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    async def test_health_includes_counts(self, client):
        """GET /api/health includes pending and fact-check counts."""
        # Add some data
        state.pending_claims_blocks.append({"block_id": "b1"})
        state.pending_claims_blocks.append({"block_id": "b2"})
        state.fact_checks.append({"id": 1})

        response = await client.get("/api/health")

        data = response.json()
        assert data["pending_blocks"] == 2
        assert data["fact_checks"] == 1

    async def test_health_includes_current_episode(self, client):
        """GET /api/health includes current episode key."""
        state.current_episode_key = "active-episode"

        response = await client.get("/api/health")

        data = response.json()
        assert data["current_episode"] == "active-episode"

    async def test_health_null_episode_when_not_set(self, client):
        """GET /api/health returns null episode when not set."""
        response = await client.get("/api/health")

        data = response.json()
        assert data["current_episode"] is None


class TestSetEpisodeEndpoint:
    """Tests for POST /api/set-episode endpoint."""

    async def test_set_episode_success(self, client):
        """POST /api/set-episode sets current episode."""
        response = await client.post("/api/set-episode", json={
            "episode_key": "new-episode",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["episode_key"] == "new-episode"
        assert state.current_episode_key == "new-episode"

    async def test_set_episode_accepts_episode_field(self, client):
        """POST /api/set-episode accepts 'episode' field as alias."""
        response = await client.post("/api/set-episode", json={
            "episode": "alias-episode",
        })

        assert response.status_code == 200
        assert state.current_episode_key == "alias-episode"

    async def test_set_episode_rejects_empty(self, client):
        """POST /api/set-episode rejects empty episode_key."""
        response = await client.post("/api/set-episode", json={})

        assert response.status_code == 400
        assert "episode_key missing" in response.json()["detail"]
