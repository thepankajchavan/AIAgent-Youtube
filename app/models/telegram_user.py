"""Telegram user model for allowlist and rate limiting."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TelegramUser(Base, TimestampMixin):
    """Telegram user with rate limiting and access control."""

    __tablename__ = "telegram_users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="Telegram user ID")

    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Access control
    is_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True, comment="Whether user is in allowlist"
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="Admin users bypass rate limits"
    )

    # Rate limiting (5 videos per hour)
    videos_this_hour: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rate_limit_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Statistics
    total_videos_requested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_command_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<TelegramUser {self.user_id} @{self.username} allowed={self.is_allowed}>"
