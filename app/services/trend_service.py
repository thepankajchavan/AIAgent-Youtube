"""
Trend Aggregator — multi-source trend fetching with smart scoring.

Fetches from YouTube Trending, Google Trends, Reddit, and Twitter/X.
Applies weighted scoring, velocity detection, niche classification, and deduplication.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings

# ── Source weights for composite scoring ──────────────────────
SOURCE_WEIGHTS: dict[str, float] = {
    "youtube_trending": 1.0,
    "google_trends": 0.85,
    "reddit": 0.7,
    "twitter": 0.5,
}

# ── Niche keyword detection ──────────────────────────────────
NICHE_KEYWORDS: dict[str, list[str]] = {
    "science": [
        "research", "discovery", "study", "quantum", "DNA", "biology",
        "physics", "chemistry", "experiment", "molecule", "genome",
        "neuroscience", "evolution", "climate", "species", "lab",
    ],
    "technology": [
        "AI", "robot", "software", "chip", "launch", "startup",
        "cyber", "cloud", "data", "algorithm", "machine learning",
        "blockchain", "app", "device", "processor", "GPU",
    ],
    "history": [
        "ancient", "war", "empire", "century", "civilization",
        "medieval", "dynasty", "archaeological", "revolution",
        "colonial", "historic", "artifact", "era",
    ],
    "motivation": [
        "success", "mindset", "discipline", "habits", "goals",
        "productivity", "self-improvement", "hustle", "growth",
        "wealth", "millionaire", "entrepreneur", "grind",
    ],
    "psychology": [
        "brain", "mental", "cognitive", "behavior", "emotion",
        "personality", "anxiety", "therapy", "subconscious",
        "trauma", "narcissist", "manipulation", "attachment",
    ],
    "space": [
        "NASA", "Mars", "moon", "satellite", "galaxy", "star",
        "telescope", "orbit", "astronaut", "rocket", "SpaceX",
        "cosmos", "universe", "planet", "black hole",
    ],
    "entertainment": [
        "movie", "celebrity", "album", "concert", "Netflix",
        "streaming", "series", "trailer", "box office",
        "award", "viral", "meme", "TikTok",
    ],
}


class TrendAggregator:
    """Multi-source trend aggregation with weighted scoring."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ── Public API ────────────────────────────────────────────

    async def collect_and_store_trends(self) -> int:
        """Full pipeline: fetch all → score → velocity → niche → dedup → store.

        Returns count of new trends stored.
        """
        from app.core.database import async_session_factory
        from app.models.analytics import TrendingTopic

        raw_trends = await self.fetch_all_sources(
            categories=[c.strip() for c in self._settings.trends_categories.split(",") if c.strip()],
            region=self._settings.trends_region,
        )

        if not raw_trends:
            logger.info("No trends collected from any source")
            return 0

        # Score each trend
        scored = [self.score_trend(t) for t in raw_trends]

        # Detect niche for each
        for trend in scored:
            if not trend.get("niche"):
                trend["niche"] = self.detect_niche(
                    trend["topic"],
                    trend.get("related_queries", []),
                )

        # Detect velocity by comparing with recent DB records
        historical = await self._get_recent_trends_for_velocity()
        for trend in scored:
            trend["velocity"] = self.detect_velocity(trend, historical)

        # Deduplicate
        unique = self._deduplicate_trends(scored)

        # Store in DB
        now = datetime.now(timezone.utc)
        expiry_hours = getattr(self._settings, "trends_expiry_hours", 24)
        expires = now + timedelta(hours=expiry_hours)
        stored = 0

        async with async_session_factory() as session:
            for trend in unique:
                record = TrendingTopic(
                    id=uuid.uuid4(),
                    topic=trend["topic"][:512],
                    category=trend.get("category"),
                    trend_score=trend["trend_score"],
                    source=trend["source"],
                    region=self._settings.trends_region,
                    related_queries=json.dumps(trend.get("related_queries", [])),
                    fetched_at=now,
                    expires_at=expires,
                    velocity=trend.get("velocity", "rising"),
                    quality_score=trend.get("quality_score", 0.0),
                    viral_potential=trend.get("viral_potential", 0.0),
                    niche=trend.get("niche"),
                    source_url=trend.get("source_url"),
                    source_metadata=json.dumps(trend.get("source_metadata")) if trend.get("source_metadata") else None,
                )
                session.add(record)
                stored += 1
            await session.commit()

        logger.info("Stored {} unique trends (from {} raw)", stored, len(raw_trends))
        return stored

    async def fetch_all_sources(
        self, categories: list[str], region: str
    ) -> list[dict]:
        """Fetch from all enabled sources in parallel."""
        tasks: list = []

        # Google Trends (per category)
        for cat in categories:
            tasks.append(self.fetch_google_trends(category=cat, region=region))

        # YouTube Trending
        tasks.append(self.fetch_youtube_trending(region=region))

        # Reddit (if enabled)
        if getattr(self._settings, "trends_reddit_enabled", False):
            subreddits_str = getattr(
                self._settings, "trends_reddit_subreddits",
                "technology,science,worldnews,futurology",
            )
            subreddits = [s.strip() for s in subreddits_str.split(",") if s.strip()]
            tasks.append(self.fetch_reddit_trending(subreddits=subreddits))

        # Twitter (if enabled)
        if getattr(self._settings, "trends_twitter_enabled", False):
            tasks.append(self.fetch_twitter_trending(region=region))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_trends: list[dict] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Source fetch failed: {}", result)
                continue
            if isinstance(result, list):
                all_trends.extend(result)

        return all_trends

    # ── Individual Source Fetchers ─────────────────────────────

    async def fetch_google_trends(
        self, category: str = "", region: str = "US"
    ) -> list[dict]:
        """Fetch trending searches from Google Trends via pytrends (executor)."""
        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(
                None, self._fetch_google_trends_sync, category, region
            )
            return results
        except Exception as exc:
            logger.warning("Google Trends fetch failed: {}", exc)
            return []

    def _fetch_google_trends_sync(self, category: str, region: str) -> list[dict]:
        """Synchronous Google Trends fetch."""
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 30))
        results: list[dict] = []

        # Daily trending searches
        try:
            trending = pytrends.trending_searches(pn=region.lower())
            for idx, row in trending.iterrows():
                topic_name = str(row[0])
                results.append({
                    "topic": topic_name,
                    "trend_score": max(80.0 - idx * 2, 10.0),
                    "category": category or None,
                    "related_queries": [],
                    "source": "google_trends",
                })
        except Exception as exc:
            logger.warning("Google Trends daily search failed: {}", exc)

        # Related queries for category
        if category:
            try:
                pytrends.build_payload([category], timeframe="now 1-d", geo=region)
                related = pytrends.related_queries()
                if category in related and related[category].get("rising") is not None:
                    rising_df = related[category]["rising"]
                    for _, row in rising_df.head(10).iterrows():
                        results.append({
                            "topic": str(row["query"]),
                            "trend_score": min(float(row.get("value", 50)), 100.0),
                            "category": category,
                            "related_queries": [],
                            "source": "google_trends",
                        })
            except Exception as exc:
                logger.warning("Google Trends related queries failed for '{}': {}", category, exc)

        logger.info("Google Trends fetched — region={} category={} results={}", region, category, len(results))
        return results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        retry=retry_if_exception_type((ConnectionError, OSError)),
    )
    async def fetch_youtube_trending(
        self, region: str = "US", category_id: str = "0"
    ) -> list[dict]:
        """Fetch trending videos from YouTube Data API v3."""
        from googleapiclient.discovery import build

        loop = asyncio.get_event_loop()

        def _fetch() -> list[dict]:
            youtube = build("youtube", "v3", developerKey=self._settings.youtube_api_key)
            request = youtube.videos().list(
                part="snippet,statistics",
                chart="mostPopular",
                regionCode=region,
                videoCategoryId=category_id,
                maxResults=20,
            )
            response = request.execute()
            items = response.get("items", [])

            results = []
            for idx, item in enumerate(items):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                title = snippet.get("title", "")
                tags = snippet.get("tags", [])
                view_count = int(stats.get("viewCount", 0))
                video_id = item.get("id", "")

                score = max(90.0 - idx * 3, 10.0)
                # Viral potential based on view count and position
                viral = min(view_count / 10_000_000, 1.0) if view_count else 0.0

                results.append({
                    "topic": title,
                    "trend_score": score,
                    "category": snippet.get("categoryId"),
                    "related_queries": tags[:5] if tags else [],
                    "source": "youtube_trending",
                    "viral_potential": viral,
                    "source_url": f"https://youtube.com/watch?v={video_id}" if video_id else None,
                    "source_metadata": {"view_count": view_count, "video_id": video_id},
                })
            return results

        try:
            results = await loop.run_in_executor(None, _fetch)
            logger.info("YouTube trending fetched — region={} results={}", region, len(results))
            return results
        except Exception as exc:
            logger.warning("YouTube trending fetch failed: {}", exc)
            return []

    async def fetch_reddit_trending(self, subreddits: list[str]) -> list[dict]:
        """Fetch hot posts from Reddit's public JSON API. No auth needed."""
        results: list[dict] = []

        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "ContentEngine/1.0 (trend-aggregator)"},
        ) as client:
            for sub in subreddits:
                try:
                    url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10"
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()

                    posts = data.get("data", {}).get("children", [])
                    for idx, post in enumerate(posts):
                        post_data = post.get("data", {})
                        title = post_data.get("title", "")
                        upvotes = post_data.get("ups", 0)
                        num_comments = post_data.get("num_comments", 0)
                        permalink = post_data.get("permalink", "")

                        if not title or post_data.get("stickied"):
                            continue

                        score = max(75.0 - idx * 5, 10.0)
                        viral = min(upvotes / 50_000, 1.0) if upvotes else 0.0

                        results.append({
                            "topic": title,
                            "trend_score": score,
                            "category": sub,
                            "related_queries": [],
                            "source": "reddit",
                            "viral_potential": viral,
                            "source_url": f"https://reddit.com{permalink}" if permalink else None,
                            "source_metadata": {
                                "subreddit": sub,
                                "upvotes": upvotes,
                                "num_comments": num_comments,
                            },
                        })

                    # Rate limit: 2s between subreddit requests
                    await asyncio.sleep(2)

                except Exception as exc:
                    logger.warning("Reddit fetch failed for r/{}: {}", sub, exc)

        logger.info("Reddit trending fetched — subreddits={} results={}", len(subreddits), len(results))
        return results

    async def fetch_twitter_trending(self, region: str = "US") -> list[dict]:
        """Fetch trending topics from Twitter/X. Gracefully degrades if unavailable."""
        results: list[dict] = []

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ContentEngine/1.0)"},
                follow_redirects=True,
            ) as client:
                # Use the public Nitter instance or Twitter's public trends
                # This is a best-effort source — silent failure is expected
                url = "https://nitter.net/search?q=trending&f=tweets"
                resp = await client.get(url)

                if resp.status_code != 200:
                    logger.info("Twitter/X trends unavailable (status={}), skipping", resp.status_code)
                    return []

                # Basic extraction of trending keywords from response
                text = resp.text
                # Extract hashtags as trending topics
                hashtags = re.findall(r"#(\w{3,30})", text)
                seen: set[str] = set()

                for idx, tag in enumerate(hashtags[:15]):
                    tag_lower = tag.lower()
                    if tag_lower in seen:
                        continue
                    seen.add(tag_lower)

                    results.append({
                        "topic": f"#{tag}",
                        "trend_score": max(60.0 - idx * 4, 10.0),
                        "category": None,
                        "related_queries": [],
                        "source": "twitter",
                        "viral_potential": 0.3,
                        "source_url": f"https://twitter.com/hashtag/{tag}",
                        "source_metadata": {"hashtag": tag},
                    })

        except Exception as exc:
            logger.info("Twitter/X trends unavailable: {}", exc)

        logger.info("Twitter trending fetched — results={}", len(results))
        return results

    # ── Scoring & Classification ──────────────────────────────

    def score_trend(self, raw: dict) -> dict:
        """Apply weighted scoring: base_score * source_weight * niche_bonus.

        Returns the trend dict with quality_score and viral_potential added.
        """
        source = raw.get("source", "")
        weight = SOURCE_WEIGHTS.get(source, 0.5)
        base_score = raw.get("trend_score", 0.0)

        # Weighted score
        quality = base_score * weight

        # Viral potential boost
        viral = raw.get("viral_potential", 0.0)
        if viral > 0.5:
            quality *= 1.15
        elif viral > 0.2:
            quality *= 1.05

        quality = min(quality, 100.0)

        result = raw.copy()
        result["quality_score"] = round(quality, 2)
        result["viral_potential"] = viral
        return result

    def detect_velocity(self, trend: dict, historical: list[dict]) -> str:
        """Detect if a trend is rising, peaked, or declining.

        Compares against historical snapshots from the last 12 hours.
        """
        topic_lower = trend["topic"].lower()

        # Find matching historical entries
        past_scores: list[float] = []
        for h in historical:
            similarity = SequenceMatcher(None, topic_lower, h["topic"].lower()).ratio()
            if similarity >= 0.75:
                past_scores.append(h["trend_score"])

        if not past_scores:
            return "rising"  # New topic = rising

        avg_past = sum(past_scores) / len(past_scores)
        current = trend.get("trend_score", 0.0)

        if current > avg_past * 1.1:
            return "rising"
        elif current < avg_past * 0.85:
            return "declining"
        else:
            return "peaked"

    def detect_niche(self, topic: str, tags: list[str] | None = None) -> str | None:
        """Detect niche via keyword regex matching (word boundaries)."""
        text = topic.lower()
        if tags:
            text += " " + " ".join(t.lower() for t in tags)

        best_niche: str | None = None
        best_count = 0

        for niche, keywords in NICHE_KEYWORDS.items():
            count = 0
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw.lower()) + r"\b", text):
                    count += 1
            if count > best_count:
                best_count = count
                best_niche = niche

        return best_niche if best_count >= 1 else None

    # ── Deduplication ─────────────────────────────────────────

    def _deduplicate_trends(self, trends: list[dict]) -> list[dict]:
        """Remove near-duplicate topics using fuzzy matching (75% threshold).

        Cross-source matches get a 1.3x score boost.
        """
        unique: list[dict] = []

        for trend in trends:
            is_dup = False
            for existing in unique:
                similarity = SequenceMatcher(
                    None,
                    trend["topic"].lower(),
                    existing["topic"].lower(),
                ).ratio()
                if similarity >= 0.75:
                    # Cross-source boost
                    if trend["source"] != existing["source"]:
                        existing["quality_score"] = min(
                            (existing.get("quality_score", 0) + trend.get("quality_score", 0)) / 2 * 1.3,
                            100.0,
                        )
                        existing["trend_score"] = min(
                            (existing["trend_score"] + trend["trend_score"]) / 2 * 1.3,
                            100.0,
                        )
                    elif trend.get("quality_score", 0) > existing.get("quality_score", 0):
                        existing["quality_score"] = trend["quality_score"]
                    is_dup = True
                    break
            if not is_dup:
                unique.append(trend.copy())

        return unique

    # ── Query Methods ─────────────────────────────────────────

    async def get_current_trends(
        self, category: str | None = None, limit: int = 10
    ) -> list[dict]:
        """Query active (non-expired) trends from DB."""
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.models.analytics import TrendingTopic

        now = datetime.now(timezone.utc)

        async with async_session_factory() as session:
            query = (
                select(TrendingTopic)
                .where(TrendingTopic.expires_at > now)
                .where(TrendingTopic.is_blacklisted.is_(False))
                .order_by(TrendingTopic.quality_score.desc())
                .limit(limit)
            )
            if category:
                query = query.where(TrendingTopic.category == category)

            result = await session.execute(query)
            topics = result.scalars().all()

        return [
            {
                "id": str(t.id),
                "topic": t.topic,
                "category": t.category,
                "trend_score": t.trend_score,
                "quality_score": t.quality_score,
                "velocity": t.velocity,
                "niche": t.niche,
                "source": t.source,
                "viral_potential": t.viral_potential,
                "fetched_at": t.fetched_at.isoformat() if t.fetched_at else None,
            }
            for t in topics
        ]

    async def get_best_topics_for_scheduling(
        self,
        niche: str | None = None,
        limit: int = 10,
        exclude_used_days: int = 3,
    ) -> list[dict]:
        """Get best topics for auto-scheduling.

        Filters by: non-expired, quality >= threshold, not blacklisted,
        velocity != declining, not recently used.
        """
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.models.analytics import TrendingTopic
        from app.models.video import VideoProject

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=exclude_used_days)
        min_quality = getattr(self._settings, "trends_min_quality_score", 40.0)

        async with async_session_factory() as session:
            query = (
                select(TrendingTopic)
                .where(TrendingTopic.expires_at > now)
                .where(TrendingTopic.is_blacklisted.is_(False))
                .where(TrendingTopic.quality_score >= min_quality)
                .where(TrendingTopic.velocity != "declining")
                .order_by(TrendingTopic.quality_score.desc())
                .limit(limit * 2)  # Fetch extra to filter used ones
            )
            if niche:
                query = query.where(TrendingTopic.niche == niche)

            result = await session.execute(query)
            trends = result.scalars().all()

            # Get recently used topics
            recent_q = (
                select(VideoProject.trend_topic_used)
                .where(VideoProject.trend_topic_used.isnot(None))
                .where(VideoProject.created_at > cutoff)
            )
            recent_result = await session.execute(recent_q)
            recently_used = {row[0] for row in recent_result.all()}

        # Filter out recently used (fuzzy match)
        filtered: list[dict] = []
        for t in trends:
            is_used = False
            for used_topic in recently_used:
                if SequenceMatcher(None, t.topic.lower(), used_topic.lower()).ratio() >= 0.6:
                    is_used = True
                    break
            if not is_used:
                filtered.append({
                    "id": str(t.id),
                    "topic": t.topic,
                    "category": t.category,
                    "niche": t.niche,
                    "trend_score": t.trend_score,
                    "quality_score": t.quality_score,
                    "velocity": t.velocity,
                    "viral_potential": t.viral_potential,
                    "source": t.source,
                })
            if len(filtered) >= limit:
                break

        # If all filtered out, return top trend anyway
        if not filtered and trends:
            top = trends[0]
            filtered.append({
                "id": str(top.id),
                "topic": top.topic,
                "category": top.category,
                "niche": top.niche,
                "trend_score": top.trend_score,
                "quality_score": top.quality_score,
                "velocity": top.velocity,
                "viral_potential": top.viral_potential,
                "source": top.source,
            })

        return filtered

    # ── Backward Compatibility ────────────────────────────────

    async def get_trend_for_video(self, niche: str | None = None) -> dict | None:
        """Pick the best trending topic for the next video.

        Backward-compatible wrapper around get_best_topics_for_scheduling.
        """
        topics = await self.get_best_topics_for_scheduling(
            niche=niche, limit=1, exclude_used_days=3
        )
        return topics[0] if topics else None

    # ── Internal Helpers ──────────────────────────────────────

    async def _get_recent_trends_for_velocity(self) -> list[dict]:
        """Get trends from last 12 hours for velocity comparison."""
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.models.analytics import TrendingTopic

        twelve_hours_ago = datetime.now(timezone.utc) - timedelta(hours=12)

        try:
            async with async_session_factory() as session:
                query = (
                    select(TrendingTopic.topic, TrendingTopic.trend_score)
                    .where(TrendingTopic.fetched_at > twelve_hours_ago)
                    .order_by(TrendingTopic.fetched_at.desc())
                    .limit(100)
                )
                result = await session.execute(query)
                rows = result.all()

            return [{"topic": row[0], "trend_score": row[1]} for row in rows]
        except Exception:
            return []


# Backward compatibility alias
TrendService = TrendAggregator
