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
import re
import asyncio
import logging
from datetime import datetime
from difflib import SequenceMatcher

from backend.lang import UNCLEAR_SPEAKER
from backend.utils import build_fact_check_dict
from .gate import split_sentences
from .transcription import keyterms_from_guests

logger = logging.getLogger(__name__)

# A window flushes once it holds at least this many sentence-ending marks, or this
# many finalized turns, whichever comes first. Small = low latency, closer to live.
WINDOW_MIN_SENTENCES = int(os.getenv("STREAM_WINDOW_MIN_SENTENCES", "2"))
WINDOW_MAX_TURNS = int(os.getenv("STREAM_WINDOW_MAX_TURNS", "3"))
# Sample rate the browser must send (PCM16 mono). 16 kHz is AssemblyAI's expected rate.
STREAM_SAMPLE_RATE = int(os.getenv("STREAM_SAMPLE_RATE", "16000"))

# Early sentences: AssemblyAI punctuates in-progress (partial) turns, and only a partial's
# last sentence is still being revised. So a sentence enters the window as soon as the next
# one has started, instead of waiting for the end of the turn — on monologues that is
# several seconds sooner. The finalized turn then only contributes what wasn't taken yet.
STREAM_EARLY_SENTENCES = os.getenv("STREAM_EARLY_SENTENCES", "true").lower() in ("1", "true", "yes")
# Two renderings of a sentence (partial vs. final, or a repeated source) count as the same
# above this similarity of their normalized text.
SAME_SENTENCE_RATIO = 0.85
# How many recently checked source sentences to remember for duplicate suppression.
CHECKED_SOURCES_MEMORY = 50


