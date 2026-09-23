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

import logfire

from backend.lang import UNKNOWN_SPEAKER
from backend.utils import build_fact_check_dict
from .speaker_track import SpeakerTrack, sentence_span
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
# How long a claim waits for the track to cover its sentence before it is checked with the
# fallback speaker (and rewritten later when coverage lands).
SPEAKER_ID_WAIT_MS = int(os.getenv("SPEAKER_ID_WAIT_MS", "1000"))
# Voiceprint label naming (replaces the LLM resolver): a diarization label is named once
# this many of its turns were confidently identified, with this share agreeing.
SPEAKER_ID_LABEL_MIN_VOTES = int(os.getenv("SPEAKER_ID_LABEL_MIN_VOTES", "3"))
SPEAKER_ID_LABEL_MAJORITY = float(os.getenv("SPEAKER_ID_LABEL_MAJORITY", "0.8"))


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
        # Claims checked before the track covered their span: (pid, span, t0, label),
        # resolved after each classifier step via _apply_voiceprint.
        self._pending_spk: list[tuple[int, tuple[int, int], float, str | None]] = []
        # Claims named (or marked unknown) by voiceprint. They are never registered on the
        # label paths, and both label rewrites skip them — the voiceprint name wins.
        self._voiceprint_pids: set[int] = set()
        self._claim_speakers: dict[int, str] = {}  # pid -> current speaker (survives the check)
        self._map_source: dict[str, str] = {}  # label -> "label_vote" | "llm"
        # Label naming: finalized turns awaiting track coverage, and each turn's voiceprint
        # name. Votes are keyed by turn, so a reclustered turn moves its vote to the new label.
        self._pending_votes: list[tuple[int, tuple[int, int]]] = []
        self._turn_votes: dict[int, str] = {}
        # Episode speakers without a voiceprint. Only they need the LLM resolver.
        self._missing: list[str] = []
        if speaker_identifier is not None:
            enrolled = {n.casefold() for n in speaker_identifier.voiceprints}
            self._missing = [n for n in self.speakers if n.casefold() not in enrolled]

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
        # Every speaker enrolled → voiceprints name the labels; no LLM call at all.
        if self.speaker_identifier is not None and not self._missing:
            return
        turns = len(self._transcript_log)
        # First pass keys on "no LLM mapping yet": voiceprint-named labels must not
        # suppress it while unenrolled speakers still need a name.
        llm_mapped = any(self._map_source.get(k) == "llm" for k in self._speaker_map)
        due = (not llm_mapped and turns >= SPEAKER_RESOLVE_MIN_TURNS) \
            or (self._turns_since_resolve >= SPEAKER_RESOLVE_EVERY_TURNS)
        if due:
            self._track(self._resolve_speakers())

    async def _resolve_speakers(self) -> None:
        self._resolving = True
        self._turns_since_resolve = 0
        try:
            transcript = "\n".join(self._transcript_log[-SPEAKER_RESOLVE_MAX_LINES:])
            mapping = await self._resolve_speakers_fn(transcript, self.guests, self.conversation_type)
            # Voiceprint-named labels are authoritative; the LLM only fills the rest.
            mapping = {k: v for k, v in (mapping or {}).items()
                       if self._map_source.get(k) != "label_vote"}
            if mapping:
                self._speaker_map.update(mapping)
                self._map_source.update({label: "llm" for label in mapping})
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
                if pid not in self._voiceprint_pids:
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
                if pid in self._voiceprint_pids:
                    continue
                await self._rewrite_speaker(pid, new_name)
                updated.append((pid, new_label))  # keep base label current for next revision
            if turn_order in self._turn_claims:
                self._turn_claims[turn_order] = updated
        await self._update_label_map()  # the moved votes may change a label's name

    async def _rewrite_speaker(self, pid: int, name: str) -> None:
        """Update a stored claim's speaker in place and notify the UI."""
        self._claim_speakers[pid] = name
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
        if self.speaker_identifier is not None and turn_order is not None and words:
            self._pending_votes.append((turn_order, (words[0]["start"], words[-1]["end"])))
            await self._resolve_pending_votes()
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
            span = self._claim_span(source, entries) if self.speaker_identifier is not None else None
            self._track(self._check_and_store(name, text, source, turn_order, label, span))

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

    def _claim_span(self, source: str | None, entries: list[dict]) -> tuple[int, int] | None:
        """Time span of a claim's source sentence: its own turn first, else the window."""
        if not source or not source.strip():
            return None
        needle = source.strip()
        for e in entries:
            hay = e["text"] or ""
            if needle in hay or hay in needle:
                span = sentence_span(needle, e.get("words"), hay)
                if span:
                    return span
        words = [w for e in entries for w in e.get("words") or []]
        return sentence_span(needle, words, " ".join(e["text"] for e in entries))

    async def _await_coverage(self, end_ms: int) -> None:
        """Wait (bounded by SPEAKER_ID_WAIT_MS) until the track covers ``end_ms``."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SPEAKER_ID_WAIT_MS / 1000
        while not self._spk_track.covers(end_ms):
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(self._track_updated.wait(), remaining)
            except TimeoutError:
                return

    def _fallback_source(self, speaker_label: str | None) -> str:
        if speaker_label and speaker_label in self._speaker_map:
            return self._map_source.get(speaker_label, "llm")
        return "label"

    def _log_speaker(self, pid, speaker, source, verdict, span, t0) -> None:
        """One Logfire record per claim — calibration data for thresholds and wait (§11)."""
        waited_ms = int((asyncio.get_running_loop().time() - t0) * 1000)
        fields = dict(
            session_id=self.session_id, claim_id=pid, speaker=speaker, source=source,
            voiceprint_name=verdict.name if verdict else None,
            score=round(verdict.score, 3) if verdict and verdict.score is not None else None,
            span=list(span) if span else None, waited_ms=waited_ms,
        )
        logger.info("[stream:%s] speaker_id %s", self.session_id, fields)
        logfire.info("speaker_id claim {speaker} via {source}", **fields)

    async def _apply_voiceprint(self, pid: int, verdict) -> str | None:
        """Late voiceprint result: rewrite the claim's speaker and lock it against labels.

        Returns the applied speaker, or None when the verdict has no name (the claim stays
        on the label paths).
        """
        name = verdict.name or (UNKNOWN_SPEAKER if verdict.unknown else None)
        if name is None:
            return None
        self._voiceprint_pids.add(pid)
        for turn_order, items in self._turn_claims.items():
            self._turn_claims[turn_order] = [it for it in items if it[0] != pid]
        for label, pids in self._label_claims.items():
            self._label_claims[label] = [p for p in pids if p != pid]
        await self._rewrite_speaker(pid, name)
        return name

    async def _resolve_pending_spk(self) -> None:
        """Resolve claims whose span the track now covers (after each classifier step)."""
        due = [p for p in self._pending_spk if self._spk_track.covers(p[1][1])]
        if not due:
            return
        self._pending_spk = [p for p in self._pending_spk if not self._spk_track.covers(p[1][1])]
        for pid, span, t0, label in due:
            verdict = self._spk_track.dominant(*span)
            applied = await self._apply_voiceprint(pid, verdict)
            if applied:
                self._log_speaker(pid, applied, "unknown" if verdict.unknown else "span", verdict, span, t0)
            else:
                self._log_speaker(pid, self._claim_speakers.get(pid), self._fallback_source(label),
                                  verdict, span, t0)

    async def _resolve_pending_votes(self) -> None:
        """Record a voiceprint vote for each finalized turn the track now covers."""
        due = [v for v in self._pending_votes if self._spk_track.covers(v[1][1])]
        if not due:
            return
        self._pending_votes = [v for v in self._pending_votes if not self._spk_track.covers(v[1][1])]
        for turn_order, span in due:
            name = self._spk_track.dominant(*span).name
            if name:
                self._turn_votes[turn_order] = name
        await self._update_label_map()

    async def _update_label_map(self) -> None:
        """Name each label by its turns' voiceprint votes (§6.8); follows reclustering."""
        votes: dict[str, dict[str, int]] = {}
        for turn_order, name in self._turn_votes.items():
            label = self._turns.get(turn_order, {}).get("speaker")
            if label:
                counts = votes.setdefault(label, {})
                counts[name] = counts.get(name, 0) + 1
        for label, counts in votes.items():
            total = sum(counts.values())
            best = max(counts, key=counts.get)
            if total < SPEAKER_ID_LABEL_MIN_VOTES or counts[best] / total < SPEAKER_ID_LABEL_MAJORITY:
                continue
            if self._speaker_map.get(label) == best and self._map_source.get(label) == "label_vote":
                continue
            self._speaker_map[label] = best
            self._map_source[label] = "label_vote"
            logger.info(f"[stream:{self.session_id}] voiceprint label naming: {label} -> {best} {counts}")
            await self._apply_map_to_pending({label: best})

    def _give_up_pending_spk(self) -> None:
        """At stop: claims the track never covered keep their fallback speaker."""
        for pid, span, t0, label in self._pending_spk:
            self._log_speaker(pid, self._claim_speakers.get(pid), self._fallback_source(label),
                              None, span, t0)
        self._pending_spk = []

    async def _check_and_store(
        self,
        speaker: str,
        claim: str,
        source: str | None = None,
        turn_order: int | None = None,
        speaker_label: str | None = None,
        span: tuple[int, int] | None = None,
    ) -> None:
        """Insert a spinner placeholder, run the fast check, update in place.

        With voiceprint speaker ID and a known sentence span, the speaker is resolved
        *before* the check (the name feeds into the reasoning): read the track now, or wait
        briefly for it to cover the span; on timeout check with the fallback speaker and
        rewrite it once the track catches up.
        """
        now = datetime.now().isoformat()
        t0 = asyncio.get_running_loop().time()
        verdict = None
        if span is not None:
            await self._await_coverage(span[1])
            if self._spk_track.covers(span[1]):
                verdict = self._spk_track.dominant(*span)
        vp_name = None
        if verdict is not None:
            vp_name = verdict.name or (UNKNOWN_SPEAKER if verdict.unknown else None)
        if vp_name:
            speaker = vp_name
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
        self._claim_speakers[pid] = speaker
        if vp_name:
            # Voiceprint name wins: not registered on the label paths at all.
            self._voiceprint_pids.add(pid)
        else:
            # Remember which turn produced this row so a SpeakerRevision can rewrite it.
            if turn_order is not None:
                self._turn_claims.setdefault(turn_order, []).append((pid, speaker_label))
            # Stored under a bare label the resolver hasn't named yet? Track it so the
            # background resolution can rewrite it to the real name once it lands.
            if speaker_label and self._speaker_map.get(speaker_label) is None:
                self._label_claims.setdefault(speaker_label, []).append(pid)
        if span is not None and verdict is None:
            self._pending_spk.append((pid, span, t0, speaker_label))
            await self._resolve_pending_spk()  # coverage may have landed during the insert
        elif self.speaker_identifier is not None:
            src = ("unknown" if verdict.unknown else "span") if vp_name else self._fallback_source(speaker_label)
            self._log_speaker(pid, speaker, src, verdict, span, t0)
        event = {"type": "claim_processing", "id": pid, "speaker": speaker, "claim": claim, "source": source}
        if verdict is not None and verdict.unknown:
            event["unknown_voice"] = True
        await self._emit(event)

        try:
            result = await self.fast_checker.check_claim_async(
                speaker=speaker, claim=claim, context=self.context, episode_date=self.episode_date
            )
            fc = build_fact_check_dict(result, self.session_id, speaker_fallback=speaker, claim_fallback=claim)
            # A rewrite (revision, label naming, late voiceprint) may have landed during
            # the check; don't let the checker's echo of the old speaker clobber it.
            fc["sprecher"] = self._claim_speakers.get(pid, fc["sprecher"])
            fc["check_depth"] = "fast"
            await self.db.update_fact_check(pid, fc)
            await self._emit({"type": "claim_result", "id": pid, "consistency": fc["consistency"]})
        except Exception:
            logger.exception("Fast check failed for streamed claim")
            await self.db.update_fact_check(pid, {
                "sprecher": self._claim_speakers.get(pid, speaker), "behauptung": claim, "consistency": "",
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
            await self._resolve_pending_spk()
            await self._resolve_pending_votes()
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
            await self._announce_speaker_id()

    async def _announce_speaker_id(self) -> None:
        """Enrollment check (§5.3): tell the admin UI which speakers lack a voiceprint."""
        enrolled = [n for n in self.speakers if n not in self._missing]
        logger.info(f"[stream:{self.session_id}] speaker ID: enrolled={enrolled} missing={self._missing}")
        logfire.info("speaker_id status", session_id=self.session_id,
                     enrolled=enrolled, missing=self._missing)
        await self._emit({"type": "speaker_id_status", "enrolled": enrolled, "missing": self._missing})

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
            self._give_up_pending_spk()
        logger.info(f"[stream:{self.session_id}] session stopped")
