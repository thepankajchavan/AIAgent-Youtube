"""Unit tests for database models."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.api_key import APIKey
from app.models.base import Base
from app.models.telegram_user import TelegramUser
from app.models.video import VideoFormat, VideoProject, VideoStatus


@pytest.fixture(scope="module")
def test_db_engine():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(test_db_engine):
    """Create a fresh database session for each test."""
    SessionLocal = sessionmaker(bind=test_db_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


class TestVideoProject:
    """Test VideoProject model CRUD operations and state transitions."""

    def test_create_video_project(self, db_session):
        """Test creating a new video project."""
        project = VideoProject(
            topic="5 facts about space", format=VideoFormat.SHORT, provider="openai"
        )

        db_session.add(project)
        db_session.commit()

        # Verify defaults
        assert project.id is not None
        assert project.status == VideoStatus.PENDING
        assert project.format == VideoFormat.SHORT
        assert project.created_at is not None
        assert project.updated_at is not None
        assert project.script is None
        assert project.audio_path is None

    def test_video_project_repr(self, db_session):
        """Test VideoProject string representation."""
        project = VideoProject(topic="Test topic for representation")
        db_session.add(project)
        db_session.commit()

        repr_str = repr(project)
        assert "VideoProject" in repr_str
        assert "Test topic for representation" in repr_str
        assert "pending" in repr_str

    def test_video_project_timestamps(self, db_session):
        """Test that timestamps are automatically managed."""
        project = VideoProject(topic="Test timestamps")
        db_session.add(project)
        db_session.commit()

        created_at = project.created_at
        updated_at = project.updated_at

        assert created_at is not None
        assert updated_at is not None

        # Update project
        project.status = VideoStatus.SCRIPT_GENERATING
        db_session.commit()

        # created_at should not change
        assert project.created_at == created_at
        # updated_at should be set (>= original, may be same second in SQLite)
        assert project.updated_at >= updated_at

    def test_video_project_status_enum(self, db_session):
        """Test all video status enum values."""
        project = VideoProject(topic="Test status")
        db_session.add(project)

        statuses = [
            VideoStatus.PENDING,
            VideoStatus.SCRIPT_GENERATING,
            VideoStatus.AUDIO_GENERATING,
            VideoStatus.VIDEO_GENERATING,
            VideoStatus.ASSEMBLING,
            VideoStatus.UPLOADING,
            VideoStatus.COMPLETED,
            VideoStatus.FAILED,
        ]

        for status in statuses:
            project.status = status
            db_session.commit()
            assert project.status == status

    def test_video_project_format_enum(self, db_session):
        """Test video format enum values."""
        project_short = VideoProject(topic="Short video", format=VideoFormat.SHORT)
        project_long = VideoProject(topic="Long video", format=VideoFormat.LONG)

        db_session.add_all([project_short, project_long])
        db_session.commit()

        assert project_short.format == VideoFormat.SHORT
        assert project_long.format == VideoFormat.LONG

    def test_validate_status_transition_valid(self, db_session):
        """Test valid status transitions."""
        project = VideoProject(topic="Test", status=VideoStatus.PENDING)
        db_session.add(project)
        db_session.commit()

        # Valid transition: PENDING → SCRIPT_GENERATING
        assert project.validate_status_transition(VideoStatus.SCRIPT_GENERATING)
        project.status = VideoStatus.SCRIPT_GENERATING
        db_session.commit()

        # Valid transition: SCRIPT_GENERATING → AUDIO_GENERATING
        assert project.validate_status_transition(VideoStatus.AUDIO_GENERATING)

    def test_validate_status_transition_invalid(self, db_session):
        """Test invalid status transitions are blocked."""
        project = VideoProject(topic="Test", status=VideoStatus.PENDING)
        db_session.add(project)
        db_session.commit()

        # Invalid transition: PENDING → UPLOADING (skips steps)
        with pytest.raises(ValueError, match="Invalid transition"):
            project.validate_status_transition(VideoStatus.UPLOADING)

    def test_video_project_with_telegram_data(self, db_session):
        """Test storing Telegram integration data."""
        project = VideoProject(
            topic="Test",
            telegram_user_id=123456789,
            telegram_chat_id=987654321,
            telegram_message_id=42,
        )

        db_session.add(project)
        db_session.commit()

        assert project.telegram_user_id == 123456789
        assert project.telegram_chat_id == 987654321
        assert project.telegram_message_id == 42

    def test_video_project_with_youtube_data(self, db_session):
        """Test storing YouTube upload data."""
        project = VideoProject(
            topic="Test",
            youtube_video_id="abc123xyz",
            youtube_url="https://www.youtube.com/watch?v=abc123xyz",
        )

        db_session.add(project)
        db_session.commit()

        assert project.youtube_video_id == "abc123xyz"
        assert "youtube.com" in project.youtube_url

    def test_video_project_error_tracking(self, db_session):
        """Test error message storage."""
        project = VideoProject(
            topic="Test", status=VideoStatus.FAILED, error_message="API rate limit exceeded"
        )

        db_session.add(project)
        db_session.commit()

        assert project.status == VideoStatus.FAILED
        assert "rate limit" in project.error_message

    def test_video_project_artefact_paths(self, db_session):
        """Test storing artefact file paths."""
        project = VideoProject(
            topic="Test",
            audio_path="/media/audio/test_audio.mp3",
            video_path="/media/video/test_video.mp4",
            output_path="/media/output/final_test.mp4",
        )

        db_session.add(project)
        db_session.commit()

        assert project.audio_path.endswith(".mp3")
        assert project.video_path.endswith(".mp4")
        assert project.output_path.endswith(".mp4")


class TestAPIKey:
    """Test APIKey model for authentication."""

    def test_create_api_key(self, db_session):
        """Test creating a new API key."""
        api_key = APIKey(key="ce_test_key_12345", name="Test Application")

        db_session.add(api_key)
        db_session.commit()

        assert api_key.id is not None
        assert api_key.key == "ce_test_key_12345"
        assert api_key.name == "Test Application"
        assert api_key.is_active is True
        assert api_key.rate_limit == 100
        assert api_key.requests_this_hour == 0
        assert api_key.total_requests == 0

    def test_generate_api_key(self):
        """Test API key generation."""
        key = APIKey.generate_key()

        assert key.startswith("ce_")
        assert len(key) > 10  # Should be long and random

        # Generate another key to verify uniqueness
        key2 = APIKey.generate_key()
        assert key != key2

    def test_api_key_repr(self, db_session):
        """Test APIKey string representation."""
        api_key = APIKey(key="ce_test", name="Test Key", is_active=True)
        db_session.add(api_key)
        db_session.commit()

        repr_str = repr(api_key)
        assert "APIKey" in repr_str
        assert "Test Key" in repr_str
        assert "active=True" in repr_str

    def test_api_key_rate_limiting(self, db_session):
        """Test rate limiting fields."""
        api_key = APIKey(key="ce_test_ratelimit", name="Rate Limited Key", rate_limit=50)

        db_session.add(api_key)
        db_session.commit()

        # Simulate requests
        api_key.requests_this_hour = 25
        api_key.total_requests = 1000
        db_session.commit()

        assert api_key.requests_this_hour == 25
        assert api_key.total_requests == 1000
        assert api_key.rate_limit == 50

    def test_api_key_deactivation(self, db_session):
        """Test deactivating an API key."""
        api_key = APIKey(key="ce_test_deactivate", name="To Deactivate", is_active=True)
        db_session.add(api_key)
        db_session.commit()

        # Deactivate
        api_key.is_active = False
        db_session.commit()

        assert api_key.is_active is False

    def test_api_key_unique_constraint(self, db_session):
        """Test that API keys must be unique."""
        from sqlalchemy.exc import IntegrityError

        key1 = APIKey(key="ce_duplicate", name="First")
        key2 = APIKey(key="ce_duplicate", name="Second")

        db_session.add(key1)
        db_session.commit()

        db_session.add(key2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_api_key_last_used_tracking(self, db_session):
        """Test last_used_at timestamp tracking."""
        api_key = APIKey(key="ce_test_lastused", name="Test")
        db_session.add(api_key)
        db_session.commit()

        assert api_key.last_used_at is None

        # Simulate usage
        api_key.last_used_at = datetime.utcnow()
        api_key.total_requests += 1
        db_session.commit()

        assert api_key.last_used_at is not None
        assert api_key.total_requests == 1


class TestTelegramUser:
    """Test TelegramUser model for allowlist."""

    def test_create_telegram_user(self, db_session):
        """Test creating a Telegram user."""
        user = TelegramUser(
            user_id=123456789,
            username="test_user",
            first_name="Test",
            last_name="User",
            is_allowed=True,
        )

        db_session.add(user)
        db_session.commit()

        assert user.user_id == 123456789
        assert user.username == "test_user"
        assert user.first_name == "Test"
        assert user.is_allowed is True

    def test_telegram_user_repr(self, db_session):
        """Test TelegramUser string representation."""
        user = TelegramUser(user_id=1230, username="test_user", is_allowed=True)
        db_session.add(user)
        db_session.commit()

        repr_str = repr(user)
        assert "TelegramUser" in repr_str
        assert "@test_user" in repr_str
        assert "allowed=True" in repr_str

    def test_telegram_user_without_username(self, db_session):
        """Test Telegram user without username."""
        user = TelegramUser(user_id=999, first_name="NoUsername")
        db_session.add(user)
        db_session.commit()

        assert user.username is None
        assert user.first_name == "NoUsername"

    def test_telegram_user_allowlist_toggle(self, db_session):
        """Test toggling allowlist status."""
        user = TelegramUser(user_id=1231, is_allowed=True)
        db_session.add(user)
        db_session.commit()

        # Block user
        user.is_allowed = False
        db_session.commit()

        assert user.is_allowed is False

        # Re-allow user
        user.is_allowed = True
        db_session.commit()

        assert user.is_allowed is True

    def test_telegram_user_unique_user_id(self, db_session):
        """Test that user_id must be unique (it's the primary key)."""
        from sqlalchemy.exc import IntegrityError

        user1 = TelegramUser(user_id=7777, username="user1")
        user2 = TelegramUser(user_id=7777, username="user2")

        db_session.add(user1)
        db_session.commit()

        db_session.add(user2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_telegram_user_timestamps(self, db_session):
        """Test timestamp fields."""
        user = TelegramUser(user_id=1232)
        db_session.add(user)
        db_session.commit()

        assert user.created_at is not None
        assert user.updated_at is not None

        created_at = user.created_at

        # Update user
        user.first_name = "Updated Name"
        db_session.commit()

        # created_at unchanged, updated_at should be set
        assert user.created_at == created_at
        assert user.updated_at >= created_at


class TestModelRelationships:
    """Test relationships between models (if any)."""

    def test_query_video_projects_by_status(self, db_session):
        """Test querying projects by status."""
        project1 = VideoProject(topic="Query Test 1", status=VideoStatus.COMPLETED)
        project2 = VideoProject(topic="Query Test 2", status=VideoStatus.FAILED)
        project3 = VideoProject(topic="Query Test 3", status=VideoStatus.COMPLETED)

        db_session.add_all([project1, project2, project3])
        db_session.commit()

        # Filter by our specific projects to avoid pollution from earlier tests
        completed = (
            db_session.query(VideoProject)
            .filter(
                VideoProject.status == VideoStatus.COMPLETED,
                VideoProject.topic.like("Query Test%"),
            )
            .all()
        )

        assert len(completed) == 2
        assert all(p.status == VideoStatus.COMPLETED for p in completed)

    def test_query_active_api_keys(self, db_session):
        """Test querying active API keys."""
        key1 = APIKey(key="ce_rel_active1", name="Rel Active 1", is_active=True)
        key2 = APIKey(key="ce_rel_inactive", name="Rel Inactive", is_active=False)
        key3 = APIKey(key="ce_rel_active2", name="Rel Active 2", is_active=True)

        db_session.add_all([key1, key2, key3])
        db_session.commit()

        active_keys = (
            db_session.query(APIKey)
            .filter(
                APIKey.is_active,
                APIKey.name.like("Rel %"),
            )
            .all()
        )

        assert len(active_keys) == 2
        assert all(k.is_active for k in active_keys)

    def test_query_allowed_telegram_users(self, db_session):
        """Test querying allowed Telegram users."""
        user1 = TelegramUser(user_id=20001, username="rel_allowed1", is_allowed=True)
        user2 = TelegramUser(user_id=20002, username="rel_blocked", is_allowed=False)
        user3 = TelegramUser(user_id=20003, username="rel_allowed2", is_allowed=True)

        db_session.add_all([user1, user2, user3])
        db_session.commit()

        allowed = (
            db_session.query(TelegramUser)
            .filter(
                TelegramUser.is_allowed,
                TelegramUser.username.like("rel_%"),
            )
            .all()
        )

        assert len(allowed) == 2
        assert all(u.is_allowed for u in allowed)
