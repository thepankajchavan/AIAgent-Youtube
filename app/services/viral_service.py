"""
Viral Optimizer — connects trending data to LLM prompt for viral hashtags,
SEO-optimized titles, and trending keywords.

Gathers signals from:
  1. TrendingTopic DB records (related_queries, velocity, viral_potential)
  2. YouTube autocomplete API (free, no key needed)
  3. Hardcoded niche hashtag pools (proven high-performers)
"""

from __future__ import annotations

import json
import re

import httpx
from loguru import logger

from app.core.config import get_settings

# ── Niche Hashtag Pools (YouTube best practices) ───────────────
NICHE_HASHTAG_POOLS: dict[str, list[str]] = {
    "science": [
        "#ScienceFacts", "#DidYouKnow", "#STEM", "#ScienceShorts",
        "#ScienceExplained", "#MindBlown", "#Biology", "#Physics",
    ],
    "technology": [
        "#TechNews", "#AI", "#FutureTech", "#TechShorts",
        "#Innovation", "#Coding", "#MachineLearning", "#TechFacts",
    ],
    "history": [
        "#HistoryFacts", "#TodayILearned", "#HistoryShorts",
        "#AncientHistory", "#HistoryNerd", "#WorldHistory",
    ],
    "motivation": [
        "#Motivation", "#Mindset", "#GrindMode", "#SuccessShorts",
        "#NeverGiveUp", "#Discipline", "#SelfImprovement",
    ],
    "psychology": [
        "#Psychology", "#HumanBehavior", "#MindBlown", "#BrainFacts",
        "#CognitiveBias", "#PsychologyFacts", "#MentalHealth",
    ],
    "space": [
        "#Space", "#NASA", "#Universe", "#SpaceFacts",
        "#Astronomy", "#Cosmos", "#SpaceShorts", "#Galaxy",
    ],
    "entertainment": [
        "#Entertainment", "#MovieFacts", "#Celebrity", "#Viral",
        "#PopCulture", "#Netflix", "#Hollywood", "#Trending",
    ],
}

# ── Generic viral hashtags (used when no niche detected) ──────
GENERIC_VIRAL_HASHTAGS = [
    "#Shorts", "#Viral", "#Facts", "#MindBlown",
    "#DidYouKnow", "#Trending", "#FYP",
]


