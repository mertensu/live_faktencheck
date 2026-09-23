"""
Unit tests for backend/services/speaker_track.py: sentence → word time span mapping (§4.1)
and the overlap-weighted speaker-track vote (§5.2). Pure Python, no audio.
"""

from backend.services.speaker_track import SpeakerTrack, sentence_span


def _words(text: str, start: int = 0, step: int = 300) -> list[dict]:
    """Raw ASR-style words with evenly spaced timestamps (ms)."""
    return [{"text": w, "start": start + i * step, "end": start + i * step + step - 50}
            for i, w in enumerate(text.split())]


class TestSentenceSpan:
    def test_exact_match_ignores_case_and_punctuation(self):
        words = _words("guten abend wir reden heute über die rente")
        # "wir reden heute" = words 2..4
        assert sentence_span("Wir reden heute.", words) == (600, 1450)

    def test_second_sentence_in_turn(self):
        words = _words("das ist gut die rente ist sicher")
        assert sentence_span("Die Rente ist sicher!", words) == (900, 2050)

    def test_number_heavy_sentence_uses_anchor_match(self):
        # Formatted "20 %" vs raw "zwanzig prozent": exact fails, head+tail anchors hit.
        words = _words("also die inflation lag im letzten jahr bei zwanzig prozent "
                       "das sagt das statistische bundesamt")
        span = sentence_span("Die Inflation lag im letzten Jahr bei 20 %, "
                             "das sagt das Statistische Bundesamt.", words)
        assert span == (300, words[-1]["end"])

    def test_numbers_at_both_ends_fall_back_to_head_anchor(self):
        words = _words("die löhne sind um drei prozent gestiegen seit zweitausendzwanzig")
        span = sentence_span("Die Löhne sind um 3 % gestiegen seit 2020.", words)
        assert span is not None
        assert span[0] == 0  # head anchor "die löhne sind"
        assert span[1] > span[0]

    def test_rough_estimate_from_turn_text(self):
        # Neither anchor matches the raw words, but the sentence sits in the turn text.
        words = _words("eins zwei drei vier fünf sechs sieben acht")
        turn_text = "Eins zwei drei vier. 5 6 7 8."
        span = sentence_span("5 6 7 8.", words, turn_text=turn_text)
        assert span is not None
        assert words[0]["start"] < span[0] < span[1] <= words[-1]["end"]

    def test_no_match_returns_none(self):
        assert sentence_span("Völlig anderer Satz hier.", _words("eins zwei drei")) is None

    def test_missing_inputs_return_none(self):
        assert sentence_span(None, _words("a b")) is None
        assert sentence_span("a b", []) is None


class TestSpeakerTrack:
    def _track(self, *entries, **kw):
        t = SpeakerTrack(unknown_threshold=kw.pop("unknown_threshold", 0.35), **kw)
        for e in entries:
            t.add(*e)
        return t

    def test_clear_majority_names_speaker(self):
        t = self._track((0, 3000, "Alice", 0.8), (1000, 4000, "Alice", 0.7))
        v = t.dominant(1500, 2500)
        assert v.name == "Alice" and not v.unknown
        assert v.score == 0.75

    def test_mixed_windows_yield_no_name(self):
        t = self._track((0, 3000, "Alice", 0.8), (1000, 4000, "Bob", 0.8))
        assert t.dominant(1000, 3000).name is None

    def test_none_windows_count_against_majority(self):
        t = self._track((0, 3000, "Alice", 0.8), (1000, 4000, None, 0.45),
                        (2000, 5000, None, 0.45))
        assert t.dominant(2000, 3000).name is None

    def test_short_sentence_reads_every_overlapping_window(self):
        # 3 s windows, 1 s hop; a 0.5 s sentence at 3.2–3.7 s overlaps windows 1–3 s..4–7 s.
        t = self._track((0, 3000, "Bob", 0.8), (1000, 4000, "Alice", 0.8),
                        (2000, 5000, "Alice", 0.8), (3000, 6000, "Alice", 0.8))
        assert t.dominant(3200, 3700).name == "Alice"

    def test_overlap_weighting(self):
        # Span 2500–4000: Bob window overlaps 500 ms, Alice window 1500 ms → 75 % Alice.
        t = self._track((0, 3000, "Bob", 0.8), (2500, 5500, "Alice", 0.8))
        assert t.dominant(2500, 4000).name == "Alice"

    def test_all_windows_below_unknown_threshold_is_unknown(self):
        t = self._track((0, 3000, None, 0.2), (1000, 4000, None, 0.25))
        v = t.dominant(500, 3500)
        assert v.unknown and v.name is None

    def test_between_thresholds_is_not_unknown(self):
        t = self._track((0, 3000, None, 0.2), (1000, 4000, None, 0.45))
        v = t.dominant(500, 3500)
        assert not v.unknown and v.name is None

    def test_quiet_window_prevents_unknown(self):
        # Energy-gated (score None) windows are not "loud enough" evidence of a foreign voice.
        t = self._track((0, 3000, None, None), (1000, 4000, None, 0.2))
        assert not t.dominant(500, 3500).unknown

    def test_empty_span_and_coverage(self):
        t = self._track((0, 3000, "Alice", 0.8))
        assert t.dominant(5000, 6000).name is None
        assert t.covers(3000) and not t.covers(3001)

    def test_plurality_without_majority(self):
        t = self._track((0, 3000, "Alice", 0.6), (0, 3000, None, 0.5), (0, 3000, "Bob", 0.6),
                        (0, 3000, "Alice", 0.6))
        v = t.dominant(0, 3000)
        assert v.name is None and v.plurality == "Alice"
