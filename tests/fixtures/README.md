# Test Fixtures

This directory contains sample media files for testing.

## Generating Fixture Files

To generate the actual media files, run inside Docker (where FFmpeg is available):

```bash
docker compose exec api python tests/generate_fixtures.py
```

Or manually with FFmpeg:

```bash
# Generate 1-second silent audio
ffmpeg -f lavfi -i anullsrc=duration=1.0 -c:a libmp3lame tests/fixtures/sample_audio.mp3

# Generate 1-second black video (1080x1920 for Shorts)
ffmpeg -f lavfi -i color=black:s=1080x1920:d=1.0 -c:v libx264 -pix_fmt yuv420p tests/fixtures/sample_video.mp4
```

## Files

- `sample_script.json` - Mock LLM response for testing
- `sample_audio.mp3` - 1-second silent audio file
- `sample_video.mp4` - 1-second black video file (9:16 format)
