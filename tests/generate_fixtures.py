"""Generate test fixture media files."""

from pathlib import Path

from utils import create_mock_audio, create_mock_video


def main():
    """Generate fixture files."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    print("Generating test fixture media files...")

    # Generate 1-second silent audio
    audio_path = fixtures_dir / "sample_audio.mp3"
    print(f"Creating {audio_path}...")
    create_mock_audio(audio_path, duration_seconds=1.0)
    print(f"  Created: {audio_path} ({audio_path.stat().st_size} bytes)")

    # Generate 1-second black video (9:16 Shorts format)
    video_path = fixtures_dir / "sample_video.mp4"
    print(f"Creating {video_path}...")
    create_mock_video(video_path, duration_seconds=1.0, width=1080, height=1920)
    print(f"  Created: {video_path} ({video_path.stat().st_size} bytes)")

    print("\n[SUCCESS] All fixture files generated!")


if __name__ == "__main__":
    main()
