"""Unit tests for YouTube service with mocked Google API."""

import json
from unittest.mock import MagicMock

import pytest

from app.services.youtube_service import (
    _read_token,
    _write_token,
    upload_video,
)


class TestTokenReadWrite:
    """Test OAuth token reading and writing with encryption."""

    def test_read_token_encrypted(self, mocker, tmp_path):
        """Test reading encrypted token file."""
        token_path = tmp_path / "youtube_token.json"
        encrypted_path = tmp_path / "youtube_token.json.encrypted"

        # Create encrypted token file
        encrypted_path.write_text("encrypted_token_data")

        # Mock decrypt_string
        mock_decrypt = mocker.patch(
            "app.services.youtube_service.decrypt_string",
            return_value='{"token": "decrypted_value"}',
        )

        result = _read_token(token_path)

        assert result == '{"token": "decrypted_value"}'
        mock_decrypt.assert_called_once_with("encrypted_token_data")

    def test_read_token_plaintext_fallback(self, mocker, tmp_path):
        """Test reading plaintext token when encrypted doesn't exist."""
        token_path = tmp_path / "youtube_token.json"
        plaintext_token = '{"token": "plaintext_value"}'
        token_path.write_text(plaintext_token)

        result = _read_token(token_path)

        assert result == plaintext_token

    def test_read_token_not_found(self, tmp_path):
        """Test reading token when neither file exists."""
        token_path = tmp_path / "nonexistent_token.json"

        result = _read_token(token_path)

        assert result is None

    def test_read_token_decryption_failure(self, mocker, tmp_path):
        """Test that decryption failures raise ValueError."""
        token_path = tmp_path / "youtube_token.json"
        encrypted_path = tmp_path / "youtube_token.json.encrypted"
        encrypted_path.write_text("corrupted_data")

        # Mock decrypt_string to raise exception
        mocker.patch(
            "app.services.youtube_service.decrypt_string",
            side_effect=ValueError("Decryption failed"),
        )

        with pytest.raises(ValueError, match="Failed to decrypt YouTube token"):
            _read_token(token_path)

    def test_write_token_encrypted(self, mocker, tmp_path):
        """Test writing encrypted token file."""
        token_path = tmp_path / "youtube_token.json"
        encrypted_path = tmp_path / "youtube_token.json.encrypted"
        token_json = '{"token": "secret_token"}'

        # Mock encrypt_string
        mocker.patch(
            "app.services.youtube_service.encrypt_string", return_value="encrypted_token_data"
        )

        _write_token(token_path, token_json)

        # Verify encrypted file was created
        assert encrypted_path.exists()
        assert encrypted_path.read_text() == "encrypted_token_data"

        # Verify plaintext file doesn't exist
        assert not token_path.exists()

    def test_write_token_removes_existing_plaintext(self, mocker, tmp_path):
        """Test that existing plaintext token is removed when encrypting."""
        token_path = tmp_path / "youtube_token.json"
        encrypted_path = tmp_path / "youtube_token.json.encrypted"

        # Create existing plaintext token
        token_path.write_text('{"old": "token"}')

        # Mock encryption
        mocker.patch(
            "app.services.youtube_service.encrypt_string", return_value="new_encrypted_data"
        )

        _write_token(token_path, '{"new": "token"}')

        # Verify plaintext was removed
        assert not token_path.exists()
        assert encrypted_path.exists()

    def test_write_token_plaintext_fallback(self, mocker, tmp_path):
        """Test writing plaintext when encryption key not configured."""
        token_path = tmp_path / "youtube_token.json"
        token_json = '{"token": "value"}'

        # Mock encrypt_string to raise ValueError (no encryption key)
        mocker.patch(
            "app.services.youtube_service.encrypt_string",
            side_effect=ValueError("ENCRYPTION_KEY not configured"),
        )

        _write_token(token_path, token_json)

        # Verify plaintext file was created
        assert token_path.exists()
        assert token_path.read_text() == token_json


