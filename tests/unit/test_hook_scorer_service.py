"""Unit tests for HookScorerService — pure logic, no mocks needed."""

from __future__ import annotations

import pytest

from app.services.hook_scorer_service import (
    ENGAGEMENT_SIGNALS,
    HookScore,
    _extract_first_sentence,
    score_hook,
)


# ── TestExtractFirstSentence ───────────────────────────────────


class TestExtractFirstSentence:
    """Tests for _extract_first_sentence helper."""

    def test_period_ending(self):
        text = "This is a sentence. And this is another."
        assert _extract_first_sentence(text) == "This is a sentence."

    def test_exclamation_ending(self):
        text = "Wow this is amazing! You need to see it."
        assert _extract_first_sentence(text) == "Wow this is amazing!"

    def test_question_mark_ending(self):
        text = "Did you know this? It will blow your mind."
        assert _extract_first_sentence(text) == "Did you know this?"

    def test_multiline_text_extracts_first_sentence(self):
        text = "First sentence here.\nSecond line.\nThird line."
        assert _extract_first_sentence(text) == "First sentence here."

    def test_multiline_sentence_spanning_lines(self):
        text = "This sentence\nspans two lines. Then another."
        assert _extract_first_sentence(text) == "This sentence\nspans two lines."

    def test_empty_text(self):
        assert _extract_first_sentence("") == ""

    def test_whitespace_only(self):
        assert _extract_first_sentence("   \n\t  ") == ""

    def test_no_punctuation_fallback_to_first_line(self):
        text = "No punctuation here\nSecond line without it"
        assert _extract_first_sentence(text) == "No punctuation here"

    def test_no_punctuation_single_line(self):
        text = "Just a fragment with no ending"
        assert _extract_first_sentence(text) == "Just a fragment with no ending"

    def test_leading_trailing_whitespace_stripped(self):
        text = "   Hello world.   Rest of text."
        assert _extract_first_sentence(text) == "Hello world."


# ── TestScoreHook ──────────────────────────────────────────────


class TestScoreHook:
    """Tests for score_hook composite scoring."""

    def test_question_hook_scores_at_least_0_2(self):
        result = score_hook("Did you know this?")
        # "?" triggers question (0.20), "you" triggers you_address (0.15)
        assert result.total >= 0.20
        assert result.signals["question"] is True

    def test_multi_signal_hook_scores_above_0_5(self):
        # question (0.20) + number (0.15) + you_address (0.15) = 0.50
        result = score_hook("Did you know 99% of people fail? The rest is history.")
        assert result.total >= 0.50
        assert result.signals["question"] is True
        assert result.signals["number"] is True
        assert result.signals["you_address"] is True

    def test_bland_statement_scores_below_0_3(self):
        result = score_hook("The weather is nice today.")
        assert result.total < 0.30

    def test_returns_hook_score_dataclass(self):
        result = score_hook("A simple hook.")
        assert isinstance(result, HookScore)
        assert isinstance(result.total, float)
        assert isinstance(result.signals, dict)
        assert isinstance(result.feedback, str)

    def test_total_capped_at_1_0(self):
        # Pack every signal into one sentence
        hook = "Did you know the most shocking secret killed 1,000 people?"
        result = score_hook(hook)
        assert result.total <= 1.0

    def test_all_six_signal_keys_present(self):
        result = score_hook("Anything at all.")
        assert set(result.signals.keys()) == set(ENGAGEMENT_SIGNALS.keys())

    def test_only_first_sentence_scored(self):
        # Second sentence has signals but should not count
        text = "Plain boring text. Did you know the most shocking secret?"
        result = score_hook(text)
        assert result.signals["question"] is False
        assert result.signals["curiosity_gap"] is False


# ── TestEngagementSignals ──────────────────────────────────────


class TestEngagementSignals:
    """Tests that each individual signal is detected correctly."""

    def test_question_signal(self):
        result = score_hook("Is this real?")
        assert result.signals["question"] is True
        assert result.total >= 0.20

    def test_number_signal_integer(self):
        result = score_hook("There are 500 species left.")
        assert result.signals["number"] is True
        assert result.total >= 0.15

    def test_number_signal_percentage(self):
        result = score_hook("About 73% of people agree.")
        assert result.signals["number"] is True

    def test_number_signal_with_commas(self):
        result = score_hook("Over 1,000,000 sold worldwide.")
        assert result.signals["number"] is True

    def test_superlative_signal_most(self):
        result = score_hook("The most dangerous animal alive.")
        assert result.signals["superlative"] is True
        assert result.total >= 0.15

    def test_superlative_signal_biggest(self):
        result = score_hook("The biggest wave ever recorded.")
        assert result.signals["superlative"] is True

    def test_superlative_signal_deadliest(self):
        result = score_hook("The deadliest virus in history.")
        assert result.signals["superlative"] is True

    def test_superlative_signal_worst(self):
        result = score_hook("The worst disaster of the century.")
        assert result.signals["superlative"] is True

    def test_you_address_signal(self):
        result = score_hook("This will change how you see the world.")
        assert result.signals["you_address"] is True
        assert result.total >= 0.15

    def test_curiosity_gap_signal_secret(self):
        result = score_hook("There is a secret door in this building.")
        assert result.signals["curiosity_gap"] is True
        assert result.total >= 0.20

    def test_curiosity_gap_signal_hidden(self):
        result = score_hook("A hidden message was found.")
        assert result.signals["curiosity_gap"] is True

    def test_curiosity_gap_signal_never_knew(self):
        result = score_hook("Something people never knew about the ocean.")
        assert result.signals["curiosity_gap"] is True

    def test_curiosity_gap_signal_wont_believe(self):
        result = score_hook("What happened next, people won't believe.")
        assert result.signals["curiosity_gap"] is True

    def test_curiosity_gap_signal_what_if(self):
        result = score_hook("What if gravity stopped working.")
        assert result.signals["curiosity_gap"] is True

    def test_power_word_signal_destroyed(self):
        result = score_hook("A meteor destroyed the entire city.")
        assert result.signals["power_word"] is True
        assert result.total >= 0.15

    def test_power_word_signal_impossible(self):
        result = score_hook("Scientists said it was impossible.")
        assert result.signals["power_word"] is True

    def test_power_word_signal_shocking(self):
        result = score_hook("The shocking truth about sleep.")
        assert result.signals["power_word"] is True

    def test_power_word_signal_terrifying(self):
        result = score_hook("A terrifying creature was discovered.")
        assert result.signals["power_word"] is True

    def test_signal_detection_is_case_insensitive(self):
        result = score_hook("The MOST SHOCKING discovery ever.")
        assert result.signals["superlative"] is True
        assert result.signals["power_word"] is True

    def test_signal_not_detected_when_absent(self):
        result = score_hook("The sky is blue.")
        assert result.signals["question"] is False
        assert result.signals["number"] is False
        assert result.signals["superlative"] is False
        assert result.signals["you_address"] is False
        assert result.signals["curiosity_gap"] is False
        assert result.signals["power_word"] is False


