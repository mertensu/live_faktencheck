"""
Tests for claims management API endpoints.

Tests:
- POST /api/pending-claims
- GET /api/pending-claims
- POST /api/approve-claims
"""


from backend import state


class TestPendingClaimsEndpoint:
    """Tests for /api/pending-claims endpoints."""

    async def test_post_pending_claims(self, client):
        """POST /api/pending-claims stores claims and returns success."""
        payload = {
            "claims": [
                {"name": "Speaker A", "claim": "Test claim 1"},
                {"name": "Speaker B", "claim": "Test claim 2"},
            ],
            "block_id": "test-block-001",
            "episode_key": "test-episode",
        }

        response = await client.post("/api/pending-claims", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["block_id"] == "test-block-001"
        assert data["claims_count"] == 2

        # Verify state was updated
        assert len(state.pending_claims_blocks) == 1
        block = state.pending_claims_blocks[0]
        assert block["block_id"] == "test-block-001"
        assert block["claims_count"] == 2
        assert block["status"] == "pending"

    async def test_post_pending_claims_generates_block_id(self, client):
        """POST /api/pending-claims generates block_id if not provided."""
        payload = {
            "claims": [{"name": "Speaker", "claim": "A claim"}],
        }

        response = await client.post("/api/pending-claims", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["block_id"].startswith("block_")

    async def test_post_pending_claims_unique_block_id(self, client):
        """POST /api/pending-claims ensures unique block_id."""
        # Add first block
        payload1 = {
            "claims": [{"name": "A", "claim": "Claim 1"}],
            "block_id": "duplicate-id",
        }
        await client.post("/api/pending-claims", json=payload1)

        # Add second block with same ID
        payload2 = {
            "claims": [{"name": "B", "claim": "Claim 2"}],
            "block_id": "duplicate-id",
        }
        response = await client.post("/api/pending-claims", json=payload2)

        assert response.status_code == 201
        data = response.json()
        # Should have been modified to be unique
        assert data["block_id"] == "duplicate-id_1"

    async def test_get_pending_claims_empty(self, client):
        """GET /api/pending-claims returns empty list when no claims."""
        response = await client.get("/api/pending-claims")

        assert response.status_code == 200
        assert response.json() == []

    async def test_get_pending_claims_returns_all(self, client):
        """GET /api/pending-claims returns all pending blocks."""
        # Add some claims
        for i in range(3):
            await client.post("/api/pending-claims", json={
                "claims": [{"name": f"Speaker {i}", "claim": f"Claim {i}"}],
                "block_id": f"block-{i}",
            })

        response = await client.get("/api/pending-claims")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    async def test_get_pending_claims_sorted_by_timestamp(self, client):
        """GET /api/pending-claims returns blocks newest first."""
        # Add blocks with specific timestamps
        state.pending_claims_blocks.append({
            "block_id": "old",
            "timestamp": "2024-01-01T10:00:00",
            "claims_count": 1,
            "claims": [],
            "status": "pending",
        })
        state.pending_claims_blocks.append({
            "block_id": "new",
            "timestamp": "2024-01-02T10:00:00",
            "claims_count": 1,
            "claims": [],
            "status": "pending",
        })

        response = await client.get("/api/pending-claims")

        data = response.json()
        assert data[0]["block_id"] == "new"
        assert data[1]["block_id"] == "old"


class TestApproveClaimsEndpoint:
    """Tests for /api/approve-claims endpoint."""

    async def test_approve_claims_triggers_fact_checking(self, client, mock_all_services):
        """POST /api/approve-claims starts background fact-checking."""
        payload = {
            "claims": [
                {"name": "Speaker A", "claim": "Test claim to verify"},
            ],
            "block_id": "test-block",
            "episode_key": "test-episode",
        }

        response = await client.post("/api/approve-claims", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "processing"
        assert data["claims_count"] == 1

    async def test_approve_claims_empty_list_rejected(self, client):
        """POST /api/approve-claims rejects empty claims list."""
        payload = {
            "claims": [],
            "block_id": "test-block",
        }

        response = await client.post("/api/approve-claims", json=payload)

        assert response.status_code == 400
        assert "No claims selected" in response.json()["detail"]

    async def test_approve_claims_uses_context_from_block(self, client, mock_all_services):
        """POST /api/approve-claims retrieves context from pending block."""
        # First add a pending block with context
        state.pending_claims_blocks.append({
            "block_id": "context-block",
            "headline": "Important context headline",
            "claims": [{"name": "X", "claim": "Y"}],
            "status": "pending",
        })

        payload = {
            "claims": [{"name": "X", "claim": "Y"}],
            "block_id": "context-block",
        }

        response = await client.post("/api/approve-claims", json=payload)

        assert response.status_code == 202

    async def test_approve_claims_uses_current_episode(self, client, mock_all_services):
        """POST /api/approve-claims uses current episode if not specified."""
        state.current_episode_key = "default-episode"

        payload = {
            "claims": [{"name": "A", "claim": "B"}],
        }

        response = await client.post("/api/approve-claims", json=payload)

        assert response.status_code == 202


class TestTextBlockEndpoint:
    """Tests for /api/text-block endpoint."""

    async def test_text_block_accepts_valid_request(self, client, mock_all_services):
        """POST /api/text-block accepts text and returns 202."""
        payload = {
            "text": "This is the article content with some claims.",
            "headline": "Test Headline",
        }

        response = await client.post("/api/text-block", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["source_id"].startswith("article-")

    async def test_text_block_uses_provided_source_id(self, client, mock_all_services):
        """POST /api/text-block uses provided source_id."""
        payload = {
            "text": "Article content here.",
            "headline": "Headline",
            "source_id": "my-custom-source",
        }

        response = await client.post("/api/text-block", json=payload)

        assert response.status_code == 202
        assert response.json()["source_id"] == "my-custom-source"

    async def test_text_block_rejects_empty_text(self, client):
        """POST /api/text-block rejects empty text."""
        payload = {
            "text": "",
            "headline": "Headline",
        }

        response = await client.post("/api/text-block", json=payload)

        assert response.status_code == 400
        assert "No text provided" in response.json()["detail"]

    async def test_text_block_rejects_whitespace_only(self, client):
        """POST /api/text-block rejects whitespace-only text."""
        payload = {
            "text": "   \n\t  ",
            "headline": "Headline",
        }

        response = await client.post("/api/text-block", json=payload)

        assert response.status_code == 400
