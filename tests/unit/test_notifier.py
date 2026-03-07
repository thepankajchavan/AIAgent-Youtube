"""Tests for Telegram notifier — status update delivery."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from telegram.error import RetryAfter, TelegramError

from app.telegram.notifier import format_status_message, handle_status_update


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


@pytest.fixture
def mock_redis():
    """Mock Redis client for status message ID tracking."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # No existing message by default
    redis.set = AsyncMock()
    return redis


def _make_event(status="SCRIPT_GENERATING", extra=None):
    return {
        "project_id": "test-project-123",
        "status": status,
        "telegram_user_id": 111,
        "telegram_chat_id": 222,
        "telegram_message_id": 333,
        "extra": extra or {},
    }


# ── handle_status_update tests ───────────────────────────────


class TestHandleStatusUpdate:
    """Tests for handle_status_update — edit-in-place with Redis tracking."""

    @pytest.mark.asyncio
    async def test_first_event_sends_new_message(self, mock_bot, mock_redis):
        """First status update sends a new message and stores ID in Redis."""
        msg = AsyncMock()
        msg.message_id = 999
        mock_bot.send_message.return_value = msg

        event = _make_event("AUDIO_GENERATING")
        await handle_status_update(mock_bot, event, mock_redis)

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 222
        assert "Generating voiceover" in call_kwargs["text"]
        assert call_kwargs["parse_mode"] == "Markdown"
        # Should store message ID in Redis
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_subsequent_event_edits_message(self, mock_bot, mock_redis):
        """Subsequent intermediate status edits existing message."""
        mock_redis.get.return_value = "999"  # Existing message ID

        event = _make_event("UPLOADING")
        await handle_status_update(mock_bot, event, mock_redis)

        mock_bot.edit_message_text.assert_called_once()
        call_kwargs = mock_bot.edit_message_text.call_args.kwargs
        assert call_kwargs["chat_id"] == 222
        assert call_kwargs["message_id"] == 999

    @pytest.mark.asyncio
    async def test_completed_includes_youtube_url(self, mock_bot, mock_redis):
        """COMPLETED status includes YouTube link in message text."""
        event = _make_event("COMPLETED", extra={"youtube_url": "https://youtu.be/abc123"})
        await handle_status_update(mock_bot, event, mock_redis)

        # Should send new message (no existing msg tracked)
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert "https://youtu.be/abc123" in call_kwargs["text"]
        assert "Watch on YouTube" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_completed_enables_web_preview(self, mock_bot, mock_redis):
        """COMPLETED messages show YouTube link preview."""
        event = _make_event("COMPLETED", extra={"youtube_url": "https://youtu.be/abc123"})
        await handle_status_update(mock_bot, event, mock_redis)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["disable_web_page_preview"] is False

    @pytest.mark.asyncio
    async def test_failed_sends_message(self, mock_bot, mock_redis):
        """FAILED status sends a message (no existing message tracked)."""
        event = _make_event("FAILED")
        await handle_status_update(mock_bot, event, mock_redis)

        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_includes_error(self, mock_bot, mock_redis):
        """FAILED status includes error message."""
        event = _make_event("FAILED", extra={"error": "Something broke"})
        await handle_status_update(mock_bot, event, mock_redis)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert "Something broke" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_rate_limit_retries(self, mock_bot, mock_redis):
        """RetryAfter triggers a retry after sleeping."""
        retry_err = RetryAfter(retry_after=1)
        mock_bot.send_message.side_effect = [retry_err, AsyncMock()]

        event = _make_event("ASSEMBLING")

        with patch("app.telegram.notifier.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await handle_status_update(mock_bot, event, mock_redis)

        mock_sleep.assert_called_once_with(1)
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_telegram_error_does_not_raise(self, mock_bot, mock_redis):
        """TelegramError is caught and logged, not raised."""
        mock_bot.send_message.side_effect = TelegramError("Network error")

        event = _make_event("UPLOADING")
        # Should not raise
        await handle_status_update(mock_bot, event, mock_redis)


# ── format_status_message tests ──────────────────────────────


class TestFormatStatusMessage:
    """Tests for format_status_message — emoji + text formatting."""

    @pytest.mark.parametrize(
        "status, expected_text",
        [
            ("SCRIPT_GENERATING", "Generating script..."),
            ("SCENE_SPLITTING", "Planning visual scenes..."),
            ("AUDIO_GENERATING", "Generating voiceover..."),
            ("VIDEO_GENERATING", "Generating video clips..."),
            ("ASSEMBLING", "Assembling final video..."),
            ("UPLOADING", "Uploading to YouTube..."),
            ("COMPLETED", "Done!"),
            ("FAILED", "Failed"),
        ],
    )
    def test_all_statuses_produce_correct_text(self, status, expected_text):
        text = format_status_message(status, "proj-1", {})
        assert expected_text in text

    def test_includes_project_id(self):
        text = format_status_message("UPLOADING", "my-project-42", {})
        assert "my-project-42" in text

    def test_completed_with_youtube_url(self):
        text = format_status_message(
            "COMPLETED", "proj-1", {"youtube_url": "https://youtu.be/xyz"}
        )
        assert "https://youtu.be/xyz" in text
        assert "Watch on YouTube" in text

    def test_completed_without_youtube_url(self):
        text = format_status_message("COMPLETED", "proj-1", {})
        assert "Done!" in text
        assert "Watch on YouTube" not in text

    def test_failed_with_error(self):
        text = format_status_message("FAILED", "proj-1", {"error": "API timeout"})
        assert "API timeout" in text

    def test_failed_without_error(self):
        text = format_status_message("FAILED", "proj-1", {})
        assert "Failed" in text

    def test_unknown_status_fallback(self):
        text = format_status_message("SOME_NEW_STATUS", "proj-1", {})
        assert "SOME_NEW_STATUS" in text
