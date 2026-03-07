"""Unit tests for circuit breaker infrastructure."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pybreaker import CircuitBreakerError

from app.core.circuit_breaker import (
    _ALL_BREAKERS,
    _wrap_with_breaker,
    get_circuit_breaker_states,
    kling_breaker,
    openai_breaker,
    pexels_breaker,
    reset_circuit_breaker,
    runway_breaker,
    stability_breaker,
    whisper_breaker,
    with_kling_breaker,
    with_openai_breaker,
    with_pexels_breaker,
    with_runway_breaker,
    with_stability_breaker,
    with_whisper_breaker,
    with_youtube_breaker,
)


class TestBreakerInstances:
    """Test that all 9 breaker instances are properly configured."""

    def test_all_nine_breakers_exist(self):
        assert len(_ALL_BREAKERS) == 9
        expected = {
            "openai", "anthropic", "elevenlabs", "pexels", "youtube",
            "runway", "stability", "kling", "whisper",
        }
        assert set(_ALL_BREAKERS.keys()) == expected

    def test_runway_breaker_config(self):
        assert runway_breaker.fail_max == 3
        assert runway_breaker.reset_timeout == 120

    def test_stability_breaker_config(self):
        assert stability_breaker.fail_max == 3
        assert stability_breaker.reset_timeout == 120

    def test_kling_breaker_config(self):
        assert kling_breaker.fail_max == 3
        assert kling_breaker.reset_timeout == 120

    def test_whisper_breaker_config(self):
        assert whisper_breaker.fail_max == 3
        assert whisper_breaker.reset_timeout == 60


class TestGetCircuitBreakerStates:
    """Test state monitoring."""

    def test_returns_all_nine(self):
        states = get_circuit_breaker_states()
        assert len(states) == 9
        for name in _ALL_BREAKERS:
            assert name in states
            assert "state" in states[name]
            assert "fail_counter" in states[name]
            assert "fail_max" in states[name]


class TestResetCircuitBreaker:
    """Test manual reset."""

    def test_reset_known_breaker(self):
        assert reset_circuit_breaker("runway") is True

    def test_reset_unknown_breaker(self):
        assert reset_circuit_breaker("nonexistent") is False

    def test_reset_case_insensitive(self):
        assert reset_circuit_breaker("WHISPER") is True


class TestWrapWithBreakerAsync:
    """Test auto-detect async wrapping."""

    def test_wraps_async_function(self):
        async def my_async_fn():
            return "ok"

        breaker = MagicMock()
        breaker.call_async = AsyncMock(return_value="ok")
        breaker.name = "test"

        wrapped = _wrap_with_breaker(breaker, my_async_fn)
        assert asyncio.iscoroutinefunction(wrapped)

    def test_wraps_sync_function(self):
        def my_sync_fn():
            return "ok"

        breaker = MagicMock()
        breaker.call = MagicMock(return_value="ok")
        breaker.name = "test"

        wrapped = _wrap_with_breaker(breaker, my_sync_fn)
        assert not asyncio.iscoroutinefunction(wrapped)


class TestDecoratorFactory:
    """Test that decorator factories return proper decorators."""

    def test_with_runway_breaker_wraps(self):
        @with_runway_breaker()
        async def dummy():
            pass

        assert asyncio.iscoroutinefunction(dummy)

    def test_with_stability_breaker_wraps(self):
        @with_stability_breaker()
        async def dummy():
            pass

        assert asyncio.iscoroutinefunction(dummy)

    def test_with_kling_breaker_wraps(self):
        @with_kling_breaker()
        async def dummy():
            pass

        assert asyncio.iscoroutinefunction(dummy)

    def test_with_whisper_breaker_wraps(self):
        @with_whisper_breaker()
        async def dummy():
            pass

        assert asyncio.iscoroutinefunction(dummy)

    def test_with_youtube_breaker_wraps_sync(self):
        @with_youtube_breaker()
        def dummy():
            pass

        assert not asyncio.iscoroutinefunction(dummy)
