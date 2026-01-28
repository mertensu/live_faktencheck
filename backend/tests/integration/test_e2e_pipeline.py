"""
End-to-end integration tests for the full fact-checking pipeline.

These tests use REAL API calls (AssemblyAI, Gemini, Tavily) and are therefore:
- Slow (~30-60 seconds per test)
- Costly (~$0.01-0.05 per run with cheap models)
- Non-deterministic (LLM outputs vary)

Run only for smoke testing:
    uv run pytest -m integration

Skip in CI/regular test runs:
    uv run pytest -m "not integration"
"""

import os
from pathlib import Path

import pytest


# =============================================================================
# Test Configuration
# =============================================================================

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_AUDIO_FILE = FIXTURES_DIR / "test.wav"

# Valid consistency values from the fact-checker
VALID_CONSISTENCY_VALUES = {"hoch", "mittel", "niedrig", "unklar"}


def skip_if_missing_keys():
    """Check if required API keys are set."""
    required_keys = ["ASSEMBLYAI_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"]
    missing = [k for k in required_keys if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing API keys: {', '.join(missing)}")


def skip_if_no_audio():
    """Check if test audio file exists."""
    if not TEST_AUDIO_FILE.exists():
        pytest.skip(f"Test audio file not found: {TEST_AUDIO_FILE}")


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def cheap_models(monkeypatch):
    """Use cheapest models for E2E tests to minimize cost."""
    monkeypatch.setenv("GEMINI_MODEL_CLAIM_EXTRACTION", "gemini-2.0-flash-lite")
    monkeypatch.setenv("GEMINI_MODEL_FACT_CHECKER", "gemini-2.0-flash-lite")


# =============================================================================
# E2E Tests with Audio
# =============================================================================

@pytest.mark.integration
@pytest.mark.slow
def test_full_pipeline_with_audio(cheap_models):
    """
    Test complete pipeline: audio -> transcription -> extraction -> fact-check.

    Uses a short audio file with the claim:
    "Der Spitzensteuersatz in Deutschland betraegt 42 Prozent"

    Runs in subprocess to avoid pytest-asyncio conflicts with ChatGoogleGenerativeAI.
    See: https://github.com/langchain-ai/langchain-google/issues/357
    """
    import subprocess
    import sys
    import json
    import time

    skip_if_missing_keys()
    skip_if_no_audio()

    code = f'''
import os
import json
import asyncio
from dotenv import load_dotenv
load_dotenv()

os.environ["GEMINI_MODEL_CLAIM_EXTRACTION"] = "gemini-2.0-flash-lite"
os.environ["GEMINI_MODEL_FACT_CHECKER"] = "gemini-2.0-flash-lite"

from backend.services.transcription import TranscriptionService
from backend.services.claim_extraction import ClaimExtractor
from backend.services.fact_checker import FactChecker

# Step 1: Read and transcribe audio
print("[TEST] Step 1: Transcribing audio...", flush=True)
with open("{TEST_AUDIO_FILE}", "rb") as f:
    audio_data = f.read()
print(f"[TEST] Audio file size: {{len(audio_data)}} bytes", flush=True)

transcription_service = TranscriptionService()
transcript = transcription_service.transcribe(audio_data)
print(f"[TEST] Transcript: {{transcript}}", flush=True)
assert len(transcript) > 0

# Step 2: Extract claims (async - google.genai works fine)
print("[TEST] Step 2: Extracting claims...", flush=True)
extractor = ClaimExtractor()
claims = asyncio.run(extractor.extract_async(transcript, info="E2E Test"))
print(f"[TEST] Extracted {{len(claims)}} claims", flush=True)
assert len(claims) > 0

for claim in claims:
    print(f"[TEST]   - {{claim.name}}: {{claim.claim}}", flush=True)

# Step 3: Fact-check claims (sync - avoids ChatGoogleGenerativeAI async bugs)
print("[TEST] Step 3: Fact-checking claims...", flush=True)
fact_checker = FactChecker()
claims_dicts = [{{"name": c.name, "claim": c.claim}} for c in claims]
results = fact_checker.check_claims(claims_dicts)
print(f"[TEST] Got {{len(results)}} fact-check results", flush=True)
assert len(results) > 0

# Step 4: Verify results
print("[TEST] Step 4: Verifying results...", flush=True)
valid_values = {{"hoch", "mittel", "niedrig", "unklar"}}
for result in results:
    assert "speaker" in result
    assert "original_claim" in result
    assert "consistency" in result
    assert "evidence" in result
    assert result["consistency"] in valid_values
    print(f"[TEST] Result: {{result['speaker']}} - {{result['consistency']}}", flush=True)

print("SUCCESS")
'''

    project_root = Path(__file__).parent.parent.parent.parent
    clean_env = {k: v for k, v in os.environ.items()
                 if not k.startswith(('PYTEST', '_PYTEST', 'COV_'))}

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        cwd=str(project_root),
        env=clean_env,
    )

    # Poll with timeout (longer for full pipeline)
    timeout = 180
    for i in range(timeout // 2):
        time.sleep(2)
        ret = proc.poll()
        if ret is not None:
            stdout, stderr = proc.communicate()
            break
    else:
        proc.kill()
        proc.wait()
        pytest.fail(f"Subprocess timed out after {timeout}s")

    print(stdout)
    if ret != 0:
        print(f"STDERR: {stderr}")
        pytest.fail(f"Subprocess failed with code {ret}: {stderr}")

    assert "SUCCESS" in stdout


# =============================================================================
# E2E Tests with Text (skips transcription - faster/cheaper)
# =============================================================================

@pytest.mark.integration
@pytest.mark.slow
def test_full_pipeline_with_text(cheap_models):
    """
    Test pipeline without transcription: text -> extraction -> fact-check.

    Skips AssemblyAI transcription for faster, cheaper E2E testing.
    Runs in subprocess to avoid pytest-asyncio conflicts with ChatGoogleGenerativeAI.
    See: https://github.com/langchain-ai/langchain-google/issues/357
    """
    import subprocess
    import sys
    import json
    import time

    skip_if_missing_keys()

    code = '''
import os
import json
import asyncio
from dotenv import load_dotenv
load_dotenv()

os.environ["GEMINI_MODEL_CLAIM_EXTRACTION"] = "gemini-2.0-flash-lite"
os.environ["GEMINI_MODEL_FACT_CHECKER"] = "gemini-2.0-flash-lite"

from backend.services.claim_extraction import ClaimExtractor
from backend.services.fact_checker import FactChecker

# Test text with verifiable claim about German tax rate
test_text = """
Moderator: Herr Schmidt, wie hoch ist eigentlich der Spitzensteuersatz in Deutschland?
Schmidt: Der Spitzensteuersatz in Deutschland betraegt 42 Prozent.
Moderator: Und ab welchem Einkommen gilt dieser Satz?
Schmidt: Ab einem zu versteuernden Einkommen von etwa 66.000 Euro im Jahr.
"""

# Step 1: Extract claims from text (async - google.genai works fine)
print("[TEST] Step 1: Extracting claims from text...", flush=True)
extractor = ClaimExtractor()
claims = asyncio.run(extractor.extract_async(test_text, info="E2E Test: Spitzensteuersatz"))
print(f"[TEST] Extracted {len(claims)} claims", flush=True)
assert len(claims) > 0

for claim in claims:
    print(f"[TEST]   - {claim.name}: {claim.claim}", flush=True)

# Step 2: Fact-check claims (sync - avoids ChatGoogleGenerativeAI async bugs)
print("[TEST] Step 2: Fact-checking claims...", flush=True)
fact_checker = FactChecker()
claims_dicts = [{"name": c.name, "claim": c.claim} for c in claims]
results = fact_checker.check_claims(claims_dicts)
print(f"[TEST] Got {len(results)} fact-check results", flush=True)
assert len(results) > 0

# Step 3: Verify results
print("[TEST] Step 3: Verifying results...", flush=True)
valid_values = {"hoch", "mittel", "niedrig", "unklar"}
for result in results:
    assert "speaker" in result
    assert "original_claim" in result
    assert "consistency" in result
    assert "evidence" in result
    assert result["consistency"] in valid_values
    print(f"[TEST] Result: {result['speaker']} - {result['consistency']}", flush=True)

# Check that at least one fact-check mentions the tax rate claim
tax_claims = [r for r in results if "42" in r["original_claim"] or "Steuersatz" in r["original_claim"]]
assert len(tax_claims) > 0, "Expected at least one fact-check about the 42% tax rate"

print("SUCCESS")
'''

    project_root = Path(__file__).parent.parent.parent.parent
    clean_env = {k: v for k, v in os.environ.items()
                 if not k.startswith(('PYTEST', '_PYTEST', 'COV_'))}

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        cwd=str(project_root),
        env=clean_env,
    )

    # Poll with timeout
    timeout = 180
    for i in range(timeout // 2):
        time.sleep(2)
        ret = proc.poll()
        if ret is not None:
            stdout, stderr = proc.communicate()
            break
    else:
        proc.kill()
        proc.wait()
        pytest.fail(f"Subprocess timed out after {timeout}s")

    print(stdout)
    if ret != 0:
        print(f"STDERR: {stderr}")
        pytest.fail(f"Subprocess failed with code {ret}: {stderr}")

    assert "SUCCESS" in stdout


@pytest.mark.integration
def test_direct_fact_check_single_claim(cheap_models):
    """
    Test fact-checker service directly.

    This is the fastest E2E test - runs in subprocess to avoid pytest-asyncio conflicts.
    Uses Popen with polling instead of subprocess.run to avoid blocking issues.
    """
    import subprocess
    import sys
    import json
    import time

    skip_if_missing_keys()

    # Run the sync test in a subprocess to avoid event loop conflicts
    # IMPORTANT: Use sync invoke() not ainvoke() - ChatGoogleGenerativeAI has async bugs
    # See: https://github.com/langchain-ai/langchain-google/issues/357
    code = '''
import os
import json
from dotenv import load_dotenv
load_dotenv()

os.environ["GEMINI_MODEL_FACT_CHECKER"] = "gemini-2.0-flash-lite"

from backend.services.fact_checker import FactChecker

fc = FactChecker()
result = fc.check_claim(
    speaker="Test Speaker",
    claim="Der Spitzensteuersatz in Deutschland betraegt 42 Prozent."
)
print(json.dumps(result))
'''

    project_root = Path(__file__).parent.parent.parent.parent

    # Clean environment - remove pytest-related vars that might affect subprocess
    clean_env = {k: v for k, v in os.environ.items()
                 if not k.startswith(('PYTEST', '_PYTEST', 'COV_'))}

    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,  # Prevent waiting on stdin
        text=True,
        cwd=str(project_root),
        env=clean_env,
    )

    # Poll with timeout
    timeout = 120  # Increased timeout for slow API calls
    for i in range(timeout // 2):
        time.sleep(2)
        ret = proc.poll()
        if ret is not None:
            stdout, stderr = proc.communicate()
            break
    else:
        proc.kill()
        proc.wait()
        pytest.fail(f"Subprocess timed out after {timeout}s")

    if ret != 0:
        print(f"STDERR: {stderr}")
        pytest.fail(f"Subprocess failed with code {ret}: {stderr}")

    # Parse the JSON result from stdout (last line)
    output_lines = stdout.strip().split('\n')
    result = json.loads(output_lines[-1])

    print(f"\n[TEST] Result: {result['consistency']}")
    print(f"[TEST] Evidence: {result['evidence'][:100]}...")

    assert result["speaker"] == "Test Speaker"
    assert "42" in result["original_claim"]
    assert result["consistency"] in VALID_CONSISTENCY_VALUES
    assert result["evidence"]