# ── TestHookFeedback ───────────────────────────────────────────


class TestHookFeedback:
    """Tests for feedback generation."""

    def test_low_score_returns_actionable_feedback(self):
        result = score_hook("The sky is blue.")
        assert result.feedback != ""
        assert result.feedback.startswith("Strengthen the hook:")

    def test_feedback_contains_at_most_two_hints(self):
        result = score_hook("The sky is blue.")
        # "Strengthen the hook: " prefix, then at most 2 hint sentences joined by ". "
        # Count the signal-specific feedback hints present
        hint_count = 0
        for _, (_, _, hint) in ENGAGEMENT_SIGNALS.items():
            if hint in result.feedback:
                hint_count += 1
        assert hint_count <= 2

    def test_perfect_score_has_empty_feedback(self):
        # Trigger all 6 signals in one sentence
        hook = "Did you know the most shocking secret killed 1,000 people?"
        result = score_hook(hook)
        # Verify all signals fire
        assert all(result.signals.values()), f"Not all signals fired: {result.signals}"
        assert result.feedback == ""

    def test_partial_signal_feedback_references_missing(self):
        # Only question signal fires
        result = score_hook("Is this real?")
        assert "Strengthen the hook:" in result.feedback
        # Should not mention question-related hint since it was detected
        question_hint = ENGAGEMENT_SIGNALS["question"][2]
        assert question_hint not in result.feedback

    def test_empty_script_feedback(self):
        result = score_hook("")
        assert "no hook" in result.feedback.lower()


# ── TestEdgeCases ──────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests for hook scoring."""

    def test_empty_string(self):
        result = score_hook("")
        assert result.total == 0.0
        assert all(v is False for v in result.signals.values())
        assert result.feedback != ""

    def test_single_word(self):
        result = score_hook("Hello")
        assert isinstance(result.total, float)
        assert result.total >= 0.0
        assert set(result.signals.keys()) == set(ENGAGEMENT_SIGNALS.keys())

    def test_all_signals_present(self):
        # question + number + superlative + you_address + curiosity_gap + power_word
        hook = "Did you know the most shocking secret killed 1,000 people?"
        result = score_hook(hook)

        assert result.signals["question"] is True       # "?"
        assert result.signals["number"] is True          # "1,000"
        assert result.signals["superlative"] is True     # "most"
        assert result.signals["you_address"] is True     # "you"
        assert result.signals["curiosity_gap"] is True   # "secret"
        assert result.signals["power_word"] is True      # "killed" + "shocking"

        expected_total = sum(w for _, w, _ in ENGAGEMENT_SIGNALS.values())
        assert result.total == min(expected_total, 1.0)
        assert result.feedback == ""

    def test_only_whitespace_and_newlines(self):
        result = score_hook("   \n\n\t  ")
        assert result.total == 0.0
        assert all(v is False for v in result.signals.values())

    def test_special_characters_do_not_crash(self):
        result = score_hook("!@#$%^&*()_+-=[]{}|;':\",./<>")
        assert isinstance(result, HookScore)

    def test_very_long_text_only_scores_first_sentence(self):
        first = "A plain sentence."
        rest = " Did you know the most shocking secret? " * 100
        result = score_hook(first + rest)
        # Only "A plain sentence." is scored
        assert result.signals["question"] is False
        assert result.signals["curiosity_gap"] is False

    def test_hook_score_dataclass_defaults(self):
        hs = HookScore(total=0.5)
        assert hs.total == 0.5
        assert hs.signals == {}
        assert hs.feedback == ""

    def test_engagement_signals_weights_sum_to_1(self):
        total_weight = sum(w for _, w, _ in ENGAGEMENT_SIGNALS.values())
        assert total_weight == pytest.approx(1.0, abs=0.01)

    def test_engagement_signals_has_six_entries(self):
        assert len(ENGAGEMENT_SIGNALS) == 6
