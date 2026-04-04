"""
Tests for Pydantic request/response models.

Tests:
- FactCheckRequest German/English field handling
- ClaimApprovalRequest validation
- Other model validation
"""

import pytest
from pydantic import ValidationError

from backend.models import (
    FactCheckRequest,
    ClaimApprovalRequest,
    PendingClaimsRequest,
    TextBlockRequest,
    ClaimUpdateRequest,
    SetEpisodeRequest,
    ProcessingResponse,
    HealthResponse,
)


class TestFactCheckRequest:
    """Tests for FactCheckRequest model."""

    def test_german_fields(self):
        """FactCheckRequest accepts German field names."""
        request = FactCheckRequest(
            sprecher="Angela Merkel",
            behauptung="Deutschland hat 80 Millionen Einwohner",
            consistency="hoch",
            begruendung="Statistisches Bundesamt bestätigt dies.",
            quellen=["https://destatis.de"],
            episode_key="maischberger-2024-01-15",
        )

        assert request.sprecher == "Angela Merkel"
        assert request.behauptung == "Deutschland hat 80 Millionen Einwohner"
        assert request.consistency == "hoch"
        assert request.begruendung == "Statistisches Bundesamt bestätigt dies."
        assert request.quellen == ["https://destatis.de"]
        assert request.episode_key == "maischberger-2024-01-15"

    def test_english_fields(self):
        """FactCheckRequest accepts English field names."""
        request = FactCheckRequest(
            speaker="Joe Biden",
            claim="The economy is growing",
            original_claim="The economy is growing fast",
            consistency="hoch",
            evidence="Official statistics confirm this.",
            sources=["https://example.com"],
            episode="test-episode",
        )

        assert request.speaker == "Joe Biden"
        assert request.claim == "The economy is growing"
        assert request.original_claim == "The economy is growing fast"
        assert request.evidence == "Official statistics confirm this."
        assert request.sources == ["https://example.com"]
        assert request.episode == "test-episode"

    def test_mixed_german_english_fields(self):
        """FactCheckRequest accepts mixed German/English fields."""
        request = FactCheckRequest(
            sprecher="Mixed Speaker",
            claim="English claim text",
            consistency="niedrig",
            begruendung="German reasoning",
        )

        assert request.sprecher == "Mixed Speaker"
        assert request.claim == "English claim text"
        assert request.begruendung == "German reasoning"

    def test_all_fields_optional(self):
        """FactCheckRequest allows all fields to be optional."""
        request = FactCheckRequest()

        assert request.sprecher is None
        assert request.speaker is None
        assert request.behauptung is None
        assert request.claim is None

    def test_legacy_urteil_field(self):
        """FactCheckRequest accepts legacy 'urteil' field."""
        request = FactCheckRequest(
            sprecher="Test",
            urteil="wahr",
        )

        assert request.urteil == "wahr"

    def test_sources_accepts_any_type(self):
        """FactCheckRequest sources/quellen accept any list items."""
        request = FactCheckRequest(
            quellen=[
                "https://simple-url.com",
                {"url": "https://complex.com", "title": "Complex Source"},
            ]
        )

        assert len(request.quellen) == 2
        assert isinstance(request.quellen[1], dict)


class TestClaimApprovalRequest:
    """Tests for ClaimApprovalRequest model."""

    def test_valid_request(self):
        """ClaimApprovalRequest accepts valid data."""
        request = ClaimApprovalRequest(
            claims=[
                {"name": "Speaker A", "claim": "Claim 1"},
                {"name": "Speaker B", "claim": "Claim 2"},
            ],
            block_id="block-123",
            episode_key="test-episode",
        )

        assert len(request.claims) == 2
        assert request.block_id == "block-123"
        assert request.episode_key == "test-episode"

    def test_claims_required(self):
        """ClaimApprovalRequest requires claims field."""
        with pytest.raises(ValidationError) as exc_info:
            ClaimApprovalRequest(block_id="test")

        assert "claims" in str(exc_info.value)

    def test_optional_fields(self):
        """ClaimApprovalRequest optional fields default to None."""
        request = ClaimApprovalRequest(
            claims=[{"name": "X", "claim": "Y"}]
        )

        assert request.block_id is None
        assert request.episode_key is None

    def test_claims_as_list_of_dicts(self):
        """ClaimApprovalRequest claims must be list of dicts."""
        request = ClaimApprovalRequest(
            claims=[
                {"name": "A", "claim": "B", "extra": "field"},
            ]
        )

        assert request.claims[0]["extra"] == "field"


