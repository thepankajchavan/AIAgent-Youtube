"""
Hook Scorer Service — scores the opening sentence of a script for engagement.

Analyses the first sentence for 6 engagement signals commonly found in
viral YouTube Shorts hooks: questions, numbers, superlatives, direct address,
curiosity gaps, and power words. Returns a composite score (0.0-1.0) and
actionable feedback that the LLM quality-retry loop can use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class HookScore:
    """Result of hook engagement analysis."""

    total: float                        # 0.0-1.0 composite score
    signals: dict[str, bool] = field(default_factory=dict)  # detected signals
    feedback: str = ""                  # LLM-usable improvement feedback


# ── Engagement Signal Definitions ────────────────────────────────
# Each signal: (regex_pattern, weight, feedback_hint)

ENGAGEMENT_SIGNALS: dict[str, tuple[str, float, str]] = {
    "question": (
        r"\?",
        0.20,
        "Start with a question to pull the viewer in",
    ),
    "number": (
        r"\b\d[\d,.']*%?\b",
        0.15,
        "Include a specific number or statistic for credibility",
    ),
    "superlative": (
        r"\b(most|biggest|fastest|deadliest|worst|best|craziest|strangest|smallest|largest|longest|shortest|oldest|newest|rarest|deepest)\b",
        0.15,
        "Use a superlative (most, biggest, deadliest) to create scale",
    ),
    "you_address": (
        r"\byou\b",
        0.15,
        "Address the viewer directly with 'you' to make it personal",
    ),
    "curiosity_gap": (
        r"\b(secret|hidden|never knew|no one talks about|actually|turns out|didn't know|won't believe|what if|imagine)\b",
        0.20,
        "Create a curiosity gap (secret, hidden, never knew, won't believe)",
    ),
    "power_word": (
        r"\b(killed|destroyed|impossible|shocking|terrifying|insane|banned|illegal|deadly|lethal|forbidden|unstoppable|unbelievable)\b",
        0.15,
        "Use a power word (shocking, terrifying, impossible) for emotional punch",
    ),
}


def _extract_first_sentence(text: str) -> str:
    """Extract the first sentence from script text.

    Handles sentences ending with . ! or ? and also takes
    the first line if no sentence-ending punctuation is found.
    """
    text = text.strip()
    if not text:
        return ""

    # Match up to the first sentence-ending punctuation
    match = re.match(r"^(.+?[.!?])", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # No punctuation found — take first line
    first_line = text.split("\n")[0].strip()
    return first_line


def score_hook(script_text: str) -> HookScore:
    """Score the first sentence of a script for engagement signals.

    Returns a HookScore with:
    - total: composite score 0.0-1.0 (sum of detected signal weights)
    - signals: dict of signal_name → bool (detected or not)
    - feedback: actionable text for LLM to improve weak hooks
    """
    hook_text = _extract_first_sentence(script_text)

    if not hook_text:
        return HookScore(
            total=0.0,
            signals={name: False for name in ENGAGEMENT_SIGNALS},
            feedback="The script has no hook — start with a compelling opening sentence.",
        )

    total = 0.0
    signals: dict[str, bool] = {}
    missing_feedback: list[str] = []

    for name, (pattern, weight, hint) in ENGAGEMENT_SIGNALS.items():
        found = bool(re.search(pattern, hook_text, re.IGNORECASE))
        signals[name] = found
        if found:
            total += weight
        else:
            missing_feedback.append(hint)

    # Cap at 1.0
    total = min(total, 1.0)

    # Build feedback from top 2 missing signals
    if missing_feedback:
        feedback = "Strengthen the hook: " + ". ".join(missing_feedback[:2]) + "."
    else:
        feedback = ""

    return HookScore(total=total, signals=signals, feedback=feedback)
