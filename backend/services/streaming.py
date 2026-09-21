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

# Speaker label->name resolution (live lane): labels (A/B/…) are stable within a session,
# so resolve once enough transcript has accrued and cache the mapping — then re-resolve
# every N further turns to catch speakers who only appear later. It runs in the background
# off the hot path, so it never adds latency to a fact-check.
SPEAKER_RESOLVE_MIN_TURNS = int(os.getenv("STREAM_SPEAKER_RESOLVE_MIN_TURNS", "6"))
SPEAKER_RESOLVE_EVERY_TURNS = int(os.getenv("STREAM_SPEAKER_RESOLVE_EVERY_TURNS", "20"))
SPEAKER_RESOLVE_MAX_LINES = int(os.getenv("STREAM_SPEAKER_RESOLVE_MAX_LINES", "60"))

# Optional hard cap on how many distinct speakers AssemblyAI's online diarization may
# cluster into. Left unset it is derived from the guest list (+1 for the moderator), which
# gives the reclusterer a hint on hard single-mic TV audio. Env overrides the derivation.
STREAM_MAX_SPEAKERS = os.getenv("STREAM_MAX_SPEAKERS")


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
        resolve_speakers=None,
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
        # optional async callable(transcript, guests, conversation_type) -> {label: name}
        self._resolve_speakers_fn = resolve_speakers

        # Current window: finalized turns as {"turn_order", "speaker" (label), "text"}.
        self._buffer: list[dict] = []
        self._sentence_count = 0
        self._previous_context: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._client = None                   # AssemblyAI AsyncStreamingClient (set in start)

        self._transcript_log: list[str] = []  # all finalized "label: text" lines (for resolution)
        self._speaker_map: dict[str, str] = {}  # label -> real name, filled in the background
        self._turns_since_resolve = 0
        self._resolving = False

        # AssemblyAI v3 diarizes by online reclustering: a turn's speaker_label is
        # provisional and may be corrected later by a SpeakerRevisionEvent (matched by
        # turn_order). We keep every finalized turn and the claims it produced so a
        # revision can rewrite the stored speaker retroactively.
        self._turns: dict[int, dict] = {}            # turn_order -> {"speaker", "text"}
        self._turn_claims: dict[int, list] = {}      # turn_order -> [(fact_check_id, label)]

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

    # ---- speaker label -> name resolution (background, cached) ---------------
    def _maybe_resolve_speakers(self) -> None:
        """Kick off a background label->name resolution when it's due.

        First pass once ``SPEAKER_RESOLVE_MIN_TURNS`` turns exist, then every
        ``SPEAKER_RESOLVE_EVERY_TURNS`` turns. No-op without a resolver or guests (the
        resolver needs candidate names), or while one is already running.
        """
        if self._resolve_speakers_fn is None or not self.guests or self._resolving:
            return
        turns = len(self._transcript_log)
        due = (not self._speaker_map and turns >= SPEAKER_RESOLVE_MIN_TURNS) \
            or (self._turns_since_resolve >= SPEAKER_RESOLVE_EVERY_TURNS)
        if due:
            self._track(self._resolve_speakers())

    async def _resolve_speakers(self) -> None:
        self._resolving = True
        self._turns_since_resolve = 0
        try:
            transcript = "\n".join(self._transcript_log[-SPEAKER_RESOLVE_MAX_LINES:])
            mapping = await self._resolve_speakers_fn(transcript, self.guests, self.conversation_type)
            if mapping:
                self._speaker_map.update(mapping)
                logger.info(f"[stream:{self.session_id}] speaker map: {self._speaker_map}")
        except Exception:
            logger.exception("Speaker resolution failed")
        finally:
            self._resolving = False

    # ---- speaker revisions (unit-testable) ----------------------------------
    async def handle_speaker_revision(self, revisions: list[dict]) -> None:
        """Apply an AssemblyAI online-reclustering revision.

        Each item is ``{"turn_order", "speaker_label"}``: the corrected label for a turn
        we saw earlier. We update the kept turn and rewrite the speaker of any already
        stored claim from that turn (in the DB and in the live UI).
        """
        for rev in revisions or []:
            turn_order = rev.get("turn_order")
            new_label = rev.get("speaker_label")
            if turn_order is None or new_label is None:
                continue
            if turn_order in self._turns:
                self._turns[turn_order]["speaker"] = new_label
            new_name = self._speaker_map.get(new_label, new_label)
            updated = []
            for pid, _old_label in self._turn_claims.get(turn_order, []):
                await self._rewrite_speaker(pid, new_name)
                updated.append((pid, new_label))  # keep base label current for next revision
            if turn_order in self._turn_claims:
                self._turn_claims[turn_order] = updated

    async def _rewrite_speaker(self, pid: int, name: str) -> None:
        """Update a stored claim's speaker in place and notify the UI."""
        try:
            row = await self.db.get_fact_check_by_id(pid)
            if row and row.get("sprecher") != name:
                row["sprecher"] = name
                await self.db.update_fact_check(pid, row)
                await self._emit({"type": "claim_speaker_update", "id": pid, "speaker": name})
        except Exception:
            logger.exception("Failed to rewrite speaker for claim %s", pid)

    # ---- windowing (unit-testable) ------------------------------------------
    async def handle_turn(
        self,
        transcript: str,
        end_of_turn: bool,
        speaker_label: str | None = None,
        turn_order: int | None = None,
    ) -> None:
        """Feed one turn event. Buffers finalized turns; flushes a full window."""
        text = (transcript or "").strip()
        if not text:
            return
        # Show the resolved name in the live UI once we know it; fall back to the label.
        display_speaker = self._speaker_map.get(speaker_label, speaker_label) if speaker_label else speaker_label
        # Live partial for the UI; only finalized turns enter the buffer.
        await self._emit({"type": "partial" if not end_of_turn else "turn", "text": text, "speaker": display_speaker})
        if not end_of_turn:
            return

        # A repeated final for a turn we already recorded is a re-emission, not a new turn:
        # update the kept text but don't double-count it into the window or the transcript.
        if turn_order is not None and turn_order in self._turns:
            self._turns[turn_order].update(speaker=speaker_label, text=text)
            for entry in self._buffer:
                if entry.get("turn_order") == turn_order:
                    entry["speaker"], entry["text"] = speaker_label, text
            return

        if turn_order is not None:
            self._turns[turn_order] = {"speaker": speaker_label, "text": text}
        line = f"{speaker_label}: {text}" if speaker_label else text
        self._buffer.append({"turn_order": turn_order, "speaker": speaker_label, "text": text})
        self._transcript_log.append(line)
        self._sentence_count += _count_sentences(text)
        self._turns_since_resolve += 1
        self._maybe_resolve_speakers()
        if self._sentence_count >= WINDOW_MIN_SENTENCES or len(self._buffer) >= WINDOW_MAX_TURNS:
            await self._flush_window()

    async def _flush_window(self) -> None:
        """Gate the current window and fast-check any check-worthy claims."""
        if not self._buffer:
            return
        entries = self._buffer
        window_text = "\n".join(
            (f"{e['speaker']}: {e['text']}" if e["speaker"] else e["text"]) for e in entries
        )
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
            source = getattr(claim, "source", None)  # original transcript sentence (JevGate)
            if not text:
                continue
            # Tie the claim back to the turn it came from, so a later speaker revision can
            # rewrite its speaker. Prefer the turn's own label over the gate's guessed name.
            turn_order, label = self._match_turn(source, entries)
            if label:
                name = label
            name = self._speaker_map.get(name, name)  # label -> real name, if resolved
            self._track(self._check_and_store(name, text, source, turn_order, label))

    def _match_turn(self, source: str | None, entries: list[dict]) -> tuple[int | None, str | None]:
        """Find the buffered turn a claim's source sentence came from.

        Returns ``(turn_order, speaker_label)`` for the matching turn, or ``(None, None)``
        when there is no source or no confident match (the caller then falls back to the
        gate's own name and simply won't track the claim for revisions).
        """
        if not source:
            return None, None
        needle = source.strip()
        if not needle:
            return None, None
        for e in entries:
            hay = e["text"] or ""
            if needle in hay or hay in needle:
                return e.get("turn_order"), e.get("speaker")
        return None, None

    async def _check_and_store(
        self,
        speaker: str,
        claim: str,
        source: str | None = None,
        turn_order: int | None = None,
        speaker_label: str | None = None,
    ) -> None:
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
        # Remember which turn produced this row so a SpeakerRevision can rewrite it.
        if turn_order is not None:
            self._turn_claims.setdefault(turn_order, []).append((pid, speaker_label))
        await self._emit({"type": "claim_processing", "id": pid, "speaker": speaker, "claim": claim, "source": source})

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
    def _max_speakers(self) -> int | None:
        """Cluster-count hint for diarization: env override, else guests + moderator."""
        if STREAM_MAX_SPEAKERS:
            try:
                return int(STREAM_MAX_SPEAKERS)
            except ValueError:
                logger.warning("Invalid STREAM_MAX_SPEAKERS=%r; ignoring", STREAM_MAX_SPEAKERS)
        return len(self.guests) + 1 if self.guests else None

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
                    getattr(event, "turn_order", None),
                ),
                loop,
            )

        def _on_speaker_revision(_client, event):
            revisions = [
                {"turn_order": getattr(r, "turn_order", None),
                 "speaker_label": getattr(r, "speaker_label", None)}
                for r in getattr(event, "revisions", []) or []
            ]
            asyncio.run_coroutine_threadsafe(self.handle_speaker_revision(revisions), loop)

        self._client.on(StreamingEvents.Turn, _on_turn)
        self._client.on(StreamingEvents.SpeakerRevision, _on_speaker_revision)

        params = StreamingParameters(
            sample_rate=STREAM_SAMPLE_RATE,
            encoding=Encoding.pcm_s16le,
            language_code="de",
            format_turns=True,
            speaker_labels=True,
            max_speakers=self._max_speakers(),
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