def _norm(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").casefold()))


def _same_sentence(a: str, b: str) -> bool:
    """Compare two already-normalized sentences."""
    return a == b or SequenceMatcher(None, a, b).ratio() >= SAME_SENTENCE_RATIO


def _in_passage(source: str, passage: str) -> bool:
    """True if a claim's source sentence lies in a marked passage (both normalized).

    Also when the operator marked most of the sentence but not all of it: at least half
    of it, and a part of that sentence only.
    """
    if not source or not passage:
        return False
    if f" {source} " in f" {passage} ":
        return True
    return f" {passage} " in f" {source} " and len(passage) * 2 >= len(source)


# Optional hard cap on how many distinct speakers AssemblyAI's online diarization may
# cluster into. Left unset it is derived from the guest list (+1 for the moderator), which
# gives the reclusterer a hint on hard single-mic TV audio. Env overrides the derivation.
STREAM_MAX_SPEAKERS = os.getenv("STREAM_MAX_SPEAKERS")
# AssemblyAI re-clusters speakers and sends SpeakerRevision corrections — by default only
# once, at the end of the session. Live we want them during the show; the API's minimum
# interval is 2 minutes (0 = end of session only).
# Named explicitly: left out, the server picked universal-3-5-pro (seen in the Begin event),
# not the 3.6 the docs call the default.
STREAM_SPEECH_MODEL = os.getenv("STREAM_SPEECH_MODEL", "universal-3-6-pro")
STREAM_SPEAKER_REVISION_MS = int(os.getenv("STREAM_SPEAKER_REVISION_MS", "120000"))


def speaker_runs(words) -> list[tuple[str | None, str]]:
    """Group a turn's words into consecutive runs of the same per-word speaker.

    AssemblyAI labels every final word, not only the turn. More than one run means the
    turn mixes speakers (a turn ends at a pause, not at a change of speaker). A word
    without a speaker, or ``PENDING`` (not attributable), joins the run it falls in.
    """
    runs: list[tuple[str | None, list[str]]] = []
    for w in words or []:
        spk = getattr(w, "speaker", None)
        if spk in (None, "PENDING"):
            spk = runs[-1][0] if runs else None
        if runs and runs[-1][0] in (spk, None):
            if runs[-1][0] is None:
                runs[-1] = (spk, runs[-1][1])
            runs[-1][1].append(w.text)
        else:
            runs.append((spk, [w.text]))
    return [(spk, " ".join(ws)) for spk, ws in runs]


def _log_mixed_speakers(session_id: str, kind: str, turn_order, label, words) -> None:
    """Log a turn whose words carry more than one speaker (diagnostic for word-level splits)."""
    runs = speaker_runs(words)
    if len(runs) > 1:
        detail = " | ".join(f"{spk or '?'}: {text[:60]}" for spk, text in runs)
        logger.info(f"[stream:{session_id}] mixed-speaker {kind} #{turn_order} label={label}: {detail}")


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
        self.speakers = speakers or []  # guest names without roles: what a label may be assigned to

        # Current window: finalized turns as {"turn_order", "speaker" (label), "text"}.
        self._buffer: list[dict] = []
        self._sentence_count = 0
        self._previous_context: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self._client = None                   # AssemblyAI AsyncStreamingClient (set in start)

        # Speakers: AssemblyAI's diarization labels (A/B/…) are the only automatic signal.
        # Names come from the operator, who assigns a label to a guest in the live UI
        # (assign_speaker); an unassigned label stays bare. Online reclustering may move a
        # turn to another label later (SpeakerRevisionEvent, matched by turn_order), so we
        # keep every finalized turn and the claims it produced.
        self._speaker_map: dict[str, str] = {}         # label -> name, set by the operator
        self._turns: dict[int, dict] = {}              # turn_order -> {"speaker", "text"}
        self._turn_claims: dict[int, list[int]] = {}   # turn_order -> [fact_check_id]
        self._claim_labels: dict[int, str] = {}        # fact_check_id -> current label
        self._claim_speakers: dict[int, str] = {}      # fact_check_id -> current speaker
        # Passages the operator marked and gave to a guest, overriding their label (the
        # diarization folded one speaker's words into another's turn): [(normalized, name)].
        self._passages: list[tuple[str, str]] = []
        self._claim_sources: dict[int, str] = {}       # fact_check_id -> normalized source

        # Early sentences: per turn, the normalized sentences already taken from partials.
        self._early: dict[int, list[str]] = {}
        # Normalized source sentences of recent claims — the same sentence is checked once.
        self._checked_sources: list[str] = []
        # Early claims' source sentences per turn, re-sent in their final wording once the
        # turn is finalized (the UI marks claims by exact text; the final may be re-formatted).
        self._early_sources: dict[int, list[str]] = {}

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

    # ---- speakers: operator assignment + reclustering (unit-testable) --------
    def _display(self, label: str | None) -> str | None:
        """A label's assigned name, else the bare label."""
        return self._speaker_map.get(label, label) if label else label

    async def assign_speaker(self, label: str, name: str | None) -> None:
        """The operator assigns a diarization label to a guest, or clears it (``None``).

        Rewrites every stored claim currently under that label (DB + ``claim_speaker_update``)
        and announces the mapping, so the UI renames the label's transcript lines. A name
        outside the episode's speakers is ignored.
        """
        if not label:
            return
        if name is not None and name not in self.speakers:
            logger.warning(f"[stream:{self.session_id}] assign {label!r} -> unknown speaker {name!r}; ignored")
            return
        if name:
            self._speaker_map[label] = name
        else:
            self._speaker_map.pop(label, None)
        logger.info(f"[stream:{self.session_id}] speaker map: {self._speaker_map}")
        await self._emit({"type": "speaker_map_update", "label": label, "speaker": name})
        for pid, claim_label in list(self._claim_labels.items()):
            if claim_label == label:
                await self._rewrite_speaker(pid, self._display(label))

    async def assign_passage(self, text: str, name: str) -> None:
        """The operator marks a passage of the transcript and gives it to a guest.

        Every claim whose source sentence lies in it takes that name for good: it leaves its
        label, so later assignments and reclustering no longer touch it. The passage is
        kept, so a claim from it that is still in the gate gets the name as well.
        """
        key = _norm(text)
        if not key or name not in self.speakers:
            logger.warning(f"[stream:{self.session_id}] assign passage -> {name!r}; ignored")
            return
        self._passages.append((key, name))
        logger.info(f"[stream:{self.session_id}] passage -> {name}: {text[:80]!r}")
        for pid, source in list(self._claim_sources.items()):
            if _in_passage(source, key):
                self._detach_label(pid)
                await self._rewrite_speaker(pid, name)

    def _passage_speaker(self, source: str | None) -> str | None:
        """The name of the latest marked passage this source sentence lies in."""
        key = _norm(source or "")
        for passage, name in reversed(self._passages):
            if _in_passage(key, passage):
                return name
        return None

    def _detach_label(self, pid: int) -> None:
        self._claim_labels.pop(pid, None)
        for pids in self._turn_claims.values():
            if pid in pids:
                pids.remove(pid)

    async def handle_speaker_revision(self, revisions: list[dict]) -> None:
        """Apply an AssemblyAI online-reclustering revision.

        Each item is ``{"turn_order", "speaker_label"}``: the corrected label for a turn
        we saw earlier. We update the kept turn (and its transcript line in the UI) and
        move any claim from that turn to the new label.
        """
        for rev in revisions or []:
            turn_order = rev.get("turn_order")
            new_label = rev.get("speaker_label")
            if turn_order is None or new_label is None:
                continue
            if turn_order in self._turns:
                self._turns[turn_order]["speaker"] = new_label
                await self._emit({"type": "turn_speaker_update", "turn_order": turn_order, "label": new_label})
            for pid in self._turn_claims.get(turn_order, []):
                self._claim_labels[pid] = new_label
                await self._rewrite_speaker(pid, self._display(new_label))

    async def _rewrite_speaker(self, pid: int, name: str) -> None:
        """Update a stored claim's speaker in place and notify the UI."""
        self._claim_speakers[pid] = name
        try:
            row = await self.db.get_fact_check_by_id(pid)
            if row and row.get("sprecher") != name:
                row["sprecher"] = name
                await self.db.update_fact_check(pid, row)
                await self._emit({"type": "claim_speaker_update", "id": pid, "speaker": name,
                                  "label": self._claim_labels.get(pid)})
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
        display_speaker = self._display(speaker_label)
        # Live partial for the UI; its settled sentences may enter the window early.
        if not end_of_turn:
            await self._emit({"type": "partial", "text": text, "speaker": display_speaker})
            if STREAM_EARLY_SENTENCES and turn_order is not None and turn_order not in self._turns:
                await self._take_early_sentences(text, speaker_label, turn_order)
            return
        # turn_order + label let the UI follow a later reclustering (turn_speaker_update)
        # and the operator's assignment (speaker_map_update).
        await self._emit({"type": "turn", "text": text, "speaker": display_speaker,
                          "turn_order": turn_order, "label": speaker_label})

        # A repeated final for a turn we already recorded is a re-emission, not a new turn:
        # update the kept text but don't double-count it into the window.
        if turn_order is not None and turn_order in self._turns:
            self._turns[turn_order].update(speaker=speaker_label, text=text)
            rest = self._untaken(turn_order, text)
            for entry in self._buffer:
                if entry.get("turn_order") == turn_order and not entry.get("early"):
                    entry["speaker"], entry["text"] = speaker_label, rest
            return

        if turn_order is not None:
            self._turns[turn_order] = {"speaker": speaker_label, "text": text}
        for old in self._early_sources.pop(turn_order, []):
            await self._resend_source(old, self._final_source(turn_order, old))
        # Sentences already taken early from partials are not gated a second time.
        rest = self._untaken(turn_order, text)
        if rest:
            self._buffer.append({"turn_order": turn_order, "speaker": speaker_label, "text": rest})
            self._sentence_count += _count_sentences(rest)
        if self._sentence_count >= WINDOW_MIN_SENTENCES or len(self._buffer) >= WINDOW_MAX_TURNS:
            await self._flush_window()

    async def _take_early_sentences(self, text, speaker_label, turn_order) -> None:
        """Buffer a partial's settled sentences (all but its last) not taken yet."""
        taken = self._early.setdefault(turn_order, [])
        added = False
        for sentence in split_sentences(text)[:-1]:
            key = _norm(sentence)
            if not key or any(_same_sentence(key, t) for t in taken):
                continue
            taken.append(key)
            self._buffer.append({"turn_order": turn_order, "speaker": speaker_label, "text": sentence,
                                 "early": True})
            self._sentence_count += 1
            added = True
        if added and (self._sentence_count >= WINDOW_MIN_SENTENCES or len(self._buffer) >= WINDOW_MAX_TURNS):
            await self._flush_window()

    def _untaken(self, turn_order: int | None, text: str) -> str:
        """The part of a finalized turn not already taken early from its partials."""
        taken = self._early.get(turn_order) if turn_order is not None else None
        if not taken:
            return text
        return " ".join(s for s in split_sentences(text)
                        if not any(_same_sentence(_norm(s), t) for t in taken))

    def _final_source(self, turn_order: int | None, source: str) -> str | None:
        """The finalized turn's sentence matching an early ``source``, if its wording changed."""
        turn = self._turns.get(turn_order) if turn_order is not None else None
        if not turn or source in turn["text"]:
            return None
        key = _norm(source)
        best, ratio = None, 0.0
        for sentence in split_sentences(turn["text"]):
            r = SequenceMatcher(None, key, _norm(sentence)).ratio()
            if r > ratio:
                best, ratio = sentence, r
        return best if ratio >= 0.6 else None

    async def _resend_source(self, old: str, new: str | None) -> None:
        if new:
            await self._emit({"type": "claim_source_update", "old": old, "source": new})

    def _already_checked(self, source: str | None) -> bool:
        """True if this source sentence was checked recently; records it otherwise."""
        key = _norm(source or "")
        if not key:
            return False
        if any(_same_sentence(key, c) for c in self._checked_sources):
            return True
        self._checked_sources = (self._checked_sources + [key])[-CHECKED_SOURCES_MEMORY:]
        return False

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
            queries = getattr(claim, "search_queries", None) or None  # JevGate only
            if not text:
                continue
            # Safety net for early sentences: a sentence taken from a partial and again,
            # slightly re-rendered, from the final turn must not be checked twice.
            if self._already_checked(source):
                logger.info(f"[stream:{self.session_id}] skip duplicate claim source: {source!r}")
                continue
            # Tie the claim to the turn and label it came from. The speaker is that label
            # (or the operator's name for it) — never a name the gate guessed from the text.
            match = self._match_turn(source, entries)
            turn_order, label = match if match else self._label_from_window(name, entries)
            # A claim from an early sentence: its turn may be re-formatted when finalized.
            # Already final → show the final wording now; else re-send it on finalization.
            if source and turn_order is not None and any(
                    e.get("early") and e["turn_order"] == turn_order and source.strip() in e["text"]
                    for e in entries):
                if turn_order in self._turns:
                    source = self._final_source(turn_order, source) or source
                else:
                    self._early_sources.setdefault(turn_order, []).append(source)
            self._track(self._check_and_store(text, source, turn_order, label, queries))

    def _match_turn(self, source: str | None, entries: list[dict]) -> tuple[int | None, str | None] | None:
        """Find the buffered turn a claim's source sentence came from.

        Returns ``(turn_order, speaker_label)`` for the matching turn, or ``None`` when
        there is no source or no confident match.
        """
        if not source:
            return None
        needle = source.strip()
        if not needle:
            return None
        for e in entries:
            hay = e["text"] or ""
            if needle in hay or hay in needle:
                return e.get("turn_order"), e.get("speaker")
        return None

    @staticmethod
    def _label_from_window(name: str, entries: list[dict]) -> tuple[int | None, str | None]:
        """Label for a claim without a matching source (the extractor gate has none).

        The gate sees the window as ``"label: text"`` lines, so its name is usually one of
        them; a window with a single label is unambiguous either way. Anything else gets no
        label, and the claim is stored as ``Unklar``.
        """
        labeled = [e for e in entries if e.get("speaker")]
        hits = [e for e in labeled if e["speaker"] == name]
        if not hits and len({e["speaker"] for e in labeled}) == 1:
            hits = labeled
        if not hits:
            return None, None
        orders = {e.get("turn_order") for e in hits}
        return (orders.pop() if len(orders) == 1 else None), hits[0]["speaker"]

    async def _check_and_store(
        self,
        claim: str,
        source: str | None = None,
        turn_order: int | None = None,
        speaker_label: str | None = None,
        queries: list[str] | None = None,
    ) -> None:
        """Insert a spinner placeholder, run the fast check, update in place."""
        now = datetime.now().isoformat()
        # A passage the operator gave to a guest outranks the label.
        passage_speaker = self._passage_speaker(source)
        if passage_speaker:
            speaker_label = None
        speaker = passage_speaker or self._display(speaker_label) or UNCLEAR_SPEAKER
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
        if source:
            self._claim_sources[pid] = _norm(source)
        if speaker_label:
            # Tracked so an assignment or a revision can rewrite this row later.
            self._claim_labels[pid] = speaker_label
            if turn_order is not None:
                self._turn_claims.setdefault(turn_order, []).append(pid)
        await self._emit({"type": "claim_processing", "id": pid, "speaker": speaker,
                          "label": speaker_label, "claim": claim, "source": source})
        # An assignment may have landed while the placeholder was being inserted.
        late_passage = self._passage_speaker(source)
        if late_passage and late_passage != speaker:
            self._detach_label(pid)
            await self._rewrite_speaker(pid, late_passage)
            speaker = late_passage
        elif speaker_label and self._display(speaker_label) != speaker:
            await self._rewrite_speaker(pid, self._display(speaker_label))
            speaker = self._claim_speakers[pid]

        try:
            result = await self.fast_checker.check_claim_async(
                speaker=speaker, claim=claim, context=self.context, episode_date=self.episode_date,
                queries=queries,
            )
            fc = build_fact_check_dict(result, self.session_id, speaker_fallback=speaker, claim_fallback=claim)
            # A rewrite (assignment, revision) may have landed during the check; don't let
            # the checker's echo of the old speaker clobber it.
            fc["sprecher"] = self._claim_speakers.get(pid, fc["sprecher"])
            fc["check_depth"] = "fast"
            await self.db.update_fact_check(pid, fc)
            await self._emit({
                "type": "claim_result", "id": pid, "consistency": fc["consistency"],
                "begruendung": fc["begruendung"], "quellen": fc["quellen"],
            })
        except Exception:
            logger.exception("Fast check failed for streamed claim")
            await self.db.update_fact_check(pid, {
                "sprecher": self._claim_speakers.get(pid, speaker), "behauptung": claim, "consistency": "",
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
            if getattr(event, "end_of_turn", False):
                _log_mixed_speakers(self.session_id, "turn", getattr(event, "turn_order", None),
                                    getattr(event, "speaker_label", None), getattr(event, "words", None))
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
            for r in getattr(event, "revisions", []) or []:
                _log_mixed_speakers(self.session_id, "revision", getattr(r, "turn_order", None),
                                    getattr(r, "speaker_label", None), getattr(r, "words", None))
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
            speech_model=STREAM_SPEECH_MODEL,
            language_codes=["de"],  # a single language: a German-only session
            format_turns=True,
            speaker_labels=True,
            max_speakers=self._max_speakers(),
            speaker_labels_revision_interval_ms=STREAM_SPEAKER_REVISION_MS or None,
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
