"""Content moderation using OpenAI Moderation API."""

from loguru import logger

from app.core.config import get_settings

settings = get_settings()


async def moderate_content(text: str) -> dict[str, any]:
    """
    Check content for policy violations using OpenAI Moderation API.

    The Moderation API checks for:
    - sexual: Sexual content
    - hate: Hate speech
    - harassment: Harassment or bullying
    - self-harm: Self-harm content
    - sexual/minors: Sexual content involving minors
    - hate/threatening: Hateful content that also includes violence
    - violence/graphic: Graphic violence
    - self-harm/intent: Content promoting self-harm
    - self-harm/instructions: Instructions for self-harm
    - harassment/threatening: Harassing content that includes threats
    - violence: Violent content

    Args:
        text: Text to moderate

    Returns:
        Dict with keys:
            - flagged: bool (True if any category violated)
            - categories: dict of category -> bool
            - category_scores: dict of category -> float (0-1 confidence)

    Raises:
        RuntimeError: If moderation API call fails (fail-open: logs error but doesn't block)

    Example:
        >>> result = await moderate_content("How to build a bomb")
        >>> if result['flagged']:
        ...     print(f"Violated categories: {[k for k,v in result['categories'].items() if v]}")
    """
    if not settings.openai_api_key:
        logger.warning("OpenAI API key not configured, skipping content moderation (fail-open)")
        return {
            "flagged": False,
            "categories": {},
            "category_scores": {},
        }

    try:
        from app.services.llm_service import _get_openai

        client = _get_openai()

        response = await client.moderations.create(input=text)
        result = response.results[0]

        flagged = result.flagged
        categories = result.categories.model_dump()
        category_scores = result.category_scores.model_dump()

        if flagged:
            violated_categories = [cat for cat, is_flagged in categories.items() if is_flagged]
            logger.warning(
                f"Content moderation flagged text. " f"Categories: {', '.join(violated_categories)}"
            )
            logger.debug(f"Flagged text: {text[:100]}...")

        return {
            "flagged": flagged,
            "categories": categories,
            "category_scores": category_scores,
        }

    except Exception as e:
        # Fail-open: Log error but don't block request
        # This prevents moderation API issues from breaking the service
        logger.error(f"Content moderation API error (fail-open): {e}")
        return {
            "flagged": False,
            "categories": {},
            "category_scores": {},
            "error": str(e),
        }


async def is_content_safe(text: str) -> tuple[bool, str]:
    """
    Check if content is safe (convenient wrapper around moderate_content).

    Args:
        text: Text to check

    Returns:
        Tuple of (is_safe: bool, reason: str)
        - is_safe: True if content passed moderation
        - reason: Empty string if safe, otherwise comma-separated violated categories

    Example:
        >>> is_safe, reason = await is_content_safe("Hello world")
        >>> if not is_safe:
        ...     print(f"Content blocked: {reason}")
    """
    result = await moderate_content(text)

    if result["flagged"]:
        violated = [
            cat.replace("/", " ").replace("-", " ").title()
            for cat, is_flagged in result["categories"].items()
            if is_flagged
        ]
        reason = ", ".join(violated)
        return False, reason

    return True, ""
