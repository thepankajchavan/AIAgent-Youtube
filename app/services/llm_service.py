"""
LLM Service — generates video scripts via OpenAI or Anthropic.

4-layer architecture:
  Layer 1: _call_openai / _call_anthropic
           Single API call with network-level retry (tenacity).
  Layer 2: _parse_and_validate
           Extract JSON, validate required keys, ensure scenes exist.
  Layer 3: _generate_with_quality_retry
           Quality validation loop — retries with corrective LLM feedback.
  Layer 4: generate_script (public API)
           Content moderation, sanitization, provider fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum

import httpx
import openai
from anthropic import AsyncAnthropic
from loguru import logger
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.cache import QueryCache
from app.core.circuit_breaker import with_anthropic_breaker, with_openai_breaker
from app.core.config import get_settings
from app.security.content_moderation import is_content_safe
from app.security.sanitizers import sanitize_topic

settings = get_settings()

# ── Constants ─────────────────────────────────────────────────
MAX_QUALITY_RETRIES = 2  # Corrective feedback retries (on top of network retries)

# ── Clients (lazy singletons) ────────────────────────────────
_openai_client: AsyncOpenAI | None = None
_anthropic_client: AsyncAnthropic | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


# ── Provider enum ────────────────────────────────────────────
class LLMProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# ── Prompt templates ─────────────────────────────────────────
SHORT_SYSTEM_PROMPT = """\
You are a viral YouTube Shorts scriptwriter for faceless channels. You write scroll-stopping narrations over stock footage.

CONTENT NICHES: fascinating facts, motivation, science, technology, space, history, mysteries, psychology.

SCRIPT RULES:
1. Length: STRICTLY 80-100 words. Count carefully. This produces ~30-40 seconds of TTS audio.
2. Structure (5-6 visual beats, each separated by a blank line):
   - HOOK (1 sentence): A shocking claim, wild question, or jaw-dropping fact that stops the scroll instantly.
   - BUILD 1 (1-2 sentences): Expand with a vivid, concrete detail that pulls the viewer deeper.
   - BUILD 2 (1-2 sentences): Add another layer — a contrast, escalation, or surprising angle.
   - BUILD 3 (1-2 sentences): Deepen with a twist, comparison, or escalation.
   - CLIMAX (1 sentence): The biggest reveal, twist, or mind-blowing conclusion.
   - KICKER (optional, 1 sentence): A short punchy closer that leaves the viewer thinking.
