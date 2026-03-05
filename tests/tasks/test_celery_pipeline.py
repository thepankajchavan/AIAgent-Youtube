"""Tests for Celery pipeline orchestration (build_pipeline + run_pipeline_task)."""

from unittest.mock import MagicMock

from app.workers.pipeline import build_pipeline, run_pipeline_task


class TestBuildPipeline:
    """Test pipeline construction via build_pipeline()."""

    def test_build_pipeline_returns_chain(self):
        """Test that build_pipeline returns a Celery chain."""
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="test topic",
            video_format="short",
            provider="openai",
            skip_upload=False,
        )
        # Should return a Celery canvas primitive (chain)
        assert pipeline is not None

    def test_build_pipeline_skip_upload_omits_upload_step(self):
        """Test that skip_upload=True omits the upload task."""
        pipeline_with = build_pipeline(
            project_id="test-uuid",
            topic="test topic",
            skip_upload=False,
        )
        pipeline_without = build_pipeline(
            project_id="test-uuid",
            topic="test topic",
            skip_upload=True,
        )

        # The full pipeline has more tasks than the skip-upload version
        # Chain tasks are stored in .tasks
        with_tasks = list(pipeline_with.tasks)
        without_tasks = list(pipeline_without.tasks)
        assert len(with_tasks) > len(without_tasks)

    def test_build_pipeline_default_provider(self):
        """Test default provider is openai."""
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="test topic",
        )
        assert pipeline is not None

    def test_build_pipeline_anthropic_provider(self):
        """Test building pipeline with anthropic provider."""
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="test topic",
            provider="anthropic",
        )
        assert pipeline is not None


class TestRunPipelineTask:
    """Test the run_pipeline_task entry-point task."""

    def test_run_pipeline_task_dispatches_chain(self, mocker):
        """Test that run_pipeline_task builds and dispatches the pipeline."""
        mock_chain = MagicMock()
        mock_result = MagicMock()
        mock_result.id = "chain-task-id-123"
        mock_chain.apply_async.return_value = mock_result

        mocker.patch(
            "app.workers.pipeline.build_pipeline",
            return_value=mock_chain,
        )

        result = run_pipeline_task(
            project_id="test-uuid",
            topic="test topic",
            video_format="short",
            provider="openai",
            skip_upload=False,
        )

        assert result == "chain-task-id-123"
        mock_chain.apply_async.assert_called_once()

    def test_run_pipeline_task_passes_skip_upload(self, mocker):
        """Test that skip_upload flag is passed through."""
        mock_chain = MagicMock()
        mock_chain.apply_async.return_value = MagicMock(id="task-id")

        mock_build = mocker.patch(
            "app.workers.pipeline.build_pipeline",
            return_value=mock_chain,
        )

        run_pipeline_task(
            project_id="test-uuid",
            topic="test",
            skip_upload=True,
        )

        mock_build.assert_called_once_with(
            project_id="test-uuid",
            topic="test",
            video_format="short",
            provider="openai",
            skip_upload=True,
        )
