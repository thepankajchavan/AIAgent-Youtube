"""
Transition Service — video transition registry and position-aware selection.

Provides 12 FFmpeg xfade transition types with intelligent scene-position-aware
selection and configurable duration calculation.
"""

from __future__ import annotations

from app.core.config import get_settings

# ── Available FFmpeg xfade transitions ───────────────────────────

AVAILABLE_TRANSITIONS: list[str] = [
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "circlecrop",
    "radial",
    "smoothleft",
    "smoothright",
]

# Position-aware cycle for "auto" mode — designed for visual variety
# and narrative flow across 5-6 scene videos
_AUTO_CYCLE: list[str] = [
    "fade",          # Scene 1→2: clean opening
    "smoothright",   # Scene 2→3: directional momentum
    "dissolve",      # Scene 3→4: smooth blend
    "slideleft",     # Scene 4→5: energy shift
    "circlecrop",    # Scene 5→6: dramatic focal point
    "wiperight",     # Scene 6→7: lateral energy
    "radial",        # Scene 7→8: radiating outward
    "smoothleft",    # Scene 8→9: reverse momentum
]


def select_transitions(num_clips: int, style: str = "auto") -> list[str]:
    """Select transition types for each clip boundary.

    Args:
        num_clips: Total number of video clips.
        style: Transition style — "auto" for position-aware cycling,
               or a specific type name for uniform transitions.

    Returns:
        List of (num_clips - 1) transition names, one per boundary.
    """
    if num_clips < 2:
        return []

    num_transitions = num_clips - 1

    if style == "auto":
        # Cycle through the position-aware sequence
        return [_AUTO_CYCLE[i % len(_AUTO_CYCLE)] for i in range(num_transitions)]

    if style == "uniform":
        # Use "fade" for all transitions
        return ["fade"] * num_transitions

    # Specific type: validate and use uniformly
    if style in AVAILABLE_TRANSITIONS:
        return [style] * num_transitions

    # Unknown style — fall back to fade
    return ["fade"] * num_transitions


def select_durations(
    num_clips: int,
    base_duration: float = 0.3,
    duration_min: float = 0.2,
    duration_max: float = 0.8,
) -> list[float]:
    """Calculate per-transition durations with positional variation.

    First transition is shorter (snappy entry), last is longer (dramatic finish),
    middle transitions use the base duration.

    Args:
        num_clips: Total number of video clips.
        base_duration: Default transition duration in seconds.
        duration_min: Minimum allowed duration.
        duration_max: Maximum allowed duration.

    Returns:
        List of (num_clips - 1) durations.
    """
    if num_clips < 2:
        return []

    num_transitions = num_clips - 1

    if num_transitions == 1:
        return [max(duration_min, min(base_duration, duration_max))]

    durations: list[float] = []
    for i in range(num_transitions):
        if i == 0:
            # First transition: slightly shorter for snappy entry
            dur = base_duration * 0.7
        elif i == num_transitions - 1:
            # Last transition: longer for dramatic finish
            dur = base_duration * 1.5
        else:
            dur = base_duration

        # Clamp to bounds
        dur = max(duration_min, min(dur, duration_max))
        durations.append(round(dur, 2))

    return durations


def build_transitions_from_config() -> tuple[list[str] | None, list[float] | None]:
    """Read transition config from settings and return (transitions, durations).

    Returns (None, None) if transitions are disabled.
    """
    s = get_settings()

    if not getattr(s, "transitions_enabled", True):
        return None, None

    style = getattr(s, "transition_style", "auto")
    base_dur = getattr(s, "transition_duration", 0.3)
    dur_min = getattr(s, "transition_duration_min", 0.2)
    dur_max = getattr(s, "transition_duration_max", 0.8)

    # We need num_clips to compute — caller provides this
    # Return the config values for the caller to use
    return style, base_dur  # type: ignore[return-value]


def compute_transitions_for_clips(
    num_clips: int,
    style_override: str | None = None,
) -> tuple[list[str] | None, list[float] | None]:
    """Compute transitions and durations for a given number of clips.

    Args:
        num_clips: Total number of video clips.
        style_override: Override the config transition_style (e.g. from mood glue).

    Reads settings and returns fully computed lists, or (None, None) if disabled.
    """
    s = get_settings()

    if not getattr(s, "transitions_enabled", True):
        return None, None

    style = style_override or getattr(s, "transition_style", "auto")
    base_dur = getattr(s, "transition_duration", 0.3)
    dur_min = getattr(s, "transition_duration_min", 0.2)
    dur_max = getattr(s, "transition_duration_max", 0.8)

    transitions = select_transitions(num_clips, style)
    durations = select_durations(num_clips, base_dur, dur_min, dur_max)

    return transitions, durations
