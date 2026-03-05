"""API key model for authentication and rate limiting."""

import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class APIKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """API key for authentication with rate limiting."""

    __tablename__ = "api_keys"

    # API key (format: ce_{token_urlsafe(48)})
    key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True, comment="API key for authentication"
    )

    # Human-readable name
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Descriptive name for this key"
    )

    # Access control
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Whether this key is currently active",
    )

    # Rate limiting (default: 100 requests per hour)
    rate_limit: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False, comment="Maximum requests allowed per hour"
    )

    requests_this_hour: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="Requests made in current hour"
    )

    rate_limit_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="When rate limit counter resets",
    )

    # Statistics
    total_requests: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="Total requests made with this key"
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Last time this key was used"
    )

    @staticmethod
    def generate_key() -> str:
        """Generate a secure API key with prefix ce_."""
        token = secrets.token_urlsafe(48)
        return f"ce_{token}"

    def __repr__(self) -> str:
        return f"<APIKey {self.name} active={self.is_active}>"
