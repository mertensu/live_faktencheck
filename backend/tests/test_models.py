"""
Tests for Pydantic request/response models.

Tests:
- FactCheckRequest German/English field handling
- HealthResponse
"""

from backend.models import FactCheckRequest, HealthResponse


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
            session_id="maischberger-2024-01-15",
        )

        assert request.sprecher == "Angela Merkel"
        assert request.behauptung == "Deutschland hat 80 Millionen Einwohner"
        assert request.consistency == "hoch"
        assert request.begruendung == "Statistisches Bundesamt bestätigt dies."
        assert request.quellen == ["https://destatis.de"]
        assert request.session_id == "maischberger-2024-01-15"

    def test_english_fields(self):
        """FactCheckRequest accepts English field names."""
        request = FactCheckRequest(
            speaker="Joe Biden",
            claim="The economy is growing",
            original_claim="The economy is growing fast",
            consistency="hoch",
            evidence="Official statistics confirm this.",
            sources=["https://example.com"],
            session_id="test-session",
        )

        assert request.speaker == "Joe Biden"
        assert request.claim == "The economy is growing"
        assert request.original_claim == "The economy is growing fast"
        assert request.evidence == "Official statistics confirm this."
        assert request.sources == ["https://example.com"]
        assert request.session_id == "test-session"

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


class TestResponseModels:
    """Tests for response models."""

    def test_health_response(self):
        """HealthResponse accepts all fields."""
        response = HealthResponse(
            status="ok",
            active_sessions=2,
            fact_checks=10,
            in_flight=1,
        )

        assert response.status == "ok"
        assert response.active_sessions == 2
        assert response.pending_blocks == 0
        assert response.fact_checks == 10
        assert response.in_flight == 1
