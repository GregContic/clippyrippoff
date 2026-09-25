"""Transcript-based reaction signal detection."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TranscriptTrigger:
    start: float
    end: float
    text: str
    matched_keywords: list[str]
    score: float
    strength: str = "weak"


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip()


def _keyword_matches(text: str, keywords: list[str]) -> list[str]:
    normalised = _normalise(text)
    matches: list[str] = []
    for keyword in keywords:
        keyword_normalised = _normalise(keyword)
        if not keyword_normalised:
            continue
        pattern = rf"(?<!\w){re.escape(keyword_normalised)}(?!\w)"
        if re.search(pattern, normalised):
            matches.append(keyword_normalised)
    return matches


def detect_transcript_triggers(
    segments: list[dict],
    keywords: list[str] | dict[str, list[str]],
    strength_scores: dict[str, float] | None = None,
) -> list[TranscriptTrigger]:
    """Return reaction-bearing transcript segments with deterministic scores.

    Keywords are signals only. A trigger score is based on matched keyword
    count, exclamation/emphasis markers, and short utterance length.
    """
    if isinstance(keywords, dict):
        keyword_groups = {
            strength: [_normalise(keyword) for keyword in values]
            for strength, values in keywords.items()
        }
    else:
        keyword_groups = {"weak": [_normalise(keyword) for keyword in keywords]}
    strength_scores = strength_scores or {"weak": 0.2, "medium": 0.6, "strong": 1.0}
    keyword_strengths = {
        keyword: strength
        for strength in ("weak", "medium", "strong")
        for keyword in keyword_groups.get(strength, [])
        if keyword
    }
    triggers: list[TranscriptTrigger] = []
    for segment in segments:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        text = str(segment.get("text", "")).strip()
        if end <= start or not text:
            continue

        matches = _keyword_matches(text, list(keyword_strengths))
        normalised = _normalise(text)
        emphasis = min(normalised.count("!") + normalised.count("?"), 3)
        word_count = len(normalised.split())
        short_phrase_bonus = 1 if word_count <= 6 else 0
        if not matches and emphasis == 0:
            continue

        strength = max((keyword_strengths[match] for match in matches), key=lambda item: strength_scores.get(item, 0.0), default="weak")
        keyword_score = max((strength_scores.get(keyword_strengths[match], 0.0) for match in matches), default=0.0)
        score = min(1.0, 0.55 * keyword_score + 0.25 * emphasis / 3 + 0.20 * short_phrase_bonus)
        triggers.append(TranscriptTrigger(start, end, text, matches, score, strength))
    return triggers


def transcript_signal_for_window(
    triggers: list[TranscriptTrigger],
    start: float,
    end: float,
) -> tuple[str, float, list[str]]:
    """Summarise overlapping triggers as text, normalized strength, keywords."""
    overlapping = [trigger for trigger in triggers if trigger.end > start and trigger.start < end]
    if not overlapping:
        return "", 0.0, []
    overlapping.sort(key=lambda trigger: trigger.start)
    text = " ".join(trigger.text for trigger in overlapping).strip()
    score = max(trigger.score for trigger in overlapping)
    keywords = sorted({keyword for trigger in overlapping for keyword in trigger.matched_keywords})
    return text, score, keywords
