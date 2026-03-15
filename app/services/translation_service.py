"""
Translation Service — translates scripts and metadata to target languages using LLM.

ElevenLabs eleven_multilingual_v2 model supports 29 languages natively,
so only the text needs translation — no TTS model change required.
"""

from __future__ import annotations

from loguru import logger

from app.core.config import get_settings

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "zh": "Chinese",
    "it": "Italian",
    "ru": "Russian",
    "tr": "Turkish",
    "pl": "Polish",
    "nl": "Dutch",
}

# Language codes for Telegram --lang flag matching
LANGUAGE_ALIASES: dict[str, str] = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "hindi": "hi",
    "portuguese": "pt",
    "japanese": "ja",
    "korean": "ko",
    "arabic": "ar",
    "chinese": "zh",
    "italian": "it",
    "russian": "ru",
    "turkish": "tr",
    "polish": "pl",
    "dutch": "nl",
}


def resolve_language_code(lang_input: str) -> str | None:
    """Resolve a language input (code or name) to a standard code."""
    lang_lower = lang_input.lower().strip()
    if lang_lower in SUPPORTED_LANGUAGES:
        return lang_lower
    if lang_lower in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[lang_lower]
    return None


async def translate_script(
    script_text: str,
    target_language: str,
    provider: str = "openai",
) -> str:
    """
    Translate a video script to the target language using LLM.

    Preserves tone, beat structure, and timing. Does NOT add extra content.
    """
    if target_language == "en":
        return script_text

    lang_name = SUPPORTED_LANGUAGES.get(target_language, target_language)

    system_prompt = (
        f"You are a professional translator. Translate the following YouTube Shorts "
        f"script to {lang_name}. "
        "RULES:\n"
        "- Preserve the exact tone, energy, and dramatic structure\n"
        "- Keep the same number of sentences and beats\n"
        "- Maintain similar word count (scripts are timed to audio)\n"
        "- Do NOT add any commentary, notes, or explanations\n"
        "- Return ONLY the translated script text, nothing else"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": script_text},
    ]

    settings = get_settings()

    if provider == "openai":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.3,
        )
        translated = response.choices[0].message.content.strip()
    else:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": script_text}],
        )
        translated = response.content[0].text.strip()

    logger.info(
        "Script translated to {} — original_len={} translated_len={}",
        lang_name,
        len(script_text),
        len(translated),
    )
    return translated


async def translate_metadata(
    title: str,
    description: str,
    tags: list[str],
    target_language: str,
    provider: str = "openai",
) -> dict:
    """Translate YouTube metadata (title, description, tags)."""
    if target_language == "en":
        return {"title": title, "description": description, "tags": tags}

    lang_name = SUPPORTED_LANGUAGES.get(target_language, target_language)

    prompt = (
        f"Translate the following YouTube video metadata to {lang_name}.\n\n"
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Tags: {', '.join(tags)}\n\n"
        "Return in this exact format:\n"
        "TITLE: <translated title>\n"
        "DESCRIPTION: <translated description>\n"
        "TAGS: <comma-separated translated tags>"
    )

    settings = get_settings()

    if provider == "openai":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
    else:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

    # Parse response
    result = {"title": title, "description": description, "tags": tags}
    for line in raw.split("\n"):
        line = line.strip()
        if line.upper().startswith("TITLE:"):
            result["title"] = line[6:].strip()
        elif line.upper().startswith("DESCRIPTION:"):
            result["description"] = line[12:].strip()
        elif line.upper().startswith("TAGS:"):
            result["tags"] = [t.strip() for t in line[5:].split(",") if t.strip()]

    logger.info("Metadata translated to {}", lang_name)
    return result
