"""
Quick end-to-end test: Audio-First AI Video Pipeline
Runs real APIs for script + audio, mocks Runway to save credits.

Flow: Script (OpenAI) → TTS Audio (ElevenLabs) → Scene Split (real audio_duration) → Mock Visuals → Assembly
"""

import asyncio
import shutil
import sys
import time
from pathlib import Path

from loguru import logger

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<8} | {message}")


async def main():
    topic = "Why do octopuses have blue blood"
    video_format = "short"
    provider = "openai"

    logger.info("=" * 60)
    logger.info("E2E TEST: Audio-First AI Video Pipeline")
    logger.info("Topic: {}", topic)
    logger.info("(Runway mocked to save credits)")
    logger.info("=" * 60)

    # ── Step 1: Generate Script ──────────────────────────────
    logger.info("\n[1/5] Generating script via OpenAI...")
    t0 = time.time()

    from app.services.llm_service import LLMProvider, generate_script

    script_data = await generate_script(
        topic=topic,
        video_format=video_format,
        provider=LLMProvider.OPENAI,
    )

    logger.info("Script generated in {:.1f}s", time.time() - t0)
    logger.info("Title: {}", script_data.get("title", "N/A"))
    script_text = script_data["script"]
    word_count = len(script_text.split())
    logger.info("Script: {} words", word_count)
    logger.info("Preview: {}...", script_text[:200])

    # ── Step 2: Generate TTS Audio ───────────────────────────
    logger.info("\n[2/5] Generating TTS audio via ElevenLabs...")
    t0 = time.time()

    from app.services.tts_service import generate_speech

    audio_path = await generate_speech(
        text=script_text,
        output_filename="e2e_test_audio.mp3",
    )

    from app.services.media_service import probe_duration

    audio_duration = probe_duration(audio_path)
    logger.info("Audio generated in {:.1f}s", time.time() - t0)
    logger.info("Audio path: {}", audio_path)
    logger.info("Audio duration: {:.1f}s", audio_duration)

    # ── Step 3: Split Scenes (with real audio_duration) ──────
    logger.info("\n[3/5] Splitting script into scenes (audio_duration={:.1f}s)...", audio_duration)
    t0 = time.time()

    from app.services.ai_video_service import split_script_to_scenes

    scenes = await split_script_to_scenes(
        script=script_text,
        video_format=video_format,
        provider=provider,
        visual_strategy="ai_only",
        audio_duration=audio_duration,
    )

    total_scene_dur = sum(s.duration_seconds for s in scenes)
    logger.info("Scenes split in {:.1f}s", time.time() - t0)
    logger.info("Scene count: {}", len(scenes))
    for s in scenes:
        logger.info(
            "  Scene {}: {:.1f}s | type={} | narration='{}...'",
            s.scene_number,
            s.duration_seconds,
            s.visual_type,
            s.narration[:60],
        )
    logger.info(
        "Total scene duration: {:.1f}s (audio: {:.1f}s, diff: {:.2f}s)",
        total_scene_dur, audio_duration, total_scene_dur - audio_duration,
    )

    # ── Step 4: Create placeholder clips (mock Runway) ───────
    logger.info("\n[4/5] Creating placeholder clips (Runway MOCKED to save credits)...")
    logger.info("In production, Runway gen4.5 would generate these clips.")

    from app.core.config import get_settings
    settings = get_settings()
    media_dir = Path(settings.media_dir) / "e2e-test"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Use Pexels stock as stand-in for Runway (free, proves assembly works)
    from app.services.visual_service import fetch_clips

    stock_clips = await fetch_clips(
        queries=[s.stock_query for s in scenes],
        orientation="portrait",
        clips_per_query=1,
    )

    clip_paths = []
    for i, clip in enumerate(stock_clips):
        dest = media_dir / f"scene_{i+1}.mp4"
        shutil.copy2(str(clip), str(dest))
        clip_dur = probe_duration(dest)
        logger.info(
            "  Scene {}: {:.1f}s requested → stock placeholder {:.1f}s | query='{}'",
            scenes[i].scene_number,
            scenes[i].duration_seconds,
            clip_dur,
            scenes[i].stock_query,
        )
        clip_paths.append(dest)

    # ── Step 5: Assemble Final Video ─────────────────────────
    logger.info("\n[5/5] Assembling final video (FFmpeg)...")
    t0 = time.time()

    from app.services.media_service import assemble_video

    output_path = assemble_video(
        clip_paths=clip_paths,
        audio_path=audio_path,
        video_format=video_format,
        project_id="e2e-test",
    )

    final_duration = probe_duration(output_path)
    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Assembly complete in {:.1f}s", time.time() - t0)
    logger.info("Output: {}", output_path)
    logger.info("Duration: {:.1f}s", final_duration)
    logger.info("File size: {:.1f} MB", file_size_mb)

    # ── Summary ──────────────────────────────────────────────
    scene_audio_diff = abs(total_scene_dur - audio_duration)
    final_audio_diff = abs(final_duration - audio_duration)

    logger.info("\n" + "=" * 60)
    logger.info("E2E TEST RESULTS")
    logger.info("-" * 60)
    logger.info("  Script:         {} words", word_count)
    logger.info("  Audio duration: {:.1f}s", audio_duration)
    logger.info("  Scene durations: [{}]",
                ", ".join(f"{s.duration_seconds:.1f}s" for s in scenes))
    logger.info("  Scene total:    {:.1f}s (diff from audio: {:.2f}s)", total_scene_dur, scene_audio_diff)
    logger.info("  Final video:    {:.1f}s (diff from audio: {:.1f}s)", final_duration, final_audio_diff)
    logger.info("  Output file:    {}", output_path)
    logger.info("-" * 60)

    if scene_audio_diff < 0.2:
        logger.info("PASS — Scene durations perfectly match audio!")
    else:
        logger.warning("FAIL — Scene duration mismatch: {:.2f}s", scene_audio_diff)

    logger.info("=" * 60)
    logger.info("NOTE: Clips are stock placeholders. With Runway, each scene")
    logger.info("would be AI-generated at the exact duration shown above.")


if __name__ == "__main__":
    asyncio.run(main())
