"""
Circuit Breaker - Handles external API failures gracefully.

Implements circuit breaker pattern for:
- OpenAI (with fallback to Anthropic)
- Anthropic
- ElevenLabs
- Pexels (with fallback to placeholder)
- YouTube

Circuit Breaker States:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, requests immediately fail
- HALF_OPEN: Testing if service recovered
"""

from typing import Any, Callable
import asyncio
from functools import wraps

from pybreaker import CircuitBreaker, CircuitBreakerError
from loguru import logger

# ── Circuit Breakers for External Services ────────────────────

# OpenAI circuit breaker - fail after 5 failures in 60 seconds, recover after 120 seconds
openai_breaker = CircuitBreaker(
    fail_max=5,
    reset_timeout=120,
    name="OpenAI API"
)

# Anthropic circuit breaker
anthropic_breaker = CircuitBreaker(
    fail_max=5,
    reset_timeout=120,
    name="Anthropic API"
)

# ElevenLabs circuit breaker
elevenlabs_breaker = CircuitBreaker(
    fail_max=3,
    reset_timeout=60,
    name="ElevenLabs API"
)

# Pexels circuit breaker
pexels_breaker = CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="Pexels API"
)

# YouTube circuit breaker
youtube_breaker = CircuitBreaker(
    fail_max=3,
    reset_timeout=120,
    name="YouTube API"
)


# ── Circuit Breaker Decorators ─────────────────────────────────


def with_openai_breaker(fallback_to_anthropic: bool = True):
    """
    Decorator to wrap OpenAI calls with circuit breaker.

    If circuit is open and fallback is enabled, tries Anthropic instead.

    Args:
        fallback_to_anthropic: Whether to fallback to Anthropic on circuit open

    Returns:
        Decorated function
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                # Try OpenAI through circuit breaker
                return await openai_breaker.call_async(func, *args, **kwargs)
            except CircuitBreakerError as e:
                logger.warning(f"OpenAI circuit breaker open: {e}")

                if fallback_to_anthropic:
                    logger.info("Falling back to Anthropic API")
                    # Import here to avoid circular dependency
                    from app.services.llm_service import generate_script_anthropic
                    topic = kwargs.get("topic") or args[0] if args else None
                    if topic:
                        return await generate_script_anthropic(topic)

                raise
        return wrapper
    return decorator


def with_anthropic_breaker():
    """Decorator to wrap Anthropic calls with circuit breaker."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await anthropic_breaker.call_async(func, *args, **kwargs)
        return wrapper
    return decorator


def with_elevenlabs_breaker():
    """Decorator to wrap ElevenLabs calls with circuit breaker."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await elevenlabs_breaker.call_async(func, *args, **kwargs)
        return wrapper
    return decorator


def with_pexels_breaker(fallback_to_placeholder: bool = True):
    """
    Decorator to wrap Pexels calls with circuit breaker.

    If circuit is open and fallback is enabled, uses placeholder images.

    Args:
        fallback_to_placeholder: Whether to use placeholders on circuit open

    Returns:
        Decorated function
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await pexels_breaker.call_async(func, *args, **kwargs)
            except CircuitBreakerError as e:
                logger.warning(f"Pexels circuit breaker open: {e}")

                if fallback_to_placeholder:
                    logger.info("Falling back to placeholder videos")
                    # Use placeholder video (black screen with text)
                    from app.services.visual_service import create_placeholder_video
                    query = kwargs.get("query") or args[0] if args else "video content"
                    duration = kwargs.get("duration", 30)
                    return await create_placeholder_video(query, duration)

                raise
        return wrapper
    return decorator


def with_youtube_breaker():
    """Decorator to wrap YouTube API calls with circuit breaker."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await youtube_breaker.call_async(func, *args, **kwargs)
        return wrapper
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
        import asyncio
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
    breakers = {
        "openai": openai_breaker,
        "anthropic": anthropic_breaker,
        "elevenlabs": elevenlabs_breaker,
        "pexels": pexels_breaker,
        "youtube": youtube_breaker
    }

    states = {}
    for name, breaker in breakers.items():
        states[name] = {
            "state": str(breaker.current_state),
            "fail_counter": breaker.fail_counter,
            "fail_max": breaker.fail_max,
            "reset_timeout": breaker.reset_timeout,
            "last_failure": str(breaker.last_failure_time) if breaker.last_failure_time else None
        }

    return states


def reset_circuit_breaker(service: str) -> bool:
    """
    Manually reset a circuit breaker (for testing or admin override).

    Args:
        service: Service name (openai, anthropic, elevenlabs, pexels, youtube)

    Returns:
        True if reset successful, False if service not found
    """
    breakers = {
        "openai": openai_breaker,
        "anthropic": anthropic_breaker,
        "elevenlabs": elevenlabs_breaker,
        "pexels": pexels_breaker,
        "youtube": youtube_breaker
    }

    breaker = breakers.get(service.lower())
    if not breaker:
        return False

    breaker._state = breaker.closed_state
    breaker.fail_counter = 0
    logger.info(f"Circuit breaker for {service} manually reset")

    return True
