"""
Streaming session (SG-3): the live fast lane's orchestrator.

One ``StreamingSession`` per connected browser. It relays PCM audio to AssemblyAI
Universal-Streaming (v3), collects finalized turns into a rolling window, and — on each
window — drives the pluggable ``ClaimGate`` and ``FastFactChecker`` autopilot-style,
writing ``check_depth="fast"`` rows the same way the batch pipeline writes deep ones.

The windowing/pipeline logic (``handle_turn`` / ``_flush_window``) takes its
collaborators by injection so it is unit-testable with no network. The AssemblyAI
wiring (``start`` / ``feed`` / ``stop``) is a thin layer on top.
"""

import os
import asyncio
import logging
from datetime import datetime

from backend.utils import build_fact_check_dict
from .transcription import keyterms_from_guests

logger = logging.getLogger(__name__)

# A window flushes once it holds at least this many sentence-ending marks, or this
# many finalized turns, whichever comes first. Small = low latency, closer to live.
WINDOW_MIN_SENTENCES = int(os.getenv("STREAM_WINDOW_MIN_SENTENCES", "2"))
WINDOW_MAX_TURNS = int(os.getenv("STREAM_WINDOW_MAX_TURNS", "3"))
# Sample rate the browser must send (PCM16 mono). 16 kHz is AssemblyAI's expected rate.
STREAM_SAMPLE_RATE = int(os.getenv("STREAM_SAMPLE_RATE", "16000"))


def _count_sentences(text: str) -> int:
    return sum(text.count(m) for m in (".", "!", "?"))


class StreamingSession:
    """Orchestrates one live streaming connection."""

    def __init__(
        self,
        session_id: str,
        gate,
        fast_checker,
        db,
        *,
        guests: list[str] | None = None,
        context: str = "",
        conversation_type: str = "debate",
        excluded_speakers: list[str] | None = None,
        episode_date: str | None = None,
        on_event=None,
    ):
        self.session_id = session_id
        self.gate = gate
        self.fast_checker = fast_checker
        self.db = db
        self.guests = guests or []
        self.context = context
        self.conversation_type = conversation_type
        self.excluded_speakers = excluded_speakers or []
        self.episode_date = episode_date
        self.on_event = on_event  # optional async callable(dict) -> pushes JSON to browser

        self._buffer: list[str] = []          # finalized turn texts, current window
        self._sentence_count = 0
        self._previous_context: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._client = None                   # AssemblyAI AsyncStreamingClient (set in start)

    # ---- event emission -----------------------------------------------------
    async def _emit(self, event: dict) -> None:
        if self.on_event is None:
            return
        try:
            await self.on_event(event)
        except Exception:
            logger.exception("on_event handler failed")

    def _track(self, coro) -> None:
        """Run a coroutine in the background without blocking the receive loop."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- windowing (unit-testable) ------------------------------------------
    async def handle_turn(self, transcript: str, end_of_turn: bool, speaker_label: str | None = None) -> None:
        """Feed one turn event. Buffers finalized turns; flushes a full window."""
        text = (transcript or "").strip()
        if not text:
            return
        # Live partial for the UI; only finalized turns enter the buffer.
        await self._emit({"type": "partial" if not end_of_turn else "turn", "text": text, "speaker": speaker_label})
        if not end_of_turn:
            return
        line = f"{speaker_label}: {text}" if speaker_label else text
        self._buffer.append(line)
        self._sentence_count += _count_sentences(text)
        if self._sentence_count >= WINDOW_MIN_SENTENCES or len(self._buffer) >= WINDOW_MAX_TURNS:
            await self._flush_window()

    async def _flush_window(self) -> None:
        """Gate the current window and fast-check any check-worthy claims."""
        if not self._buffer:
            return
        window_text = "\n".join(self._buffer)
        self._buffer = []
        self._sentence_count = 0

        try:
            claims = await self.gate.gate(
                window_text,
                self.guests,
                context=self.context,
                conversation_type=self.conversation_type,
                excluded_speakers=self.excluded_speakers,
                previous_context=self._previous_context,
            )
        except Exception:
            logger.exception("Window gate failed; skipping window")
            claims = []

        # Carry a short tail for cross-window continuity.
        self._previous_context = window_text[-300:]

        for claim in claims:
            name = getattr(claim, "name", "") or ""
            text = getattr(claim, "claim", "") or ""
            if not text:
                continue
            self._track(self._check_and_store(name, text))

    async def _check_and_store(self, speaker: str, claim: str) -> None:
        """Insert a spinner placeholder, run the fast check, update in place."""
        now = datetime.now().isoformat()
        placeholder = {
            "sprecher": speaker,
            "behauptung": claim,
            "consistency": "",
            "begruendung": "",
            "quellen": [],
            "timestamp": now,
            "session_id": self.session_id,
            "status": "processing",
            "check_depth": "fast",
        }
        pid = await self.db.add_fact_check(placeholder)
        await self._emit({"type": "claim_processing", "id": pid, "speaker": speaker, "claim": claim})

        try:
            result = await self.fast_checker.check_claim_async(
                speaker=speaker, claim=claim, context=self.context, episode_date=self.episode_date
            )
            fc = build_fact_check_dict(result, self.session_id, speaker_fallback=speaker, claim_fallback=claim)
            fc["check_depth"] = "fast"
            await self.db.update_fact_check(pid, fc)
            await self._emit({"type": "claim_result", "id": pid, "consistency": fc["consistency"]})
        except Exception:
            logger.exception("Fast check failed for streamed claim")
            await self.db.update_fact_check(pid, {
                "sprecher": speaker, "behauptung": claim, "consistency": "",
                "begruendung": "Fehler bei der Schnellprüfung", "quellen": [],
                "timestamp": now, "session_id": self.session_id, "status": "error",
                "check_depth": "fast",
            })
            await self._emit({"type": "claim_error", "id": pid})

    # ---- AssemblyAI wiring (thin; covered by SG-4 e2e, not unit tests) -------
    async def start(self, api_key: str) -> None:
        """Open the AssemblyAI v3 streaming connection and register handlers."""
        from assemblyai.streaming.v3 import (
            AsyncStreamingClient, StreamingClientOptions, StreamingParameters,
            StreamingEvents, Encoding,
        )

        self._client = AsyncStreamingClient(StreamingClientOptions(api_key=api_key))
        loop = asyncio.get_running_loop()

        def _on_turn(_client, event):
            # SDK invokes handlers from its own thread/loop; hop back to ours.
            asyncio.run_coroutine_threadsafe(
                self.handle_turn(
                    getattr(event, "transcript", ""),
                    bool(getattr(event, "end_of_turn", False)),
                    getattr(event, "speaker_label", None),
                ),
                loop,
            )

        self._client.on(StreamingEvents.Turn, _on_turn)

        params = StreamingParameters(
            sample_rate=STREAM_SAMPLE_RATE,
            encoding=Encoding.pcm_s16le,
            language_code="de",
            format_turns=True,
            speaker_labels=True,
            keyterms_prompt=keyterms_from_guests(self.guests) or None,
        )
        await self._client.connect(params)
        logger.info(f"[stream:{self.session_id}] AssemblyAI streaming connected")

    async def feed(self, audio: bytes) -> None:
        if self._client is not None:
            await self._client.stream(audio)

    async def stop(self) -> None:
        """Flush the tail window, close AssemblyAI, and drain background tasks."""
        try:
            await self._flush_window()
        finally:
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:
                    logger.exception("Error disconnecting AssemblyAI stream")
                self._client = None
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)
        logger.info(f"[stream:{self.session_id}] session stopped")