class ViralOptimizer:
    """Gathers viral signals and formats them for LLM injection."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def get_trending_context(
        self, topic: str, niche: str | None = None
    ) -> dict:
        """Gather all viral signals for a topic.

        Returns dict with:
            trending_hashtags: list[str]
            trending_keywords: list[str]
            velocity: str (rising/peaked/declining)
            viral_potential: float (0-1)
            niche_hashtags: list[str]
        """
        trending_hashtags: list[str] = []
        trending_keywords: list[str] = []
        velocity = "rising"
        viral_potential = 0.0

        # 1. Get signals from DB trends
        try:
            db_signals = await self._get_signals_from_trends(topic, niche)
            trending_hashtags.extend(db_signals.get("hashtags", []))
            trending_keywords.extend(db_signals.get("keywords", []))
            velocity = db_signals.get("velocity", "rising")
            viral_potential = db_signals.get("viral_potential", 0.0)
        except Exception as exc:
            logger.warning("DB trend signals failed: {}", exc)

        # 2. Get YouTube autocomplete suggestions
        try:
            autocomplete = await self._get_youtube_autocomplete(topic)
            trending_keywords.extend(autocomplete)
        except Exception as exc:
            logger.warning("YouTube autocomplete failed: {}", exc)

        # 3. Get niche hashtag pool
        niche_hashtags = self.get_niche_hashtag_pool(niche)

        # Deduplicate keywords
        seen: set[str] = set()
        unique_keywords: list[str] = []
        for kw in trending_keywords:
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in seen:
                seen.add(kw_lower)
                unique_keywords.append(kw)

        # Deduplicate hashtags
        seen_tags: set[str] = set()
        unique_hashtags: list[str] = []
        for tag in trending_hashtags:
            tag_lower = tag.lower()
            if tag_lower not in seen_tags:
                seen_tags.add(tag_lower)
                unique_hashtags.append(tag)

        return {
            "trending_hashtags": unique_hashtags[:10],
            "trending_keywords": unique_keywords[:10],
            "velocity": velocity,
            "viral_potential": viral_potential,
            "niche_hashtags": niche_hashtags,
        }

    async def _get_signals_from_trends(
        self, topic: str, niche: str | None
    ) -> dict:
        """Query TrendingTopic DB for signals matching topic/niche."""
        from datetime import datetime, timezone

        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.models.analytics import TrendingTopic

        now = datetime.now(timezone.utc)
        hashtags: list[str] = []
        keywords: list[str] = []
        velocity = "rising"
        viral_potential = 0.0

        async with async_session_factory() as session:
            query = (
                select(TrendingTopic)
                .where(TrendingTopic.expires_at > now)
                .where(TrendingTopic.is_blacklisted.is_(False))
                .order_by(TrendingTopic.quality_score.desc())
                .limit(20)
            )
            if niche:
                query = query.where(TrendingTopic.niche == niche)

            result = await session.execute(query)
            trends = result.scalars().all()

        if not trends:
            return {"hashtags": [], "keywords": [], "velocity": "rising", "viral_potential": 0.0}

        topic_lower = topic.lower()

        for trend in trends:
            # Extract related queries as keywords
            if trend.related_queries:
                try:
                    related = json.loads(trend.related_queries) if isinstance(trend.related_queries, str) else trend.related_queries
                    if isinstance(related, list):
                        keywords.extend(related[:3])
                except (json.JSONDecodeError, TypeError):
                    pass

            # Convert high-quality keywords to hashtags
            trend_words = trend.topic.split()
            for word in trend_words:
                clean = re.sub(r"[^a-zA-Z0-9]", "", word)
                if len(clean) >= 3:
                    hashtags.append(f"#{clean}")

            # Use velocity/viral_potential from best matching trend
            if topic_lower in trend.topic.lower() or trend.topic.lower() in topic_lower:
                velocity = trend.velocity or "rising"
                viral_potential = max(viral_potential, trend.viral_potential or 0.0)

        return {
            "hashtags": hashtags[:8],
            "keywords": keywords[:8],
            "velocity": velocity,
            "viral_potential": viral_potential,
        }

    async def _get_youtube_autocomplete(self, topic: str) -> list[str]:
        """YouTube search suggest API (free, no key needed).

        Returns top search completions — these are what people actually search.
        """
        query = topic[:80]  # Limit query length
        url = (
            "https://suggestqueries.google.com/complete/search"
            f"?client=youtube&ds=yt&q={query}"
        )

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ContentEngine/1.0)"},
            )
            resp.raise_for_status()

            # Response is JSONP: callback([...])
            text = resp.text
            # Extract JSON array from JSONP
            start = text.find("[")
            if start == -1:
                return []

            data = json.loads(text[start:])
            # data[1] contains the suggestions
            if len(data) >= 2 and isinstance(data[1], list):
                suggestions = []
                for item in data[1]:
                    if isinstance(item, list) and item:
                        suggestions.append(str(item[0]))
                    elif isinstance(item, str):
                        suggestions.append(item)
                return suggestions[:8]

        return []

    def get_niche_hashtag_pool(self, niche: str | None) -> list[str]:
        """Get high-performing hashtags for a niche."""
        if niche and niche in NICHE_HASHTAG_POOLS:
            return NICHE_HASHTAG_POOLS[niche][:6]
        return GENERIC_VIRAL_HASHTAGS[:5]

    def build_viral_prompt_context(self, trending_data: dict) -> str:
        """Format trending data as text block for LLM injection.

        Returns a string to append to the user prompt.
        """
        parts: list[str] = ["\n--- TRENDING CONTEXT (use these for better discoverability) ---"]

        hashtags = trending_data.get("trending_hashtags", [])
        if hashtags:
            parts.append(f"Trending hashtags: {', '.join(hashtags[:8])}")

        keywords = trending_data.get("trending_keywords", [])
        if keywords:
            parts.append(f"Hot search terms: {', '.join(f'\"{kw}\"' for kw in keywords[:6])}")

        velocity = trending_data.get("velocity", "rising")
        velocity_text = {
            "rising": "RISING - this topic is gaining momentum, make it urgent!",
            "peaked": "PEAKED - this topic is at its peak, capitalize on the attention now!",
            "declining": "DECLINING - give a fresh angle to revive interest.",
        }.get(velocity, "RISING")
        parts.append(f"Topic velocity: {velocity_text}")

        niche_hashtags = trending_data.get("niche_hashtags", [])
        if niche_hashtags:
            parts.append(f"Niche hashtags to include: {', '.join(niche_hashtags[:5])}")

        viral_potential = trending_data.get("viral_potential", 0.0)
        if viral_potential > 0.5:
            parts.append("HIGH VIRAL POTENTIAL - this topic is exploding, go all-in on engagement!")

        parts.append("--- END TRENDING CONTEXT ---\n")

        return "\n".join(parts)

    def ensure_trending_hashtags(
        self, script_data: dict, trending_hashtags: list[str], max_inject: int = 3
    ) -> dict:
        """Post-process: ensure at least some trending hashtags are in the output.

        If the LLM didn't include trending hashtags, inject the top ones.
        """
        if not trending_hashtags:
            return script_data

        existing = script_data.get("hashtags", [])
        existing_lower = {h.lower() for h in existing}

        injected = 0
        for tag in trending_hashtags:
            if tag.lower() not in existing_lower and injected < max_inject:
                existing.append(tag)
                existing_lower.add(tag.lower())
                injected += 1

        # Cap at 8 hashtags total
        script_data["hashtags"] = existing[:8]

        if injected > 0:
            logger.info("Injected {} trending hashtags into script output", injected)

        return script_data

    def reorder_hashtags_for_youtube(self, hashtags: list[str]) -> list[str]:
        """Reorder hashtags so trending/viral ones appear last.

        YouTube shows the last 3 hashtags above the video title,
        so we want trending/viral ones at the end for maximum visibility.
        """
        if not hashtags:
            return hashtags

        # Separate: #Shorts always last, trending/viral second-to-last, rest first
        shorts_tag = None
        trending_tags: list[str] = []
        other_tags: list[str] = []

        viral_indicators = {"viral", "trending", "fyp", "foryou", "explore"}

        for tag in hashtags:
            tag_clean = tag.lstrip("#").lower()
            if tag_clean == "shorts":
                shorts_tag = tag
            elif tag_clean in viral_indicators:
                trending_tags.append(tag)
            else:
                other_tags.append(tag)

        # Order: other → trending → #Shorts
        ordered = other_tags + trending_tags
        if shorts_tag:
            ordered.append(shorts_tag)

        return ordered
