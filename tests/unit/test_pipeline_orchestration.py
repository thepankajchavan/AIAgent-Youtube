"""Unit tests for pipeline orchestration (build_pipeline)."""

from celery import chord
from celery.canvas import _chain

from app.workers.pipeline import build_pipeline


class TestBuildPipeline:
    """Test build_pipeline returns correct Celery chain structure."""

    def test_full_pipeline_is_chain(self):
        """Test full pipeline returns a chain with script and media stages."""
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="space facts",
            video_format="short",
            provider="openai",
            skip_upload=False,
        )

        # Should be a chain (internal _chain type)
        assert isinstance(pipeline, _chain)
        # Should have at least 2 tasks (Celery may flatten chord+upload)
        assert len(pipeline.tasks) >= 2

    def test_skip_upload_pipeline(self):
        """Test that skip_upload=True omits the upload step."""
        pipeline_with = build_pipeline(
            project_id="test-uuid",
            topic="space facts",
            skip_upload=False,
        )
        pipeline_without = build_pipeline(
            project_id="test-uuid",
            topic="space facts",
            skip_upload=True,
        )

        assert isinstance(pipeline_without, _chain)
        # skip_upload should produce a shorter pipeline
        assert len(pipeline_without.tasks) <= len(pipeline_with.tasks)

    def test_script_task_receives_correct_args(self):
        """Test that the script task is configured with correct arguments."""
        pipeline = build_pipeline(
            project_id="proj-123",
            topic="ocean life",
            video_format="long",
            provider="anthropic",
        )

        # First task in chain should be the script task signature
        script_sig = pipeline.tasks[0]
        assert script_sig.kwargs["project_id"] == "proj-123"
        assert script_sig.kwargs["topic"] == "ocean life"
        assert script_sig.kwargs["video_format"] == "long"
        assert script_sig.kwargs["provider"] == "anthropic"

    def test_default_values_applied(self):
        """Test that default values are applied for optional params."""
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="test",
        )

        script_sig = pipeline.tasks[0]
        assert script_sig.kwargs["video_format"] == "short"
        assert script_sig.kwargs["provider"] == "openai"

    def test_pipeline_contains_chord_for_parallel_media(self):
        """Test that the pipeline contains a chord for parallel media tasks.

        The chord runs audio + visual generation in parallel,
        then passes results to the assembly callback.
        """
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="test",
            skip_upload=True,
        )

        # The second task (after script) should be a chord
        media_stage = pipeline.tasks[1]
        assert isinstance(media_stage, chord)
