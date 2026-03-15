"""
Thumbnail Service — generates AI-powered YouTube thumbnails via DALL-E.

Falls back to frame extraction if AI generation fails.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.core.config import get_settings


def generate_thumbnail_prompt(title: str, topic: str, mood: str = "uplifting") -> str:
    """Build a DALL-E prompt for an eye-catching YouTube thumbnail."""
    mood_styles = {
        "energetic": "vibrant neon colors, dynamic angle, bold contrast",
        "calm": "soft pastel tones, serene lighting, gentle gradient",
        "dramatic": "dark moody lighting, high contrast, cinematic shadows",
        "mysterious": "deep blues and purples, foggy atmosphere, enigmatic",
        "uplifting": "warm golden light, bright colors, optimistic feel",
        "dark": "noir-style deep shadows, desaturated, ominous atmosphere",
        "happy": "bright saturated colors, playful composition, joyful",
        "sad": "muted cool tones, soft rain or fog, melancholic",
        "epic": "sweeping wide angle, dramatic sky, grand scale",
        "chill": "lo-fi aesthetic, warm muted tones, relaxed vibes",
    }

    style = mood_styles.get(mood, mood_styles["uplifting"])

    prompt = (
        f"YouTube thumbnail for a video about '{topic}'. "
        f"Style: {style}. "
        "Professional, eye-catching, designed to maximize click-through rate. "
        "Bold visual composition, shallow depth of field, "
        "cinematic quality, no text or letters in the image. "
        "16:9 landscape aspect ratio, photorealistic."
    )
    return prompt[:3900]


async def generate_ai_thumbnail(
    title: str,
    topic: str,
    mood: str = "uplifting",
    project_id: str = "",
) -> Path:
    """Generate an AI thumbnail using DALL-E."""
    from app.services.image_gen_service import generate_scene_image

    prompt = generate_thumbnail_prompt(title, topic, mood)

    # Use landscape size for YouTube thumbnails (1792x1024)
    settings = get_settings()
    thumbnail_path = await generate_scene_image(
        prompt=prompt,
        size="1792x1024",
        model=settings.ai_images_model,
        quality=settings.ai_images_quality,
    )

    logger.info("AI thumbnail generated — project={} path={}", project_id, thumbnail_path)

    # Add text overlay if enabled
    if settings.ai_thumbnail_text_overlay and title:
        try:
            thumbnail_path = add_text_overlay(thumbnail_path, title)
        except Exception as exc:
            logger.warning("Text overlay failed, using plain thumbnail: {}", exc)

    return thumbnail_path


def add_text_overlay(image_path: Path, title: str) -> Path:
    """Add bold title text overlay on the thumbnail using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)

    # Use a large bold font
    font_size = max(40, img.width // 20)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    # Truncate title if too long
    display_title = title[:50].upper()

    # Calculate text position (center-bottom)
    bbox = draw.textbbox((0, 0), display_title, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (img.width - text_width) // 2
    y = img.height - text_height - 60

    # Draw shadow
    shadow_offset = 3
    draw.text((x + shadow_offset, y + shadow_offset), display_title, font=font, fill=(0, 0, 0, 200))
    # Draw main text
    draw.text((x, y), display_title, font=font, fill=(255, 255, 255, 255))

    # Save back
    output_path = image_path.with_name(f"{image_path.stem}_overlay{image_path.suffix}")
    img.save(output_path, quality=95)
    logger.info("Text overlay added — {}", output_path)
    return output_path
