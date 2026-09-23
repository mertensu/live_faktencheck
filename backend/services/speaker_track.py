"""
Speaker-over-time track for voiceprint speaker ID (live fast lane, SPEAKER_ID_ENABLED).

Two pure pieces, kept free of numpy/ONNX so ``streaming.py`` can import them on a dark flag:

- ``sentence_span``: map a claim's ``source`` sentence (formatted text) onto the turn's ASR
  ``words`` (raw tokens with ms timestamps) → ``(start_ms, end_ms)``. Formatted text and raw
  words differ ("20 %" vs "zwanzig Prozent"), so exact matching falls back to anchor
  matching on the first/last tokens, then to a rough position estimate. Only an approximate
  span is needed — it just selects which track windows to read.
- ``SpeakerTrack``: the classified sliding windows ``(start_ms, end_ms, name|None, score)``
  and the overlap-weighted vote that reads the dominant speaker over a span.

See ``docs/speaker-id-integration-plan.md`` §4.1 and §5.2.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Anchor sizes tried in order: 3 tokens is specific enough in a turn, 2 still beats nothing.
_ANCHOR_SIZES = (3, 2)


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens; punctuation and whitespace dropped."""
    return _TOKEN_RE.findall((text or "").casefold())


def _find(seq: list[str], sub: list[str], start: int = 0) -> int:
    """Index of the first occurrence of ``sub`` in ``seq`` at or after ``start``, else -1."""
    n = len(sub)
    if not n:
        return -1
    for i in range(start, len(seq) - n + 1):
        if seq[i:i + n] == sub:
            return i
    return -1


def sentence_span(sentence: str | None, words: list[dict] | None,
                  turn_text: str | None = None) -> tuple[int, int] | None:
    """Approximate ``(start_ms, end_ms)`` of ``sentence`` within ``words``, or None.

    Fallback chain (§4.1): exact token match → anchor match on the first/last tokens →
    rough estimate from the sentence's position in ``turn_text`` → None (skip ID).
    """
    if not sentence or not words:
        return None
    # Flatten words into tokens, remembering which word each token came from.
    stream: list[str] = []
    owner: list[int] = []
    for i, w in enumerate(words):
        for tok in _tokens(w.get("text", "")):
            stream.append(tok)
            owner.append(i)
    sent = _tokens(sentence)
    if not stream or not sent:
        return None

    def span(first_tok: int, last_tok: int) -> tuple[int, int]:
        return words[owner[first_tok]]["start"], words[owner[last_tok]]["end"]

    # 1. Exact: the whole sentence appears as a token run.
    i = _find(stream, sent)
    if i >= 0:
        return span(i, i + len(sent) - 1)

    # 2. Anchors: head and/or tail tokens. Numbers inside the sentence ("20 %" vs "zwanzig
    # Prozent") break exact matching but rarely both ends.
    ms_per_tok = max(1, (words[-1]["end"] - words[0]["start"]) // max(1, len(stream)))
    for k in _ANCHOR_SIZES:
        if len(sent) < k:
            continue
        head = _find(stream, sent[:k])
        tail = _find(stream, sent[-k:], head + k if head >= 0 else 0)
        if head >= 0 and tail >= 0:
            return span(head, tail + k - 1)
        if head >= 0:
            start = words[owner[head]]["start"]
            return start, start + len(sent) * ms_per_tok
        if tail >= 0:
            end = words[owner[tail + k - 1]]["end"]
            return max(0, end - len(sent) * ms_per_tok), end

    # 3. Rough estimate: interpolate the sentence's character position in the formatted
    # turn text onto the turn's time range.
    if turn_text:
        pos = turn_text.find(sentence.strip())
        if pos >= 0 and len(turn_text):
            t0, t1 = words[0]["start"], words[-1]["end"]
            dur = t1 - t0
            start = t0 + int(dur * pos / len(turn_text))
            end = t0 + int(dur * (pos + len(sentence.strip())) / len(turn_text))
            return start, max(end, start + 1)

    # 4. Give up: the caller keeps the label.
    return None


@dataclass
class TrackVerdict:
    """Result of reading the track over a span.

    ``name`` is set only for a clear, confident majority. ``unknown`` means every
    overlapping window was loud and scored below the unknown threshold — a clearly foreign
    voice (clip, caller, audience), not just an unsure one. ``score`` is the mean score of
    the winning name's windows (or of all scored windows for unknown/None). ``plurality``
    is the strongest name even without a clear majority — too weak on its own, but usable
    to confirm an independent signal (the diarization label's name).
    """

    name: str | None = None
    score: float | None = None
    unknown: bool = False
    plurality: str | None = None


class SpeakerTrack:
    """Session-long list of classified windows; tiny (one entry per hop)."""

    def __init__(self, *, majority: float = 0.6, unknown_threshold: float = 0.35):
        self.majority = majority
        self.unknown_threshold = unknown_threshold
        # (win_start_ms, win_end_ms, name|None, score|None); score None = energy-gated.
        self.entries: list[tuple[int, int, str | None, float | None]] = []
        self.covered_ms = 0  # end of the newest classified window

    def add(self, start_ms: int, end_ms: int, name: str | None, score: float | None) -> None:
        self.entries.append((start_ms, end_ms, name, score))
        self.covered_ms = max(self.covered_ms, end_ms)

    def covers(self, end_ms: int) -> bool:
        return end_ms <= self.covered_ms

    def dominant(self, start_ms: int, end_ms: int) -> TrackVerdict:
        """Overlap-weighted vote over every window that overlaps ``[start_ms, end_ms]``.

        ``None`` windows (unknown/quiet) count against a clear majority, so a mixed or
        unclear span yields no name rather than a confident wrong one.
        """
        weights: dict[str | None, float] = defaultdict(float)
        scores: dict[str | None, list[float]] = defaultdict(list)
        overlapping = []
        for ws, we, name, score in self.entries:
            overlap = min(we, end_ms) - max(ws, start_ms)
            if overlap <= 0:
                continue
            overlapping.append(score)
            weights[name] += overlap
            if score is not None:
                scores[name].append(score)
        if not overlapping:
            return TrackVerdict()

        all_scores = [s for s in overlapping if s is not None]
        mean = (sum(all_scores) / len(all_scores)) if all_scores else None
        if all(s is not None and s < self.unknown_threshold for s in overlapping):
            return TrackVerdict(score=mean, unknown=True)

        total = sum(weights.values())
        named = {n: w for n, w in weights.items() if n is not None}
        if named:
            best = max(named, key=named.get)
            if named[best] / total >= self.majority:
                s = scores[best]
                return TrackVerdict(name=best, score=sum(s) / len(s) if s else None, plurality=best)
            return TrackVerdict(score=mean, plurality=best)
        return TrackVerdict(score=mean)