class TestVideoUpload:
    """Test YouTube video upload with mocked Google API."""

    def test_upload_video_success(self, mocker, tmp_path):
        """Test successful video upload to YouTube."""
        # Create fake video file
        video_path = tmp_path / "test_video.mp4"
        video_path.write_bytes(b"fake_video_data")

        # Mock authenticated service
        mock_youtube = MagicMock()
        mock_request = MagicMock()

        # Mock resumable upload (no chunks needed for test)
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "abc123"}))

        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        # Upload video
        result = upload_video(
            file_path=video_path,
            title="Test Video",
            description="Test description",
            tags=["test", "video"],
            category="education",
            privacy_status="private",
        )

        # Verify result
        assert result["video_id"] == "abc123"
        assert result["url"] == "https://www.youtube.com/watch?v=abc123"

        # Verify API call
        mock_youtube.videos().insert.assert_called_once()
        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        assert call_kwargs["body"]["snippet"]["title"] == "Test Video #Shorts"
        assert call_kwargs["body"]["snippet"]["categoryId"] == "27"  # Education
        assert call_kwargs["body"]["status"]["privacyStatus"] == "private"

    def test_upload_video_adds_shorts_tag(self, mocker, tmp_path):
        """Test that #Shorts tag is added for shorts."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "xyz789"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        upload_video(
            file_path=video_path,
            title="Amazing Facts",
            description="Test",
            tags=["facts"],
            is_short=True,
        )

        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        # Verify #Shorts in title
        assert "#Shorts" in call_kwargs["body"]["snippet"]["title"]
        # Verify #Shorts in tags
        assert "#Shorts" in call_kwargs["body"]["snippet"]["tags"]

    def test_upload_video_no_shorts_tag_for_long_format(self, mocker, tmp_path):
        """Test that #Shorts tag is not added for long videos."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "xyz789"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        upload_video(
            file_path=video_path,
            title="Documentary",
            description="Test",
            tags=["documentary"],
            is_short=False,
        )

        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        title = call_kwargs["body"]["snippet"]["title"]
        tags = call_kwargs["body"]["snippet"]["tags"]

        # Should not have #Shorts
        assert "#Shorts" not in title
        assert "#Shorts" not in tags

    def test_upload_video_truncates_long_title(self, mocker, tmp_path):
        """Test that titles longer than 100 chars are truncated."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "abc"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        long_title = "A" * 150  # 150 chars

        upload_video(
            file_path=video_path,
            title=long_title,
            description="Test",
            tags=["test"],
            is_short=False,
        )

        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        result_title = call_kwargs["body"]["snippet"]["title"]

        # Should be truncated to 100 chars
        assert len(result_title) <= 100

    def test_upload_video_category_mapping(self, mocker, tmp_path):
        """Test that category names are mapped to YouTube category IDs."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "abc"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        # Test different categories
        categories_map = {
            "entertainment": "24",
            "education": "27",
            "science": "28",
            "gaming": "20",
            "unknown_category": "24",  # Default fallback
        }

        for category_name, expected_id in categories_map.items():
            upload_video(
                file_path=video_path,
                title="Test",
                description="Test",
                tags=["test"],
                category=category_name,
                is_short=False,
            )

            call_kwargs = mock_youtube.videos().insert.call_args.kwargs
            assert call_kwargs["body"]["snippet"]["categoryId"] == expected_id

    def test_upload_video_file_not_found(self, mocker):
        """Test that missing video file raises error (wrapped by tenacity after retries)."""
        from tenacity import RetryError

        with pytest.raises((FileNotFoundError, RetryError)):
            upload_video(
                file_path="/nonexistent/video.mp4", title="Test", description="Test", tags=["test"]
            )

    def test_upload_video_with_progress_logging(self, mocker, tmp_path):
        """Test that upload progress is logged correctly."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()

        # Simulate resumable upload with 3 chunks
        mock_status_1 = MagicMock()
        mock_status_1.progress.return_value = 0.33

        mock_status_2 = MagicMock()
        mock_status_2.progress.return_value = 0.66

        mock_request.next_chunk = MagicMock(
            side_effect=[
                (mock_status_1, None),  # First chunk
                (mock_status_2, None),  # Second chunk
                (None, {"id": "abc123"}),  # Final response
            ]
        )

        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        result = upload_video(
            file_path=video_path, title="Test", description="Test", tags=["test"], is_short=False
        )

        # Verify all chunks were processed
        assert mock_request.next_chunk.call_count == 3
        assert result["video_id"] == "abc123"

    def test_upload_video_sets_made_for_kids_false(self, mocker, tmp_path):
        """Test that selfDeclaredMadeForKids is set to False."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "abc"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        upload_video(file_path=video_path, title="Test", description="Test", tags=["test"])

        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        assert call_kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False

    def test_upload_video_appends_hashtags_to_description(self, mocker, tmp_path):
        """Test that hashtags are appended to the description."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "abc"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        upload_video(
            file_path=video_path,
            title="Test",
            description="Original description.",
            tags=["test"],
            hashtags=["#Shorts", "#Science", "#Facts"],
        )

        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        desc = call_kwargs["body"]["snippet"]["description"]
        assert desc.startswith("Original description.")
        # Hashtags are reordered: #Shorts moves to end (YouTube shows last 3 above title)
        assert "#Science" in desc
        assert "#Facts" in desc
        assert "#Shorts" in desc
        assert desc.rstrip().endswith("#Shorts")

    def test_upload_video_no_hashtags(self, mocker, tmp_path):
        """Test that description is unchanged when no hashtags provided."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "abc"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        upload_video(
            file_path=video_path,
            title="Test",
            description="Just a description.",
            tags=["test"],
        )

        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        desc = call_kwargs["body"]["snippet"]["description"]
        assert desc == "Just a description."

    def test_upload_video_public_privacy(self, mocker, tmp_path):
        """Test that public privacy status is set correctly."""
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"data")

        mock_youtube = MagicMock()
        mock_request = MagicMock()
        mock_request.next_chunk = MagicMock(return_value=(None, {"id": "abc"}))
        mock_youtube.videos().insert.return_value = mock_request

        mocker.patch(
            "app.services.youtube_service._get_authenticated_service", return_value=mock_youtube
        )

        upload_video(
            file_path=video_path,
            title="Public Video",
            description="Test",
            tags=["test"],
            privacy_status="public",
        )

        call_kwargs = mock_youtube.videos().insert.call_args.kwargs
        assert call_kwargs["body"]["status"]["privacyStatus"] == "public"


