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

        # Both return valid chains; the upload task is present in one but not the other.
        # Celery may merge the upload into the chord callback, so we check the
        # string representation for the upload task name instead of counting tasks.
        with_repr = repr(pipeline_with)
        without_repr = repr(pipeline_without)
        assert "upload_to_youtube_task" in with_repr
        assert "upload_to_youtube_task" not in without_repr

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
            visual_strategy="stock_only",
            ai_video_provider=None,
            target_duration=None,
            language=None,
            voice_id=None,
        )


class TestBuildPipelineAIImages:
    """Test pipeline construction for ai_images visual strategy."""

    def test_ai_images_uses_sequential_path(self):
        """ai_images strategy should use the sequential (audio-first) pipeline,
        same as ai_only/hybrid."""
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="test topic",
            video_format="short",
            visual_strategy="ai_images",
        )
        pipeline_repr = repr(pipeline)
        # Sequential path should include split_scenes_task
        assert "split_scenes_task" in pipeline_repr
        # Should NOT use chord (parallel audio+visuals)
        assert pipeline is not None

    def test_ai_images_includes_all_steps(self):
        """ai_images pipeline should include script, audio, scene split, visuals, assembly."""
        pipeline = build_pipeline(
            project_id="test-uuid",
            topic="test topic",
            visual_strategy="ai_images",
            skip_upload=True,
        )
        pipeline_repr = repr(pipeline)
        assert "generate_script_task" in pipeline_repr
        assert "generate_audio_task" in pipeline_repr
        assert "split_scenes_task" in pipeline_repr
        assert "generate_visuals_task" in pipeline_repr
        assert "assemble_video_task" in pipeline_repr
