"""
Circuit Breaker - Handles external API failures gracefully.

Implements circuit breaker pattern for:
- OpenAI (with fallback to Anthropic)
- Anthropic
- ElevenLabs
- Pexels (with fallback to placeholder)
- YouTube
- Runway
- Stability AI
- Kling AI
- Whisper (OpenAI)

Circuit Breaker States:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests immediately fail
- HALF_OPEN: Testing if service recovered
"""

import asyncio
from collections.abc import Callable
from functools import wraps
from typing import Any

from loguru import logger
from pybreaker import CircuitBreaker, CircuitBreakerError

# ── Circuit Breakers for External Services ────────────────────

# LLM providers
openai_breaker = CircuitBreaker(fail_max=5, reset_timeout=120, name="OpenAI API")
anthropic_breaker = CircuitBreaker(fail_max=5, reset_timeout=120, name="Anthropic API")

# Media providers
elevenlabs_breaker = CircuitBreaker(fail_max=3, reset_timeout=60, name="ElevenLabs API")
pexels_breaker = CircuitBreaker(fail_max=5, reset_timeout=60, name="Pexels API")

# Upload
youtube_breaker = CircuitBreaker(fail_max=3, reset_timeout=120, name="YouTube API")

# AI video providers
runway_breaker = CircuitBreaker(fail_max=3, reset_timeout=120, name="Runway API")
stability_breaker = CircuitBreaker(fail_max=3, reset_timeout=120, name="Stability API")
kling_breaker = CircuitBreaker(fail_max=3, reset_timeout=120, name="Kling API")

# Transcription
whisper_breaker = CircuitBreaker(fail_max=3, reset_timeout=60, name="Whisper API")

# ── All breakers registry ────────────────────────────────────

_ALL_BREAKERS: dict[str, CircuitBreaker] = {
    "openai": openai_breaker,
    "anthropic": anthropic_breaker,
    "elevenlabs": elevenlabs_breaker,
    "pexels": pexels_breaker,
    "youtube": youtube_breaker,
    "runway": runway_breaker,
    "stability": stability_breaker,
    "kling": kling_breaker,
    "whisper": whisper_breaker,
}


# ── Generic breaker decorator (auto-detect sync/async) ──────


def _wrap_with_breaker(
    breaker: CircuitBreaker,
    func: Callable,
    on_open: Callable | None = None,
) -> Callable:
    """Wrap a function with a circuit breaker, auto-detecting sync/async."""
    if asyncio.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await breaker.call_async(func, *args, **kwargs)
            except CircuitBreakerError as e:
                logger.warning("{} circuit breaker open: {}", breaker.name, e)
                if on_open:
                    result = on_open(*args, **kwargs)
                    if asyncio.iscoroutine(result):
                        return await result
                    return result
                raise

        return async_wrapper
    else:

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return breaker.call(func, *args, **kwargs)
            except CircuitBreakerError as e:
                logger.warning("{} circuit breaker open: {}", breaker.name, e)
                if on_open:
                    return on_open(*args, **kwargs)
                raise

        return sync_wrapper


# ── Circuit Breaker Decorators ─────────────────────────────────


def with_openai_breaker(fallback_to_anthropic: bool = True):
    """
    Decorator to wrap OpenAI calls with circuit breaker.

    If circuit is open and fallback is enabled, tries Anthropic instead.
    """

    def decorator(func: Callable):
        if fallback_to_anthropic:

            async def _openai_fallback(*args, **kwargs):
                logger.info("Falling back to Anthropic API")
                from app.services.llm_service import generate_script_anthropic

                topic = kwargs.get("topic") or args[0] if args else None
                if topic:
                    return await generate_script_anthropic(topic)
                raise CircuitBreakerError("OpenAI circuit open, no fallback topic")

            return _wrap_with_breaker(openai_breaker, func, on_open=_openai_fallback)
        return _wrap_with_breaker(openai_breaker, func)

    return decorator


def with_anthropic_breaker():
    """Decorator to wrap Anthropic calls with circuit breaker."""

    def decorator(func: Callable):
        return _wrap_with_breaker(anthropic_breaker, func)

    return decorator


def with_elevenlabs_breaker():
    """Decorator to wrap ElevenLabs calls with circuit breaker."""

    def decorator(func: Callable):
        return _wrap_with_breaker(elevenlabs_breaker, func)

    return decorator