class TestAuthenticatedService:
    """Test OAuth authentication flow."""

    def test_get_authenticated_service_with_valid_token(self, mocker, tmp_path):
        """Test that valid cached credentials are used."""
        from app.services.youtube_service import _get_authenticated_service

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.youtube_token_file = str(tmp_path / "token.json")
        mock_settings.youtube_client_secrets_file = str(tmp_path / "secrets.json")
        mocker.patch("app.services.youtube_service.settings", mock_settings)

        # Mock token file with valid credentials
        valid_token = {
            "token": "valid_access_token",
            "refresh_token": "valid_refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        }

        mocker.patch(
            "app.services.youtube_service._read_token", return_value=json.dumps(valid_token)
        )

        # Mock Credentials
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.to_json.return_value = json.dumps(valid_token)

        mocker.patch(
            "app.services.youtube_service.Credentials.from_authorized_user_info",
            return_value=mock_creds,
        )

        # Mock build
        mock_youtube = MagicMock()
        mocker.patch("app.services.youtube_service.build", return_value=mock_youtube)

        result = _get_authenticated_service()

        assert result == mock_youtube

    def test_get_authenticated_service_refreshes_expired_token(self, mocker, tmp_path):
        """Test that expired tokens are refreshed."""
        from app.services.youtube_service import _get_authenticated_service

        mock_settings = MagicMock()
        mock_settings.youtube_token_file = str(tmp_path / "token.json")
        mocker.patch("app.services.youtube_service.settings", mock_settings)

        valid_token = {"token": "old_token", "refresh_token": "refresh"}

        mocker.patch(
            "app.services.youtube_service._read_token", return_value=json.dumps(valid_token)
        )

        # Mock expired credentials
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"
        mock_creds.to_json.return_value = json.dumps({"token": "new_token"})

        mocker.patch(
            "app.services.youtube_service.Credentials.from_authorized_user_info",
            return_value=mock_creds,
        )

        # Mock refresh
        mock_creds.refresh = MagicMock()

        # Mock token writing
        mock_write = mocker.patch("app.services.youtube_service._write_token")

        # Mock build
        mock_youtube = MagicMock()
        mocker.patch("app.services.youtube_service.build", return_value=mock_youtube)

        _get_authenticated_service()

        # Verify refresh was called
        mock_creds.refresh.assert_called_once()

        # Verify new token was saved
        mock_write.assert_called_once()