class TestPendingClaimsRequest:
    """Tests for PendingClaimsRequest model."""

    def test_valid_request(self):
        """PendingClaimsRequest accepts valid data."""
        request = PendingClaimsRequest(
            block_id="test-block",
            timestamp="2024-01-15T10:30:00",
            claims=[{"name": "Speaker", "claim": "Statement"}],
            episode_key="episode-1",
        )

        assert request.block_id == "test-block"
        assert request.timestamp == "2024-01-15T10:30:00"
        assert len(request.claims) == 1

    def test_all_optional_with_defaults(self):
        """PendingClaimsRequest has sensible defaults."""
        request = PendingClaimsRequest()

        assert request.block_id is None
        assert request.timestamp is None
        assert request.claims == []
        assert request.episode_key is None


class TestTextBlockRequest:
    """Tests for TextBlockRequest model."""

    def test_valid_request(self):
        """TextBlockRequest accepts valid data."""
        request = TextBlockRequest(
            text="Article content here.",
            headline="Breaking News",
            publication_date="2024-01-15",
            source_id="article-123",
        )

        assert request.text == "Article content here."
        assert request.headline == "Breaking News"
        assert request.publication_date == "2024-01-15"
        assert request.source_id == "article-123"

    def test_text_required(self):
        """TextBlockRequest requires text field."""
        with pytest.raises(ValidationError) as exc_info:
            TextBlockRequest(headline="No text provided")

        assert "text" in str(exc_info.value)

    def test_headline_defaults_empty(self):
        """TextBlockRequest headline defaults to empty string."""
        request = TextBlockRequest(text="Some text")

        assert request.headline == ""

    def test_optional_fields(self):
        """TextBlockRequest optional fields default to None."""
        request = TextBlockRequest(text="Text")

        assert request.publication_date is None
        assert request.source_id is None


class TestClaimUpdateRequest:
    """Tests for ClaimUpdateRequest model."""

    def test_valid_request(self):
        """ClaimUpdateRequest accepts valid data."""
        request = ClaimUpdateRequest(
            name="Updated Speaker",
            claim="Updated claim text",
            episode_key="ep-1",
        )

        assert request.name == "Updated Speaker"
        assert request.claim == "Updated claim text"
        assert request.episode_key == "ep-1"

    def test_name_and_claim_required(self):
        """ClaimUpdateRequest requires name and claim."""
        with pytest.raises(ValidationError) as exc_info:
            ClaimUpdateRequest(name="Only name")

        assert "claim" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            ClaimUpdateRequest(claim="Only claim")

        assert "name" in str(exc_info.value)


class TestSetEpisodeRequest:
    """Tests for SetEpisodeRequest model."""

    def test_episode_key_field(self):
        """SetEpisodeRequest accepts episode_key."""
        request = SetEpisodeRequest(episode_key="maischberger-2024")

        assert request.episode_key == "maischberger-2024"

    def test_episode_alias_field(self):
        """SetEpisodeRequest accepts episode as alias."""
        request = SetEpisodeRequest(episode="hartaberfair-2024")

        assert request.episode == "hartaberfair-2024"

    def test_both_optional(self):
        """SetEpisodeRequest allows empty request."""
        request = SetEpisodeRequest()

        assert request.episode_key is None
        assert request.episode is None


class TestResponseModels:
    """Tests for response models."""

    def test_processing_response(self):
        """ProcessingResponse accepts all fields."""
        response = ProcessingResponse(
            status="processing",
            message="Task started",
            episode_key="ep-1",
            claims_count=5,
            source_id="src-1",
            block_id="blk-1",
        )

        assert response.status == "processing"
        assert response.claims_count == 5

    def test_processing_response_minimal(self):
        """ProcessingResponse only requires status."""
        response = ProcessingResponse(status="ok")

        assert response.status == "ok"
        assert response.message is None

    def test_health_response(self):
        """HealthResponse accepts all fields."""
        response = HealthResponse(
            status="ok",
            current_episode="test-ep",
            pending_blocks=3,
            fact_checks=10,
        )

        assert response.status == "ok"
        assert response.current_episode == "test-ep"
        assert response.pending_blocks == 3
        assert response.fact_checks == 10
