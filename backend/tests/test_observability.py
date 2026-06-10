"""Tests for Logfire configuration."""

from unittest.mock import patch


def test_configure_logfire_is_idempotent_and_calls_logfire():
    import backend.services.observability as obs
    obs._configured = False

    with patch("logfire.configure") as cfg, patch("logfire.instrument_pydantic_ai") as instr:
        obs.configure_logfire()
        obs.configure_logfire()  # second call is a no-op

    cfg.assert_called_once()
    instr.assert_called_once()
    # send_to_logfire must be 'if-token-present' so it is silent without a token.
    assert cfg.call_args.kwargs.get("send_to_logfire") == "if-token-present"