3. Do NOT include any "like", "subscribe", "follow", or CTA text — the video ends with content only.
4. Short, punchy sentences. Conversational and confident — as if telling a friend something incredible.
5. NEVER use markdown formatting (no **, *, #, __). Plain text only.
6. Open with "you" or a direct address to make it personal. Example: "You won't believe..." or "Right now, there's a..."
7. Each beat should correspond to a concrete, filmable scene found as stock footage:
   nature, cities, people, technology, space, underwater, animals, historical imagery, time-lapses, aerial shots, etc.

SEARCH KEYWORDS:
- For each scene/beat, provide 2-3 specific Pexels stock video search terms.
- Be specific and visual: "aerial city skyline night lights" beats "city". "close up human eye iris" beats "eye".
- Think: what would a viewer SEE on screen while hearing this narration?

VISUAL HINT:
- For each scene, provide a short 10-20 word cinematic description of what the viewer should SEE.
- Include camera angle (aerial, close-up, wide), lighting (golden hour, neon, overcast), and dominant colors.
- This guides AI video generation. Example: "Wide aerial shot of frozen tundra, overcast sky, muted blue-grey palette"

TAGS & SEO (critical for discoverability):
- Provide 10-15 YouTube tags: mix broad viral tags (e.g. "facts", "didyouknow", "mindblown") with niche-specific tags for the topic.
- Provide 5-8 hashtags WITH # symbol. IMPORTANT: If trending hashtags are provided below, you MUST include at least 3 of them in your hashtags list — these are currently trending on YouTube and will boost discoverability.
- Pick the best YouTube category for this content from: education, science, entertainment, howto, people, comedy, news.
- Write a 2-3 sentence SEO description that includes trending keywords naturally. End with a curiosity hook like "Wait for the ending..." or "The last fact will shock you."

TITLE RULES (optimize for clicks):
- Under 60 chars, curiosity-driven
- Use one of these proven viral patterns:
  * Number + Shocking Claim: "3 Things About Space That Will Terrify You"
  * "This X..." opener: "This 2000-Year-Old Battery Still Works"
  * Contrast/Paradox: "The Quietest Room on Earth Drives You Insane"
  * Personal "You": "You've Been Lied To About Dinosaurs"
- Include 1 trending keyword in the title if it fits naturally

8. MOOD: Provide a single mood tag for background music selection.
   Options: energetic, calm, dramatic, mysterious, uplifting, dark, happy, sad, epic, chill.

Return ONLY a JSON object — no markdown fences, no explanation:
{
  "title": "Catchy YouTube title (under 60 chars, curiosity-driven, no clickbait ALL CAPS)",
  "script": "Full narration text with blank lines between beats",
  "scenes": [
    {"narration": "Hook text...", "search_keywords": ["specific keyword 1", "specific keyword 2"], "visual_hint": "Wide establishing shot, dramatic lighting, cool blue tones"},
    {"narration": "Build 1 text...", "search_keywords": ["specific keyword 1", "specific keyword 2"], "visual_hint": "Close-up detail shot, warm amber light, shallow depth of field"},
    ...
  ],
  "tags": ["tag1", "tag2", ...] (10-15 YouTube tags, no # symbol),
  "hashtags": ["#Shorts", "#Facts", "#Science", "#Viral", "#MindBlown"],
  "category": "education",
  "description": "2-3 sentence SEO-optimized YouTube description with keywords",
  "mood": "uplifting"
}

## EXAMPLE SCRIPTS (study these for tone, structure, and quality):

### Example 1 — Science
Topic: "The deepest hole ever dug"
```json
{
  "title": "Humans Dug So Deep They Heard Screams from Hell",
  "script": "You're standing in Siberia, staring at a rusty metal cap bolted to the ground. Beneath it lies the deepest hole humans ever dug — 12,262 meters straight down.\n\nIt took Soviet scientists 19 years to drill it. They expected solid rock. Instead, they found 180-degree temperatures and ancient microscopic fossils 6 kilometers underground.\n\nThe rock at that depth behaves like plastic — it flows and seals the drill hole shut behind you.\n\nThey had to stop. Not because of mythical screams, but because the Earth itself was fighting back. And we barely scratched 0.2% of the way to the core.",
  "scenes": [
    {"narration": "You're standing in Siberia, staring at a rusty metal cap bolted to the ground. Beneath it lies the deepest hole humans ever dug — 12,262 meters straight down.", "search_keywords": ["aerial siberia tundra landscape", "rusty metal cap ground industrial"], "visual_hint": "Wide aerial shot of frozen Siberian tundra, overcast sky, muted blue-grey palette"},
    {"narration": "It took Soviet scientists 19 years to drill it. They expected solid rock. Instead, they found 180-degree temperatures and ancient microscopic fossils 6 kilometers underground.", "search_keywords": ["drilling rig industrial close up", "microscopic fossils science laboratory"], "visual_hint": "Close-up of industrial drilling equipment, warm orange sparks, gritty textures"},
    {"narration": "The rock at that depth behaves like plastic — it flows and seals the drill hole shut behind you.", "search_keywords": ["molten rock flowing lava texture", "underground tunnel deep earth"], "visual_hint": "Macro shot of molten rock flowing, deep red-orange glow, dark surroundings"},
    {"narration": "They had to stop. Not because of mythical screams, but because the Earth itself was fighting back.", "search_keywords": ["earth crust layers geological cross section", "drilling equipment abandoned industrial"], "visual_hint": "Low-angle shot of abandoned equipment, dramatic shadows, desaturated cold tones"},
    {"narration": "And we barely scratched 0.2% of the way to the core.", "search_keywords": ["earth core animation planet interior", "space view earth rotating"], "visual_hint": "Pull-out from Earth's surface to space, deep blacks with glowing planetary core"}
  ],
  "tags": ["science", "geology", "kolaboerhole", "deepesthole", "earthscience", "facts", "didyouknow", "mindblown", "soviet", "drilling", "geology facts"],
  "hashtags": ["#Shorts", "#Science", "#Facts", "#MindBlown", "#Geology"],
  "category": "science",
  "description": "The Kola Superdeep Borehole is the deepest artificial point on Earth at 12,262 meters. Soviet scientists drilled for 19 years and discovered things that changed our understanding of the planet.",
  "mood": "mysterious"
}
```

### Example 2 — History
Topic: "Cleopatra and the pyramids"
```json
{
  "title": "Cleopatra Lived Closer to WiFi Than to the Pyramids",
  "script": "You think Cleopatra saw the pyramids being built. She didn't — not even close.\n\nThe Great Pyramid was already 2,500 years old when Cleopatra was born. That's the same gap between us and ancient Rome.\n\nShe lived closer in time to the Moon landing than to the construction of the pyramids she's famous for standing beside.\n\nCleopatra spoke nine languages, commanded a navy, and ruled Egypt for 21 years. She wasn't just a queen — she was the last pharaoh of a civilization already ancient in her own time.",
  "scenes": [
    {"narration": "You think Cleopatra saw the pyramids being built. She didn't — not even close.", "search_keywords": ["pyramids giza sunset dramatic", "ancient egypt aerial desert"], "visual_hint": "Wide establishing shot of pyramids at golden hour, warm amber tones, dramatic sky"},
    {"narration": "The Great Pyramid was already 2,500 years old when Cleopatra was born. That's the same gap between us and ancient Rome.", "search_keywords": ["ancient roman colosseum ruins", "timeline history animation"], "visual_hint": "Dolly shot through ancient Roman ruins, warm sunlight, cinematic depth of field"},
    {"narration": "She lived closer in time to the Moon landing than to the construction of the pyramids she's famous for standing beside.", "search_keywords": ["moon landing apollo astronaut", "pyramid sphinx close up"], "visual_hint": "Split-feel contrast: moonscape silver-white transitioning to desert gold tones"},
    {"narration": "Cleopatra spoke nine languages, commanded a navy, and ruled Egypt for 21 years.", "search_keywords": ["ancient ship sailing mediterranean", "egyptian queen statue art"], "visual_hint": "Tracking shot of ancient ship on turquoise water, golden light, epic scale"},
    {"narration": "She wasn't just a queen — she was the last pharaoh of a civilization already ancient in her own time.", "search_keywords": ["egyptian hieroglyphics temple wall", "sunset nile river egypt"], "visual_hint": "Slow push-in on hieroglyphics in temple, warm torch-lit amber, mysterious shadows"}
  ],
  "tags": ["history", "cleopatra", "pyramids", "ancientegypt", "historyfacts", "didyouknow", "mindblown", "pharaoh", "education", "worldhistory"],
  "hashtags": ["#Shorts", "#History", "#Facts", "#Cleopatra", "#MindBlown"],
  "category": "education",
  "description": "Cleopatra lived closer to the invention of WiFi than to the building of the Great Pyramid. The timeline of ancient Egypt is far more mind-bending than most people realize.",
  "mood": "dramatic"
}
```

### Example 3 — Motivation
Topic: "Why most people quit too early"
```json
{
  "title": "You're Probably 2 Feet from Gold Right Now",
  "script": "You've been grinding for months and you see zero results. So you quit. Everyone does.\n\nDuring the Gold Rush, a man named Darby drilled for weeks and found nothing. He sold his equipment for scrap. The buyer hired a geologist — and struck gold three feet from where Darby stopped.\n\nThree feet. That's all that separated failure from a fortune.\n\nMost people don't fail because they lack talent. They fail because they stop digging one layer before the breakthrough. Your gold is closer than you think.",
  "scenes": [
    {"narration": "You've been grinding for months and you see zero results. So you quit. Everyone does.", "search_keywords": ["tired person working late laptop", "frustrated man office stress"], "visual_hint": "Close-up of tired face lit by laptop screen, dark room, cool blue-white light"},
    {"narration": "During the Gold Rush, a man named Darby drilled for weeks and found nothing. He sold his equipment for scrap.", "search_keywords": ["gold mining vintage historical", "abandoned mine equipment rusty"], "visual_hint": "Wide shot of dusty mining landscape, sepia-warm vintage tones, overcast sky"},
    {"narration": "The buyer hired a geologist — and struck gold three feet from where Darby stopped.", "search_keywords": ["gold nugget sparkling close up", "mining underground tunnel discovery"], "visual_hint": "Extreme close-up of gold glinting in rock, warm golden light, shallow depth of field"},
    {"narration": "Three feet. That's all that separated failure from a fortune.", "search_keywords": ["measuring tape close up detail", "golden light rays breakthrough"], "visual_hint": "Dramatic low-angle light breaking through darkness, golden rays, high contrast"},
    {"narration": "Most people don't fail because they lack talent. They fail because they stop digging one layer before the breakthrough. Your gold is closer than you think.", "search_keywords": ["person climbing mountain summit sunrise", "light end of tunnel hope"], "visual_hint": "Silhouette climbing toward sunrise summit, warm golden-orange horizon, epic wide shot"}
  ],
  "tags": ["motivation", "success", "mindset", "nevergiveup", "goldrush", "inspiration", "grind", "entrepreneur", "discipline", "breakthrough"],
  "hashtags": ["#Shorts", "#Motivation", "#NeverGiveUp", "#Mindset", "#Success"],
  "category": "education",
  "description": "The story of R.U. Darby and the Gold Rush teaches one of the most powerful lessons about persistence. Most people quit just before their biggest breakthrough.",
  "mood": "uplifting"
}
```\
"""

LONG_SYSTEM_PROMPT = (
    "You are an expert YouTube long-form scriptwriter. "
    "Write a script that is 5-10 minutes when spoken aloud. "
    "Structure it with a hook, intro, 3-5 key sections, and a strong outro. "
    "Return ONLY a JSON object with keys: "
    '"title", "script", '
    '"tags" (list of 12-18 viral + niche tags, no # symbol), '
    '"hashtags" (list of 5-8 hashtags WITH # for the description), '
    '"category" (one of: education, science, entertainment, howto, people, comedy, news), '
    '"description" (2-3 SEO-optimized sentences with keywords), '
    '"sections" (list of {"heading": str, "content": str}).'
)


def _system_prompt(video_format: str, target_duration: int | None = None) -> str:
    if video_format != "short":
        return LONG_SYSTEM_PROMPT
    if target_duration:
        # ~2.5 words/sec at ElevenLabs TTS speed
        target_words = int(target_duration * 2.5)
        word_min = max(30, target_words - 10)
        word_max = target_words + 10
        return SHORT_SYSTEM_PROMPT.replace(
            "STRICTLY 80-100 words. Count carefully. This produces ~30-40 seconds of TTS audio.",
            f"STRICTLY {word_min}-{word_max} words. Count carefully. "
            f"This produces ~{target_duration} seconds of TTS audio.",
        )
    return SHORT_SYSTEM_PROMPT


# ── Niche Tone Templates ─────────────────────────────────────────

NICHE_TONE_TEMPLATES: dict[str, str] = {
    "science": (
        "TONE: Curious and awe-inspiring. Use precise scientific language but keep it accessible. "
        "Lead with a mind-blowing fact. Compare scale to everyday objects. "
        "End with an implication that makes the viewer rethink something."
    ),
    "history": (
        "TONE: Narrative and cinematic. You are telling a story, not listing facts. "
        "Set the scene with time and place. Use present tense for immediacy. "
        "End with a twist or connection to today."
    ),
    "technology": (
        "TONE: Forward-looking and slightly breathless. Emphasize what's NEW and WHY it matters. "
        "One concrete example beats three abstract claims. "
        "End with what this means for the viewer personally."
    ),
    "motivation": (
        "TONE: Raw and personal. Use second-person ('you') throughout. "
        "Start with a painful truth, then flip it. Short punchy sentences. "
        "End with a single actionable takeaway."
    ),
    "psychology": (
        "TONE: Intriguing and slightly unsettling. Name the cognitive bias or phenomenon. "
        "Give a relatable example the viewer has experienced. "
        "End with 'and you've been doing it your whole life' energy."
    ),
    "space": (
        "TONE: Grand and humbling. Use extreme numbers and distances. "
        "Compare cosmic scales to human experience. "
        "End with existential wonder, not fear."
    ),
    "entertainment": (
        "TONE: Gossipy and fast. Use insider language. "
        "Reveal something most fans don't know. "
        "End with a cliffhanger or shocking detail."
    ),
}

NICHE_KEYWORDS: dict[str, list[str]] = {
    "science": ["science", "physics", "chemistry", "biology", "experiment", "research", "study", "atom", "molecule", "dna"],
    "history": ["history", "ancient", "war", "empire", "century", "civilization", "king", "queen", "medieval", "dynasty"],
    "technology": ["tech", "ai", "robot", "computer", "software", "app", "digital", "algorithm", "internet", "cyber"],
    "motivation": ["motivation", "success", "mindset", "habit", "discipline", "goal", "productivity", "hustle", "grind"],
    "psychology": ["psychology", "brain", "mind", "behavior", "cognitive", "bias", "mental", "emotion", "anxiety", "therapy"],
    "space": ["space", "planet", "star", "galaxy", "universe", "nasa", "moon", "mars", "asteroid", "black hole", "cosmos"],
    "entertainment": ["movie", "film", "celebrity", "actor", "music", "game", "netflix", "show", "hollywood", "anime"],
}


def _detect_niche(topic: str) -> str | None:
    """Detect content niche from topic string via word-boundary keyword matching."""
    topic_lower = topic.lower()
    for niche, keywords in NICHE_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(kw)}\b", topic_lower) for kw in keywords):
            return niche
    return None


def _user_prompt(
    topic: str,
    video_format: str,
    search_context: str | None = None,
    target_duration: int | None = None,
    trending_context: str | None = None,
) -> str:
    context_block = ""
    if search_context:
        context_block = (
            "\n\n--- REAL-TIME RESEARCH ---\n"
            "Use the following recent information to make the script accurate, "
            "timely, and factual. Reference specific details, names, dates, "
            "and statistics from this research:\n\n"
            f"{search_context}\n"
            "--- END RESEARCH ---\n\n"
        )

    trending_block = ""
    if trending_context:
        trending_block = f"\n{trending_context}"

    if video_format == "short":
        if target_duration:
            target_words = int(target_duration * 2.5)
            word_min = max(30, target_words - 10)
            word_max = target_words + 10
            word_reminder = f"{word_min}-{word_max} words"
        else:
            word_reminder = "80-100 words"

        # Niche tone template injection
        niche_block = ""
        if getattr(settings, "niche_templates_enabled", True):
            niche = _detect_niche(topic)
            if niche and niche in NICHE_TONE_TEMPLATES:
                niche_block = f"\n\n{NICHE_TONE_TEMPLATES[niche]}"
                logger.debug("Niche template injected: {}", niche)

        return (
            f"Write a viral YouTube Short script about: {topic}\n"
            f"{context_block}"
            "Make it fascinating, dramatic, and impossible to scroll past. "
            f"Remember: {word_reminder}, 5-6 visual beats, and specific "
            "stock footage search keywords for each scene."
            f"{niche_block}"
            f"{trending_block}"
        )
    return f"Write a detailed YouTube video script about: {topic}{context_block}{trending_block}"


# ═════════════════════════════════════════════════════════════
# LAYER 1 — Single API call with network-level retry
# ═════════════════════════════════════════════════════════════

# Retry on: network errors, rate limits, timeouts, server errors
_RETRYABLE_ERRORS = (
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.ConnectError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.InternalServerError,
)

_network_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=3, max=90),
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    before_sleep=lambda rs: logger.warning(
        "LLM network retry — attempt {} failed ({}), retrying in {:.1f}s …",
        rs.attempt_number,
        type(rs.outcome.exception()).__name__ if rs.outcome else "unknown",
        rs.next_action.sleep,
    ),
)


@with_openai_breaker(fallback_to_anthropic=False)
@_network_retry
async def _call_openai(messages: list[dict]) -> str:
    """Single OpenAI API call. Returns raw response text."""
    client = _get_openai()
    logger.debug("OpenAI API call — model={} messages={}", settings.openai_model, len(messages))

    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=messages,
        temperature=0.7,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    logger.debug("OpenAI response — {} chars", len(raw))
    return raw


@with_anthropic_breaker()
@_network_retry
async def _call_anthropic(messages: list[dict], system: str) -> str:
    """Single Anthropic API call. Returns raw response text."""
    client = _get_anthropic()
    logger.debug(
        "Anthropic API call — model={} messages={}", settings.anthropic_model, len(messages)
    )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        temperature=0.7,
        system=system,
        messages=messages,
    )

    raw = response.content[0].text
    logger.debug("Anthropic response — {} chars", len(raw))
    return raw


# ═════════════════════════════════════════════════════════════
# LAYER 2 — JSON extraction and structural validation
# ═════════════════════════════════════════════════════════════

def _extract_json(text: str) -> dict:
    """
    Robustly extract JSON from LLM response.

    Handles: raw JSON, markdown-fenced JSON, JSON embedded in prose,
    trailing commas, and other common LLM quirks.
    """
    text = text.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1:] if first_nl != -1 else text[3:]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    text = text.strip()

    # Attempt 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: find outermost { ... } in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Attempt 3: fix trailing commas (common LLM error)
            cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("No valid JSON found in LLM response", text[:200], 0)


def _validate_required_keys(result: dict) -> None:
    """Validate that all required keys exist with correct types."""
    for key in ("title", "script", "tags", "description"):
        if key not in result:
            raise ValueError(f"LLM response missing required key: '{key}'")

    if not isinstance(result["tags"], list):
        raise ValueError("LLM response 'tags' must be a list")
    if not isinstance(result["script"], str) or not result["script"].strip():
        raise ValueError("LLM response 'script' must be a non-empty string")


def _ensure_scenes(result: dict) -> None:
    """Ensure result has a valid scenes array, building from script if needed."""
    scenes_valid = False

    if "scenes" in result and isinstance(result["scenes"], list) and len(result["scenes"]) >= 2:
        # Validate each scene
        all_ok = True
        for i, scene in enumerate(result["scenes"]):
            if not isinstance(scene, dict):
                all_ok = False
                break
            if "narration" not in scene:
                scene["narration"] = ""
            if "search_keywords" not in scene or not isinstance(scene["search_keywords"], list):
                scene["search_keywords"] = []
            if "visual_hint" not in scene or not scene.get("visual_hint"):
                scene["visual_hint"] = scene.get("narration", "")
        scenes_valid = all_ok

    if not scenes_valid:
        # Rebuild scenes from script paragraphs + tags
        paragraphs = [p.strip() for p in result["script"].split("\n\n") if p.strip()]
        tags = result.get("tags", [])
        result["scenes"] = [
            {
                "narration": para,
                "search_keywords": [tags[i]] if i < len(tags) else [],
            }
            for i, para in enumerate(paragraphs)
        ]
        logger.warning(
            "Rebuilt {} scenes from script paragraphs (LLM didn't return valid scenes)",
            len(result["scenes"]),
        )


def _strip_markdown(result: dict) -> None:
    """Remove any markdown formatting from the script text."""
    s = result["script"]
    s = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", s)
    s = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", s)
    s = re.sub(r"^#+\s*", "", s, flags=re.MULTILINE)
    result["script"] = s


def _parse_and_validate(raw_text: str) -> dict:
    """Layer 2: extract JSON, validate keys, ensure scenes, clean markdown."""
    result = _extract_json(raw_text)
    _validate_required_keys(result)
    _ensure_scenes(result)
    _strip_markdown(result)
    return result


# ═════════════════════════════════════════════════════════════
# LAYER 3 — Quality validation with corrective feedback retry
# ═════════════════════════════════════════════════════════════

_CTA_PATTERN = re.compile(
    r"\b(subscribe|like this video|follow me|comment below|share this|"
    r"hit the bell|turn on notifications|smash that|let me know)\b",
    re.IGNORECASE,
)


def _validate_script_quality(result: dict, video_format: str) -> list[str]:
    """
    Validate script quality. Returns list of issues (empty = perfect).

    Checks: word count, scene count, search keywords, CTA text, markdown.
    """
    issues: list[str] = []
    script = result.get("script", "")
    word_count = len(script.split())

    if video_format == "short":
        if word_count < 60:
            issues.append(f"Script too short: {word_count} words (need 80-100)")
        elif word_count > 130:
            issues.append(f"Script too long: {word_count} words (need 80-100)")

        scenes = result.get("scenes", [])
        if len(scenes) < 4:
            issues.append(f"Only {len(scenes)} scenes (need 5-6)")
        elif len(scenes) > 8:
            issues.append(f"Too many scenes: {len(scenes)} (need 5-6)")

        # Check scenes have search keywords
        empty_kw = sum(1 for s in scenes if not s.get("search_keywords"))
        if empty_kw > 0:
            issues.append(f"{empty_kw} scene(s) missing search keywords")

    # CTA detection
    cta_match = _CTA_PATTERN.search(script)
    if cta_match:
        issues.append(f"Contains CTA text: '{cta_match.group()}'")

    # Markdown detection
    if re.search(r"\*\*[^*]+\*\*|__[^_]+__", script):
        issues.append("Contains markdown formatting")

    # Title length check
    title = result.get("title", "")
    if len(title) > 70:
        issues.append(f"Title too long: {len(title)} chars (max 60)")

    # Hook strength scoring (only for shorts)
    if video_format == "short" and script:
        try:
            from app.services.hook_scorer_service import score_hook
            hook_result = score_hook(script)
            hook_min = getattr(settings, "hook_min_score", 0.3)
            if hook_result.total < hook_min:
                issues.append(
                    f"Weak hook (score {hook_result.total:.2f}/{hook_min}). "
                    f"{hook_result.feedback}"
                )
        except Exception:
            pass  # Don't fail validation if hook scoring breaks

    return issues


async def _generate_with_quality_retry(
    topic: str,
    video_format: str,
    provider: LLMProvider,
    search_context: str | None = None,
    target_duration: int | None = None,
    trending_context: str | None = None,
) -> dict:
    """
    Layer 3: Generate script with quality validation and corrective feedback.

    On quality issues, sends the LLM's previous output back with specific
    corrections, giving it a chance to fix the problems (multi-turn).

    Up to MAX_QUALITY_RETRIES corrective retries.
    """
    system = _system_prompt(video_format, target_duration)
    user_msg = _user_prompt(topic, video_format, search_context, target_duration, trending_context)
    messages: list[dict] = [{"role": "user", "content": user_msg}]

    best_result: dict | None = None
    best_issue_count = 999

    for attempt in range(MAX_QUALITY_RETRIES + 1):
        try:
            # Call the appropriate provider
            if provider == LLMProvider.OPENAI:
                raw = await _call_openai(
                    [{"role": "system", "content": system}] + messages
                )
            else:
                raw = await _call_anthropic(messages, system)

            # Parse and validate structure
            result = _parse_and_validate(raw)

            # Quality check
            issues = _validate_script_quality(result, video_format)
            issue_count = len(issues)

            # Track the best result we've seen
            if issue_count < best_issue_count:
                best_result = result
                best_issue_count = issue_count

            if not issues:
                word_count = len(result["script"].split())
                logger.info(
                    "Script quality PERFECT — {} words, {} scenes, attempt {}/{}",
                    word_count,
                    len(result.get("scenes", [])),
                    attempt + 1,
                    MAX_QUALITY_RETRIES + 1,
                )
                return result

            # Quality issues found — retry with corrective feedback
            if attempt < MAX_QUALITY_RETRIES:
                logger.warning(
                    "Script quality issues (attempt {}/{}): {}",
                    attempt + 1,
                    MAX_QUALITY_RETRIES + 1,
                    issues,
                )

                # Build corrective multi-turn conversation
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The script has these quality issues that MUST be fixed:\n"
                            + "\n".join(f"- {issue}" for issue in issues)
                            + "\n\nPlease regenerate the COMPLETE corrected JSON. "
                            "Fix every issue listed above. Return ONLY the JSON."
                        ),
                    }
                )
            else:
                logger.warning(
                    "Accepting script with remaining issues after {} attempts: {}",
                    MAX_QUALITY_RETRIES + 1,
                    issues,
                )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(
                "Script parse/validation error (attempt {}/{}): {}",
                attempt + 1,
                MAX_QUALITY_RETRIES + 1,
                str(e)[:150],
            )
            if attempt < MAX_QUALITY_RETRIES:
                # Reset conversation with corrective instructions
                messages = [
                    {
                        "role": "user",
                        "content": (
                            f"{user_msg}\n\n"
                            f"Your previous response had this error: {e}\n\n"
                            "CRITICAL: Return ONLY valid JSON with ALL required keys: "
                            "title, script, scenes, tags, description. "
                            "No markdown fences, no explanation — ONLY the JSON object."
                        ),
                    }
                ]
            elif best_result is not None:
                return best_result
            else:
                raise

    # Return the best result we got
    if best_result is not None:
        return best_result

    raise RuntimeError("Script generation failed: no valid result after all attempts")


# ═════════════════════════════════════════════════════════════
# LAYER 4 — Public API with provider fallback
# ═════════════════════════════════════════════════════════════

async def generate_script(
    topic: str,
    video_format: str = "short",
    provider: LLMProvider = LLMProvider.OPENAI,
    search_context: str | None = None,
    target_duration: int | None = None,
    trending_context: str | None = None,
) -> dict:
    """
    Generate a video script for the given topic.

    Full pipeline:
      1. Content moderation check
      2. Input sanitization (prompt injection prevention)
      3. Script generation with quality retry loop
      4. Automatic provider fallback if primary fails

    Args:
        target_duration: Target video duration in seconds. Adjusts word count
            in the LLM prompt (~2.5 words/sec TTS rate).
        trending_context: Formatted trending data block to inject into prompt.

    Returns a dict with: title, script, scenes, tags, description.

    Raises:
        ValueError: If topic is invalid or violates content policy.
    """
    logger.info(
        "Generating {} script — provider={} topic='{}'",
        video_format,
        provider.value,
        topic[:50] + "..." if len(topic) > 50 else topic,
    )

    # 0. Check cache (skip for web-search-augmented scripts — time-sensitive)
    cache_key = None
    if search_context is None:
        topic_hash = hashlib.md5(f"{topic}:{video_format}".encode()).hexdigest()
        cache_key = f"script:{topic_hash}"
        cached = await QueryCache.get(cache_key)
        if cached:
            logger.info("Script cache HIT — topic='{}'", topic[:50])
            return json.loads(cached)

    # 1. Content moderation check
    is_safe, violation_reason = await is_content_safe(topic)
    if not is_safe:
        logger.warning(f"Content moderation blocked topic: {violation_reason}")
        raise ValueError(
            f"Topic violates content policy ({violation_reason}). "
            "Please provide a different topic."
        )

    # 2. Sanitize topic to prevent prompt injection
    sanitized_topic = sanitize_topic(topic)

    # 3. Generate with primary provider + quality retry
    try:
        result = await _generate_with_quality_retry(
            sanitized_topic, video_format, provider, search_context, target_duration, trending_context
        )
        logger.info(
            "Script generated — provider={} title='{}' words={} scenes={}",
            provider.value,
            result["title"],
            len(result["script"].split()),
            len(result.get("scenes", [])),
        )
        # Cache result for 7 days (only non-search-augmented)
        if cache_key:
            await QueryCache.set(cache_key, json.dumps(result), ttl=7 * 24 * 3600)
        return result

    except Exception as primary_err:
        # 4. Provider fallback — try the other provider
        fallback = (
            LLMProvider.ANTHROPIC if provider == LLMProvider.OPENAI else LLMProvider.OPENAI
        )
        logger.warning(
            "Primary provider {} failed ({}), falling back to {} …",
            provider.value,
            type(primary_err).__name__,
            fallback.value,
        )

        try:
            result = await _generate_with_quality_retry(
                sanitized_topic, video_format, fallback, search_context, target_duration, trending_context
            )
            logger.info(
                "Script generated via FALLBACK — provider={} title='{}' words={} scenes={}",
                fallback.value,
                result["title"],
                len(result["script"].split()),
                len(result.get("scenes", [])),
            )
            if cache_key:
                await QueryCache.set(cache_key, json.dumps(result), ttl=7 * 24 * 3600)
            return result

        except Exception as fallback_err:
            logger.error(
                "Both providers failed — primary={} ({}) fallback={} ({})",
                provider.value,
                primary_err,
                fallback.value,
                fallback_err,
            )
            # Raise the original error as it's more relevant
            raise primary_err from fallback_err
