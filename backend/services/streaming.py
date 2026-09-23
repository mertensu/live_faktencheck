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
from .speaker_track import SpeakerTrack
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

# Voiceprint speaker ID (docs/speaker-id-integration-plan.md §5.2, §8). Active only when a
# SpeakerIdentifier is injected (registry.get_speaker_identifier, SPEAKER_ID_ENABLED). A
# background classifier embeds the last WINDOW of audio every HOP into a speaker track;
# claims read the dominant speaker over their sentence's time span from that track.
SPEAKER_ID_WINDOW_MS = int(os.getenv("SPEAKER_ID_WINDOW_MS", "3000"))
SPEAKER_ID_HOP_MS = int(os.getenv("SPEAKER_ID_HOP_MS", "1000"))
SPEAKER_ID_BUFFER_MS = int(os.getenv("SPEAKER_ID_BUFFER_MS", "15000"))  # PCM ring buffer
# Energy gate: windows quieter than this RMS (float PCM in [-1, 1]) are recorded as None
# without an embedding — min_seconds only checks length, applause/room noise passes it.
SPEAKER_ID_MIN_RMS = float(os.getenv("SPEAKER_ID_MIN_RMS", "0.01"))
# Share of a span's overlap weight a name needs to count as its dominant speaker.
SPEAKER_ID_MAJORITY = float(os.getenv("SPEAKER_ID_MAJORITY", "0.6"))
# Every overlapping window below this cosine → a clearly foreign voice (§6.9).
SPEAKER_ID_UNKNOWN_THRESHOLD = float(os.getenv("SPEAKER_ID_UNKNOWN_THRESHOLD", "0.35"))


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
        speaker_identifier=None,
        speakers: list[str] | None = None,
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
        # optional SpeakerIdentifier (voiceprints); None = speaker ID off, labels only
        self.speaker_identifier = speaker_identifier
        self.speakers = speakers or []  # guest names without roles (voiceprint file stems)

        # Current window: finalized turns as {"turn_order", "speaker" (label), "text",
        # "words"} — words are [{"text", "start", "end"}] (ms from stream start).
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
        # Claims stored while their label was not yet resolved to a name (resolution needs
        # ~a minute of transcript; claims flow sooner). Keyed by the bare label so the
        # background resolution can rewrite them once it learns the name.
        self._label_claims: dict[str, list[int]] = {}  # label -> [fact_check_id]

        # Voiceprint speaker ID: a bounded ring buffer of the PCM16 actually sent to
        # AssemblyAI, and a sample counter on the same clock as its word timestamps.
        self._pcm = bytearray()
        self._samples = 0
        self._spk_track = SpeakerTrack(
            majority=SPEAKER_ID_MAJORITY, unknown_threshold=SPEAKER_ID_UNKNOWN_THRESHOLD
        )
        self._track_updated = asyncio.Event()  # set (and replaced) after each classifier step
        self._classifying = False
        self._classifier_task: asyncio.Task | None = None

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
                await self._apply_map_to_pending(mapping)
        except Exception:
            logger.exception("Speaker resolution failed")
        finally:
            self._resolving = False

    async def _apply_map_to_pending(self, mapping: dict) -> None:
        """Back-fill names onto claims that were stored under a now-resolved bare label.

        Resolution lands after the first claims are already checked and displayed, so
        those show a label (``B``) until this rewrites them to the real name — in the DB
        and, via ``claim_speaker_update``, in the live UI.
        """
        for label, name in mapping.items():
            for pid in self._label_claims.pop(label, []):
                await self._rewrite_speaker(pid, name)

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
        words: list[dict] | None = None,
    ) -> None:
        """Feed one turn event. Buffers finalized turns; flushes a full window.

        ``words`` are the turn's ASR words with timestamps (``{"text", "start", "end"}``,
        ms from stream start); they map a claim's sentence to a time span (speaker ID).
        """
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
            # Words go along with the text, or the span mapping would align new text
            # against stale words.
            self._turns[turn_order].update(speaker=speaker_label, text=text, words=words or [])
            for entry in self._buffer:
                if entry.get("turn_order") == turn_order:
                    entry["speaker"], entry["text"], entry["words"] = speaker_label, text, words or []
            return

        if turn_order is not None:
            self._turns[turn_order] = {"speaker": speaker_label, "text": text, "words": words or []}
        line = f"{speaker_label}: {text}" if speaker_label else text
        self._buffer.append({"turn_order": turn_order, "speaker": speaker_label, "text": text,
                             "words": words or []})
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
        # Stored under a bare label the resolver hasn't named yet? Track it so the
        # background resolution can rewrite it to the real name once it lands.
        if speaker_label and self._speaker_map.get(speaker_label) is None:
            self._label_claims.setdefault(speaker_label, []).append(pid)
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

    # ---- voiceprint speaker track (background classifier) --------------------
    def _ms(self, samples: int) -> int:
        return samples * 1000 // STREAM_SAMPLE_RATE

    def _buffer_pcm(self, audio: bytes) -> None:
        """Append sent audio to the ring buffer and advance the stream clock."""
        self._pcm += audio
        self._samples += len(audio) // 2
        max_bytes = SPEAKER_ID_BUFFER_MS * STREAM_SAMPLE_RATE // 1000 * 2
        if len(self._pcm) > max_bytes:
            del self._pcm[: len(self._pcm) - max_bytes]

    def _classify_tick(self) -> bool:
        """Start one classifier step on the newest window; returns False if skipped.

        Skip, don't queue: while the previous step still runs, this tick is dropped — the
        next window overlaps it anyway. Also skipped until a full window is buffered and
        when no new audio arrived since the last step.
        """
        if self.speaker_identifier is None or self._classifying:
            return False
        win = SPEAKER_ID_WINDOW_MS * STREAM_SAMPLE_RATE // 1000
        if len(self._pcm) // 2 < win or self._ms(self._samples) <= self._spk_track.covered_ms:
            return False
        self._classifying = True
        self._track(self._classify_step(bytes(self._pcm[-win * 2:]), self._samples - win, self._samples))
        return True

    def _classify_window(self, pcm_bytes: bytes) -> tuple[str | None, float | None]:
        """Energy gate + embedding for one window (runs in a worker thread)."""
        import numpy as np
        from backend.services.speaker_id import pcm16_to_float32

        pcm = pcm16_to_float32(pcm_bytes)
        if float(np.sqrt(np.mean(pcm * pcm))) < SPEAKER_ID_MIN_RMS:
            return None, None
        return self.speaker_identifier.identify(pcm, STREAM_SAMPLE_RATE)

    async def _classify_step(self, pcm_bytes: bytes, start_sample: int, end_sample: int) -> None:
        try:
            # Off the event loop: tens of ms of CPU would stall audio forwarding and WS events.
            name, score = await asyncio.to_thread(self._classify_window, pcm_bytes)
            self._spk_track.add(self._ms(start_sample), self._ms(end_sample), name, score)
            updated, self._track_updated = self._track_updated, asyncio.Event()
            updated.set()
        except Exception:
            logger.exception("Speaker classification step failed")
        finally:
            self._classifying = False

    async def _classifier_loop(self) -> None:
        while True:
            await asyncio.sleep(SPEAKER_ID_HOP_MS / 1000)
            self._classify_tick()

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
                    [{"text": w.text, "start": w.start, "end": w.end}
                     for w in getattr(event, "words", None) or []],
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
        if self.speaker_identifier is not None:
            self._classifier_task = asyncio.create_task(self._classifier_loop())

    async def feed(self, audio: bytes) -> None:
        if self._client is not None:
            await self._client.stream(audio)
            # Alignment invariant: only audio actually sent to AssemblyAI advances the
            # sample clock, so track time == word-timestamp time.
            if self.speaker_identifier is not None:
                self._buffer_pcm(audio)

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
            # Classify the tail and drain claim checks while the classifier still runs, so
            # claims waiting for track coverage get it; then stop it and drain its last step.
            self._classify_tick()
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)
            if self._classifier_task is not None:
                self._classifier_task.cancel()
                self._classifier_task = None
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)
        logger.info(f"[stream:{self.session_id}] session stopped")
