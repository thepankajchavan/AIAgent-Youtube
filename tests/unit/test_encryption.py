"""Unit tests for encryption utilities."""

import pytest

from app.core.encryption import (
    decrypt_file,
    decrypt_json,
    decrypt_string,
    encrypt_file,
    encrypt_json,
    encrypt_string,
    generate_key,
)
from app.core.encryption import (
    settings as encryption_settings,
)


@pytest.fixture
def set_encryption_key(monkeypatch):
    """Set a valid encryption key on the cached settings object."""

    def _set(key: str):
        monkeypatch.setattr(encryption_settings, "encryption_key", key)

    return _set


class TestStringEncryption:
    """Test string encryption and decryption."""

    def test_encrypt_decrypt_string(self, set_encryption_key):
        """Test that encrypted string can be decrypted back."""
        test_key = generate_key()
        set_encryption_key(test_key)

        plaintext = "This is a secret message"
        encrypted = encrypt_string(plaintext)

        # Encrypted should be different from plaintext
        assert encrypted != plaintext
        assert len(encrypted) > len(plaintext)

        # Decrypt should return original
        decrypted = decrypt_string(encrypted)
        assert decrypted == plaintext

    def test_encrypt_empty_string(self, set_encryption_key):
        """Test encrypting empty string."""
        test_key = generate_key()
        set_encryption_key(test_key)

        encrypted = encrypt_string("")
        decrypted = decrypt_string(encrypted)
        assert decrypted == ""

    def test_encrypt_unicode_string(self, set_encryption_key):
        """Test encrypting Unicode characters."""
        test_key = generate_key()
        set_encryption_key(test_key)

        plaintext = "Hello 世界 🌍"
        encrypted = encrypt_string(plaintext)
        decrypted = decrypt_string(encrypted)
        assert decrypted == plaintext

    def test_decrypt_with_wrong_key_fails(self, set_encryption_key):
        """Test that decryption fails with wrong key."""
        # Encrypt with one key
        key1 = generate_key()
        set_encryption_key(key1)
        encrypted = encrypt_string("secret")

        # Try to decrypt with different key
        key2 = generate_key()
        set_encryption_key(key2)

        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_string(encrypted)

    def test_decrypt_corrupted_data_fails(self, set_encryption_key):
        """Test that decryption fails with corrupted data."""
        test_key = generate_key()
        set_encryption_key(test_key)

        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_string("corrupted_data_not_valid_base64")

    def test_missing_encryption_key_raises_error(self, set_encryption_key):
        """Test that missing encryption key raises error."""
        set_encryption_key("")

        with pytest.raises(ValueError, match="ENCRYPTION_KEY not configured"):
            encrypt_string("test")


class TestJSONEncryption:
    """Test JSON encryption and decryption."""

    def test_encrypt_decrypt_json(self, set_encryption_key):
        """Test that encrypted JSON can be decrypted back."""
        test_key = generate_key()
        set_encryption_key(test_key)

        data = {"token": "secret_token", "user_id": 12345, "nested": {"key": "value"}}

        encrypted = encrypt_json(data)
        decrypted = decrypt_json(encrypted)

        assert decrypted == data

    def test_encrypt_empty_dict(self, set_encryption_key):
        """Test encrypting empty dictionary."""
        test_key = generate_key()
        set_encryption_key(test_key)

        data = {}
        encrypted = encrypt_json(data)
        decrypted = decrypt_json(encrypted)
        assert decrypted == data

    def test_encrypt_complex_json(self, set_encryption_key):
        """Test encrypting complex nested JSON."""
        test_key = generate_key()
        set_encryption_key(test_key)

        data = {
            "array": [1, 2, 3],
            "nested": {"deep": {"value": "test"}},
            "unicode": "测试",
            "bool": True,
            "null": None,
        }

        encrypted = encrypt_json(data)
        decrypted = decrypt_json(encrypted)
        assert decrypted == data

    def test_decrypt_invalid_json_fails(self, set_encryption_key):
        """Test that decrypting invalid JSON fails."""
        test_key = generate_key()
        set_encryption_key(test_key)

        # Encrypt non-JSON string
        encrypted = encrypt_string("not valid json {")

        with pytest.raises(ValueError, match="not valid JSON"):
            decrypt_json(encrypted)


class TestFileEncryption:
    """Test file encryption and decryption."""

    def test_encrypt_decrypt_file(self, tmp_path, set_encryption_key):
        """Test that encrypted file can be decrypted back."""
        test_key = generate_key()
        set_encryption_key(test_key)

        # Create test file
        input_file = tmp_path / "plaintext.txt"
        plaintext = b"This is secret file content"
        input_file.write_bytes(plaintext)

        # Encrypt
        encrypted_file = tmp_path / "encrypted.bin"
        result = encrypt_file(input_file, encrypted_file)
        assert result == encrypted_file
        assert encrypted_file.exists()

        # Encrypted content should be different
        encrypted_content = encrypted_file.read_bytes()
        assert encrypted_content != plaintext

        # Decrypt
        decrypted_file = tmp_path / "decrypted.txt"
        decrypt_file(encrypted_file, decrypted_file)
        assert decrypted_file.exists()

        # Decrypted should match original
        decrypted_content = decrypted_file.read_bytes()
        assert decrypted_content == plaintext

    def test_encrypt_file_default_output_path(self, tmp_path, set_encryption_key):
        """Test file encryption with default output path."""
        test_key = generate_key()
        set_encryption_key(test_key)

        input_file = tmp_path / "test.txt"
        input_file.write_bytes(b"content")

        # Encrypt without specifying output path
        result = encrypt_file(input_file)
        expected_path = tmp_path / "test.txt.encrypted"
        assert result == expected_path
        assert expected_path.exists()

    def test_decrypt_file_default_output_path(self, tmp_path, set_encryption_key):
        """Test file decryption with default output path."""
        test_key = generate_key()
        set_encryption_key(test_key)

        # Create and encrypt file
        input_file = tmp_path / "test.txt"
        input_file.write_bytes(b"content")
        encrypted_file = encrypt_file(input_file)

        # Decrypt without specifying output path
        result = decrypt_file(encrypted_file)
        expected_path = tmp_path / "test.txt"
        assert result == expected_path
        assert expected_path.exists()

    def test_decrypt_file_with_wrong_key_fails(self, tmp_path, set_encryption_key):
        """Test that decryption fails with wrong key."""
        # Encrypt with one key
        key1 = generate_key()
        set_encryption_key(key1)

        input_file = tmp_path / "test.txt"
        input_file.write_bytes(b"secret")
        encrypted_file = encrypt_file(input_file)

        # Try to decrypt with different key
        key2 = generate_key()
        set_encryption_key(key2)

        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_file(encrypted_file)


class TestKeyGeneration:
    """Test encryption key generation."""

    def test_generate_key_returns_string(self):
        """Test that generate_key returns a string."""
        key = generate_key()
        assert isinstance(key, str)
        assert len(key) > 0

    def test_generate_key_produces_unique_keys(self):
        """Test that multiple calls produce different keys."""
        key1 = generate_key()
        key2 = generate_key()
        assert key1 != key2

    def test_generated_key_is_valid_fernet_key(self):
        """Test that generated key can be used for encryption."""
        from cryptography.fernet import Fernet

        key = generate_key()
        # Should not raise exception
        fernet = Fernet(key.encode())
        assert fernet is not None
