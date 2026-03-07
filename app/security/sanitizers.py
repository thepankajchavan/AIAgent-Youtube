"""Input sanitization utilities to prevent injection attacks."""

import re
from pathlib import Path

from loguru import logger

# ── Prompt Injection Detection Patterns ──────────────────────────

PROMPT_INJECTION_PATTERNS = [
    # System/Assistant control attempts
    r"(?i)(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?|commands?)",
    r"(?i)(ignore|disregard|forget)\s+all",
    r"(?i)you\s+are\s+now\s+(a|an)\s+",
    r"(?i)(act|behave|pretend)\s+as\s+(if|a|an)\s+",
    r"(?i)new\s+(instructions?|rules?|context|role|personality)",
    r"(?i)override\s+(instructions?|rules?|settings?)",
    # XML/HTML-like instruction tags
    r"<\s*(system|assistant|user|instruction|prompt|role)\s*>",
    r"\[INST\]|\[\/INST\]",
    r"\{\s*(system|assistant|user)\s*:",
    # JSON/structured injection
    r'"(role|content|system|assistant)"\s*:\s*"',
    # Jailbreak patterns
    r"(?i)(developer\s+mode|god\s+mode|admin\s+mode|debug\s+mode)",
    r"(?i)(jailbreak|unrestrict|bypass|escape)\s+(mode|filter|safety)",
    # Prompt leaking attempts
    r"(?i)(show|reveal|display|print|output)\s+(your|the)\s+(prompt|instructions?|rules?|system\s+message)",
]

# Compile patterns for performance
INJECTION_REGEXES = [re.compile(pattern) for pattern in PROMPT_INJECTION_PATTERNS]


def sanitize_topic(topic: str, max_length: int = 200) -> str:
    """
    Sanitize user-provided video topic to prevent prompt injection.

    Security measures:
    1. Character whitelisting (alphanumeric + basic punctuation)
    2. Prompt injection pattern detection
    3. Length limiting
    4. XML tag wrapping for LLM clarity

    Args:
        topic: User-provided topic string
        max_length: Maximum allowed length (default: 200)

    Returns:
        Sanitized topic wrapped in <user_input> tags

    Raises:
        ValueError: If topic contains suspicious patterns or invalid characters
    """
    if not topic or not topic.strip():
        raise ValueError("Topic cannot be empty")

    topic = topic.strip()

    # 1. Length validation
    if len(topic) > max_length:
        raise ValueError(f"Topic too long (max {max_length} characters)")

    # 1b. Normalize common Unicode characters to ASCII equivalents
    _unicode_replacements = {
        "\u2014": "-",  # em dash → hyphen
        "\u2013": "-",  # en dash → hyphen
        "\u2018": "'",  # left single quote → apostrophe
        "\u2019": "'",  # right single quote → apostrophe
        "\u201c": '"',  # left double quote → double quote
        "\u201d": '"',  # right double quote → double quote
        "\u2026": "...",  # ellipsis → three dots
        "\u00a0": " ",  # non-breaking space → space
    }
    for char, replacement in _unicode_replacements.items():
        topic = topic.replace(char, replacement)

    # 2. Character whitelist validation
    # Allow: letters, numbers, spaces, basic punctuation
    allowed_chars = re.compile(r'^[a-zA-Z0-9\s\-_,.!?\'"()/:;&#%@+]+$')
    if not allowed_chars.match(topic):
        logger.warning(f"Topic contains invalid characters: {topic[:50]}...")
        raise ValueError(
            "Topic contains invalid characters. "
            "Only letters, numbers, spaces, and basic punctuation (.,!?'-_()) are allowed."
        )

    # 3. Prompt injection detection
    for pattern in INJECTION_REGEXES:
        if pattern.search(topic):
            logger.warning(f"Potential prompt injection detected: {topic[:50]}...")
            raise ValueError(
                "Topic contains suspicious patterns. "
                "Please rephrase without special instructions or system commands."
            )

    # 4. Wrap in XML tags for LLM clarity
    # This helps the LLM distinguish user input from system instructions
    sanitized = f"<user_input>{topic}</user_input>"

    logger.debug(f"Sanitized topic: {topic[:50]}...")
    return sanitized


def validate_file_path(file_path: Path, allowed_directory: Path) -> Path:
    """
    Validate file path to prevent directory traversal attacks.

    Security measures:
    1. Resolves symlinks and relative paths
    2. Ensures path is within allowed directory
    3. Prevents path traversal (e.g., ../../../etc/passwd)

    Args:
        file_path: Path to validate
        allowed_directory: Root directory that contains allowed paths

    Returns:
        Resolved absolute path

    Raises:
        ValueError: If path is outside allowed directory

    Example:
        >>> media_dir = Path("/app/media")
        >>> validate_file_path(Path("../etc/passwd"), media_dir)
        ValueError: Path traversal detected

        >>> validate_file_path(Path("output/video.mp4"), media_dir)
        Path("/app/media/output/video.mp4")
    """
    # Resolve to absolute path (follows symlinks)
    resolved_path = file_path.resolve()
    resolved_allowed = allowed_directory.resolve()

    # Check if resolved path is within allowed directory
    try:
        resolved_path.relative_to(resolved_allowed)
    except ValueError:
        logger.warning(
            f"Path traversal attempt detected: {file_path} "
            f"(resolved to {resolved_path}, allowed: {resolved_allowed})"
        )
        raise ValueError(f"Path traversal detected. Path must be within {allowed_directory}")

    logger.debug(f"Validated path: {resolved_path}")
    return resolved_path


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize filename to prevent directory traversal and special character issues.

    Security measures:
    1. Remove path separators
    2. Remove null bytes and control characters
    3. Whitelist safe characters
    4. Prevent reserved names (Windows)

    Args:
        filename: Proposed filename
        max_length: Maximum allowed length (default: 255)

    Returns:
        Sanitized filename

    Raises:
        ValueError: If filename is invalid or becomes empty after sanitization
    """
    if not filename or not filename.strip():
        raise ValueError("Filename cannot be empty")

    # Remove path separators
    filename = filename.replace("/", "_").replace("\\", "_")

    # Remove null bytes and control characters
    filename = "".join(char for char in filename if ord(char) >= 32 and char != "\x7f")

    # Whitelist safe characters (alphanumeric + basic punctuation, no spaces to avoid issues)
    safe_chars = re.compile(r"[^a-zA-Z0-9._-]")
    filename = safe_chars.sub("_", filename)

    # Remove leading/trailing dots and underscores
    filename = filename.strip("._")

    # Check length
    if len(filename) > max_length:
        # Preserve extension
        name, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        max_name_len = max_length - len(ext) - 1 if ext else max_length
        filename = f"{name[:max_name_len]}.{ext}" if ext else name[:max_length]

    # Check for reserved names (Windows)
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    base_name = filename.rsplit(".", 1)[0].upper() if "." in filename else filename.upper()
    if base_name in reserved_names:
        filename = f"file_{filename}"

    if not filename:
        raise ValueError("Filename becomes empty after sanitization")

    logger.debug(f"Sanitized filename: {filename}")
    return filename
