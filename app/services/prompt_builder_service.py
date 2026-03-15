"""
Dynamic Prompt Builder — enriches script generation prompts with
trending topics and learned performance patterns.

This is the core of the self-improvement feedback loop.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from loguru import logger

from app.core.config import get_settings

settings = get_settings()

# Default baseline prompt template
DEFAULT_BASELINE_TEMPLATE = (
    "Write a YouTube Shorts script about: {topic}\n\n"
    "Make it fascinating, dramatic, and impossible to scroll past. "
    "Use a powerful hook in the first sentence. "
    "Structure it with 4-5 visual beats. Keep it 80-100 words."
)


class DynamicPromptBuilder:
    """Enriches script generation prompts with trends and learned patterns."""

    async def build_enriched_prompt(
        self,
        base_topic: str,
        user_instructions: str | None = None,
        niche: str | None = None,
    ) -> tuple[str, dict]:
        """
        Build an enriched prompt with trends and patterns.

        Returns (enriched_prompt_string, metadata_dict).
        """
        # 1. Get active prompt version
        version = await self._get_active_version()
        template = version["template"] if version else DEFAULT_BASELINE_TEMPLATE
        version_id = version["id"] if version else None

        # Start building the enriched prompt
        prompt_parts = []

        # Base prompt from template
        prompt_parts.append(template.replace("{topic}", base_topic))

        # 2. Get current trends
        trend = None
        trend_topic = None
        try:
            from app.services.trend_service import TrendService

            trend_service = TrendService()
            trend = await trend_service.get_trend_for_video(niche)
        except Exception as exc:
            logger.warning("Failed to fetch trends for prompt enrichment: {}", exc)

        if trend:
            trend_topic = trend["topic"]
            prompt_parts.append(
                f"\nTRENDING NOW: The topic '{trend['topic']}' is currently trending "
                f"(score: {trend['trend_score']}/100). If relevant to the main topic, "
                "incorporate this trend angle to boost discoverability."
            )

        # 3. Get active patterns
        patterns_applied = []
        try:
            from app.services.pattern_service import PatternService

            pattern_service = PatternService()
            patterns = await pattern_service.get_active_patterns(min_confidence=0.6)
        except Exception as exc:
            logger.warning("Failed to fetch patterns for prompt enrichment: {}", exc)
            patterns = []

        if patterns:
            pattern_lines = [
                f"- {p['description']} (confidence: {p['confidence_score']:.0%})"
                for p in patterns[:5]
            ]
            prompt_parts.append(
                "\nPROVEN PATTERNS FROM YOUR BEST-PERFORMING VIDEOS:\n"
                + "\n".join(pattern_lines)
                + "\nApply these patterns to maximize engagement."
            )
            patterns_applied = [p["id"] for p in patterns[:5]]

        # 4. User instructions
        if user_instructions:
            prompt_parts.append(f"\nADDITIONAL INSTRUCTIONS:\n{user_instructions}")

        enriched_prompt = "\n".join(prompt_parts)

        metadata = {
            "prompt_version_id": version_id,
            "trend_topic_used": trend_topic,
            "patterns_applied": patterns_applied,
        }

        logger.info(
            "Enriched prompt built — version={} trend={} patterns={}",
            version_id,
            trend_topic,
            len(patterns_applied),
        )

        return enriched_prompt, metadata

    async def _get_active_version(self) -> dict | None:
        """Get the currently active prompt version."""
        from sqlalchemy import select
        from app.core.database import async_session_factory
        from app.models.analytics import PromptVersion

        async with async_session_factory() as session:
            query = (
                select(PromptVersion)
                .where(PromptVersion.is_active.is_(True))
                .limit(1)
            )
            result = await session.execute(query)
            version = result.scalar_one_or_none()

            if version:
                return {
                    "id": str(version.id),
                    "template": version.template,
                    "version_label": version.version_label,
                }

        # No active version — create default baseline
        return await self._create_default_baseline()

    async def _create_default_baseline(self) -> dict:
        """Create a default baseline prompt version."""
        from app.core.database import async_session_factory
        from app.models.analytics import PromptVersion

        version_id = uuid.uuid4()

        async with async_session_factory() as session:
            version = PromptVersion(
                id=version_id,
                version_label="v1-baseline",
                template=DEFAULT_BASELINE_TEMPLATE,
                variables=None,
                is_active=True,
                is_baseline=True,
                usage_count=0,
            )
            session.add(version)
            await session.commit()

        logger.info("Created default baseline prompt version: {}", version_id)
        return {
            "id": str(version_id),
            "template": DEFAULT_BASELINE_TEMPLATE,
            "version_label": "v1-baseline",
        }

    async def record_prompt_usage(
        self, prompt_version_id: str, project_id: str
    ) -> None:
        """Increment usage_count on the prompt version and store on project."""
        from sqlalchemy import update
        from app.core.database import async_session_factory
        from app.models.analytics import PromptVersion
        from app.models.video import VideoProject

        async with async_session_factory() as session:
            # Increment usage count
            await session.execute(
                update(PromptVersion)
                .where(PromptVersion.id == uuid.UUID(prompt_version_id))
                .values(usage_count=PromptVersion.usage_count + 1)
            )
            await session.commit()

    async def update_prompt_performance(self, prompt_version_id: str) -> None:
        """
        Recalculate avg_views, avg_retention, avg_ctr for a prompt version
        based on all videos that used it.
        """
        from sqlalchemy import select, func, update
        from app.core.database import async_session_factory
        from app.models.analytics import VideoAnalytics, PromptVersion
        from app.models.video import VideoProject

        async with async_session_factory() as session:
            # Get all projects that used this prompt version
            query = (
                select(
                    func.avg(VideoAnalytics.views).label("avg_views"),
                    func.avg(VideoAnalytics.average_view_percentage).label(
                        "avg_retention"
                    ),
                    func.avg(VideoAnalytics.click_through_rate).label("avg_ctr"),
                )
                .join(
                    VideoProject,
                    VideoAnalytics.project_id == sa.cast(VideoProject.id, sa.String),
                )
                .where(VideoProject.prompt_version_id == prompt_version_id)
            )
            result = await session.execute(query)
            row = result.one()

            if row.avg_views is not None:
                await session.execute(
                    update(PromptVersion)
                    .where(PromptVersion.id == uuid.UUID(prompt_version_id))
                    .values(
                        avg_views=float(row.avg_views),
                        avg_retention=(
                            float(row.avg_retention) if row.avg_retention else None
                        ),
                        avg_ctr=float(row.avg_ctr) if row.avg_ctr else None,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()

    async def update_all_prompt_performance(self) -> None:
        """Update performance metrics for all prompt versions with usage."""
        from sqlalchemy import select
        from app.core.database import async_session_factory
        from app.models.analytics import PromptVersion

        async with async_session_factory() as session:
            query = select(PromptVersion).where(PromptVersion.usage_count > 0)
            result = await session.execute(query)
            versions = result.scalars().all()

        for version in versions:
            try:
                await self.update_prompt_performance(str(version.id))
            except Exception as exc:
                logger.warning(
                    "Failed to update performance for version {}: {}",
                    version.id,
                    exc,
                )

    async def create_new_version(self, template: str, label: str) -> str:
        """
        Create a new prompt version (inactive by default).

        Returns version_id.
        """
        from app.core.database import async_session_factory
        from app.models.analytics import PromptVersion

        version_id = uuid.uuid4()

        async with async_session_factory() as session:
            version = PromptVersion(
                id=version_id,
                version_label=label,
                template=template,
                is_active=False,
                is_baseline=False,
                usage_count=0,
            )
            session.add(version)
            await session.commit()

        logger.info("Created new prompt version: {} ({})", label, version_id)
        return str(version_id)

    async def promote_version(self, version_id: str) -> bool:
        """
        Set this version as active, deactivate previous active version.

        Only promote if this version has been used for at least 5 videos
        and its avg_views > baseline avg_views.
        """
        from sqlalchemy import select, update
        from app.core.database import async_session_factory
        from app.models.analytics import PromptVersion

        async with async_session_factory() as session:
            # Get the version to promote
            version = await session.get(PromptVersion, uuid.UUID(version_id))
            if not version:
                raise ValueError(f"Prompt version {version_id} not found")

            if version.usage_count < 5:
                logger.warning(
                    "Cannot promote version {} — only {} uses (need 5)",
                    version_id,
                    version.usage_count,
                )
                return False

            # Check against baseline
            baseline_q = (
                select(PromptVersion)
                .where(PromptVersion.is_baseline.is_(True))
                .limit(1)
            )
            baseline_result = await session.execute(baseline_q)
            baseline = baseline_result.scalar_one_or_none()

            if baseline and baseline.avg_views and version.avg_views:
                if version.avg_views <= baseline.avg_views:
                    logger.info(
                        "Version {} not promoted — avg_views {:.1f} <= baseline {:.1f}",
                        version_id,
                        version.avg_views,
                        baseline.avg_views,
                    )
                    return False

            # Deactivate all currently active versions
            await session.execute(
                update(PromptVersion)
                .where(PromptVersion.is_active.is_(True))
                .values(is_active=False)
            )

            # Activate this version
            version.is_active = True
            version.updated_at = datetime.now(timezone.utc)
            await session.commit()

        logger.info("Promoted prompt version {} to active", version_id)
        return True

    async def maybe_create_improved_version(
        self, patterns: list[dict]
    ) -> str | None:
        """
        Create a new prompt version incorporating discovered patterns.

        Called by pattern analyzer when significant patterns are found.
        """
        if not patterns or len(patterns) < 3:
            return None

        # Build improved template incorporating patterns
        pattern_instructions = "\n".join(
            f"- {p['description']}" for p in patterns if "description" in p
        )

        template = (
            "Write a YouTube Shorts script about: {topic}\n\n"
            "Make it fascinating, dramatic, and impossible to scroll past.\n\n"
            "APPLY THESE PROVEN PATTERNS:\n"
            f"{pattern_instructions}\n\n"
            "Use a powerful hook in the first sentence. "
            "Structure it with 4-5 visual beats. Keep it 80-100 words."
        )

        label = f"v-auto-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        version_id = await self.create_new_version(template, label)

        logger.info(
            "Created auto-improved prompt version {} with {} patterns",
            version_id,
            len(patterns),
        )
        return version_id
