"""Encryption utilities for sensitive data using Fernet (AES-128 CBC)."""

import json
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


def get_encryption_key() -> bytes:
    """
    Get encryption key from environment.

    Raises:
        ValueError: If ENCRYPTION_KEY is not configured
    """
    key_str = getattr(settings, 'encryption_key', None)

    if not key_str:
        raise ValueError(
            "ENCRYPTION_KEY not configured. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )

    return key_str.encode()


def encrypt_string(plaintext: str) -> str:
    """
    Encrypt a string using Fernet.

    Args:
        plaintext: String to encrypt

    Returns:
        Base64-encoded encrypted string
    """
    key = get_encryption_key()
    fernet = Fernet(key)

    encrypted = fernet.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_string(ciphertext: str) -> str:
    """
    Decrypt a Fernet-encrypted string.

    Args:
        ciphertext: Base64-encoded encrypted string

    Returns:
        Decrypted plaintext string

    Raises:
        InvalidToken: If decryption fails (wrong key or corrupted data)
    """
    key = get_encryption_key()
    fernet = Fernet(key)

    try:
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
    except InvalidToken as e:
        logger.error("Failed to decrypt string - invalid token or wrong key")
        raise ValueError("Decryption failed - invalid token or wrong encryption key") from e


def encrypt_json(data: dict) -> str:
    """
    Encrypt a dictionary as JSON.

    Args:
        data: Dictionary to encrypt

    Returns:
        Base64-encoded encrypted JSON string
    """
    json_str = json.dumps(data)
    return encrypt_string(json_str)


def decrypt_json(ciphertext: str) -> dict:
    """
    Decrypt and parse encrypted JSON.

    Args:
        ciphertext: Base64-encoded encrypted JSON string

    Returns:
        Decrypted dictionary

    Raises:
        ValueError: If decryption fails or JSON is invalid
    """
    json_str = decrypt_string(ciphertext)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse decrypted JSON")
        raise ValueError("Decrypted data is not valid JSON") from e


def encrypt_file(input_path: Path, output_path: Path | None = None) -> Path:
    """
    Encrypt a file using Fernet.

    Args:
        input_path: Path to plaintext file
        output_path: Path to save encrypted file (default: input_path + '.encrypted')

    Returns:
        Path to encrypted file
    """
    key = get_encryption_key()
    fernet = Fernet(key)

    if output_path is None:
        output_path = input_path.with_suffix(input_path.suffix + '.encrypted')

    # Read plaintext
    plaintext = input_path.read_bytes()

    # Encrypt
    ciphertext = fernet.encrypt(plaintext)

    # Write encrypted file
    output_path.write_bytes(ciphertext)

    logger.info(f"Encrypted {input_path} → {output_path}")
    return output_path


def decrypt_file(input_path: Path, output_path: Path | None = None) -> Path:
    """
    Decrypt a Fernet-encrypted file.

    Args:
        input_path: Path to encrypted file
        output_path: Path to save decrypted file (default: remove '.encrypted' suffix)

    Returns:
        Path to decrypted file

    Raises:
        InvalidToken: If decryption fails
    """
    key = get_encryption_key()
    fernet = Fernet(key)

    if output_path is None:
        # Remove .encrypted suffix if present
        if input_path.suffix == '.encrypted':
            output_path = input_path.with_suffix('')
        else:
            output_path = input_path.with_suffix('.decrypted')

    # Read ciphertext
    ciphertext = input_path.read_bytes()

    try:
        # Decrypt
        plaintext = fernet.decrypt(ciphertext)

        # Write decrypted file
        output_path.write_bytes(plaintext)

        logger.info(f"Decrypted {input_path} → {output_path}")
        return output_path

    except InvalidToken as e:
        logger.error(f"Failed to decrypt {input_path} - invalid token or wrong key")
        raise ValueError(f"Decryption failed for {input_path} - invalid token or wrong encryption key") from e


def generate_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        Base64-encoded Fernet key (safe to store in environment variables)
    """
    return Fernet.generate_key().decode()
