"""
WebSocket endpoint guard tests (SG-4).

Runs the app under a single lifespan (own in-memory DB seeded from ACCESS_CODES) inside
a worker thread, so the TestClient's portal loop owns the aiosqlite connection and the
module-global claim queue binds to exactly one loop. All guard cases share that one app
instance. Only the pre-accept guard paths are exercised here — the AssemblyAI relay is
covered by the local end-to-end check in the plan, not by unit tests.
"""

import os

import anyio
from unittest.mock import patch
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

WS_POLICY_VIOLATION = 1008
WS_TRY_AGAIN_LATER = 1013


def _run_guard_cases() -> dict[str, int]:
    """Open the app once; probe each guard path; return {case: close_code}."""
    env = {"ACCESS_CODES": "tester:wscode", "DB_MODE": "memory"}
    results: dict[str, int] = {}

    def close_code(client, url: str) -> int:
        try:
            with client.websocket_connect(url):
                pass
            return 1000  # accepted (should not happen for guard cases)
        except WebSocketDisconnect as e:
            return e.code

    # No ASSEMBLYAI key -> the "not configured" guard fires for an otherwise-valid conn.
    with patch.dict(os.environ, {**env, "ASSEMBLYAI_API_KEY": ""}, clear=False):
        from backend.app import app
        with TestClient(app) as client:
            results["bad_code"] = close_code(client, "/api/stream?code=nope&session_id=s1")
            results["missing_session"] = close_code(client, "/api/stream?code=wscode")
            results["no_api_key"] = close_code(client, "/api/stream?code=wscode&session_id=s1")
    return results


async def test_stream_guards():
    results = await anyio.to_thread.run_sync(_run_guard_cases)
    assert results["bad_code"] == WS_POLICY_VIOLATION
    assert results["missing_session"] == WS_POLICY_VIOLATION
    assert results["no_api_key"] == WS_TRY_AGAIN_LATER