def with_pexels_breaker(fallback_to_placeholder: bool = True):
    """
    Decorator to wrap Pexels calls with circuit breaker.

    If circuit is open and fallback is enabled, uses placeholder images.
    """

    def decorator(func: Callable):
        if fallback_to_placeholder:

            async def _pexels_fallback(*args, **kwargs):
                logger.info("Falling back to placeholder videos")
                from app.services.visual_service import create_placeholder_video

                query = kwargs.get("query") or args[0] if args else "video content"
                duration = kwargs.get("duration", 30)
                return await create_placeholder_video(query, duration)

            return _wrap_with_breaker(pexels_breaker, func, on_open=_pexels_fallback)
        return _wrap_with_breaker(pexels_breaker, func)

    return decorator


def with_youtube_breaker():
    """Decorator to wrap YouTube API calls with circuit breaker."""

    def decorator(func: Callable):
        return _wrap_with_breaker(youtube_breaker, func)

    return decorator


def with_runway_breaker():
    """Decorator to wrap Runway API calls with circuit breaker."""

    def decorator(func: Callable):
        return _wrap_with_breaker(runway_breaker, func)

    return decorator


def with_stability_breaker():
    """Decorator to wrap Stability AI calls with circuit breaker."""

    def decorator(func: Callable):
        return _wrap_with_breaker(stability_breaker, func)

    return decorator


def with_kling_breaker():
    """Decorator to wrap Kling AI calls with circuit breaker."""

    def decorator(func: Callable):
        return _wrap_with_breaker(kling_breaker, func)

    return decorator


def with_whisper_breaker():
    """Decorator to wrap Whisper API calls with circuit breaker."""

    def decorator(func: Callable):
        return _wrap_with_breaker(whisper_breaker, func)

    return decorator


# ── Queue Backpressure ────────────────────────────────────────


class QueueBackpressure:
    """
    Prevent system overload by rejecting new pipelines when queue is too deep.
    """

    MAX_QUEUE_DEPTH = 50  # Maximum tasks waiting in queue
    CHECK_INTERVAL = 5  # Seconds between checks

    @classmethod
    async def check_queue_depth(cls) -> int:
        """
        Check current queue depth across all queues.

        Returns:
            Total number of tasks waiting in queues
        """
        from app.core.celery_app import celery_app

        def _sync_inspect() -> int:
            inspect = celery_app.control.inspect(timeout=3.0)
            reserved = inspect.reserved()
            if not reserved:
                return 0
            return sum(len(tasks) for tasks in reserved.values())

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_inspect)

    @classmethod
    async def can_accept_new_pipeline(cls) -> tuple[bool, int]:
        """
        Check if system can accept a new pipeline.

        Returns:
            Tuple of (can_accept, current_depth)
        """
        current_depth = await cls.check_queue_depth()

        can_accept = current_depth < cls.MAX_QUEUE_DEPTH

        if not can_accept:
            logger.warning(
                f"Queue backpressure triggered: {current_depth} tasks waiting "
                f"(max: {cls.MAX_QUEUE_DEPTH})"
            )

        return can_accept, current_depth


# ── Circuit Breaker State Monitoring ──────────────────────────


def get_circuit_breaker_states() -> dict[str, dict[str, Any]]:
    """
    Get current state of all circuit breakers.

    Returns:
        Dictionary mapping service names to their circuit breaker states
    """
    states = {}
    for name, breaker in _ALL_BREAKERS.items():
        states[name] = {
            "state": str(breaker.current_state),
            "fail_counter": breaker.fail_counter,
            "fail_max": breaker.fail_max,
            "reset_timeout": breaker.reset_timeout,
        }

    return states


def reset_circuit_breaker(service: str) -> bool:
    """
    Manually reset a circuit breaker (for testing or admin override).

    Args:
        service: Service name (openai, anthropic, elevenlabs, pexels, youtube,
                 runway, stability, kling, whisper)

    Returns:
        True if reset successful, False if service not found
    """
    breaker = _ALL_BREAKERS.get(service.lower())
    if not breaker:
        return False

    breaker.close()
    logger.info(f"Circuit breaker for {service} manually reset")

    return True
