"""API key authentication middleware."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.api_key import APIKey

settings = get_settings()


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce API key authentication on all endpoints.

    - Extracts API key from X-API-Key header or Authorization: Bearer token
    - Validates key exists, is active, and within rate limits
    - Updates usage statistics
    - Public paths exempt: /health, /docs, /openapi.json, /redoc
    """

    # Paths that don't require authentication
    PUBLIC_PATHS = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and validate API key if required."""

        # Skip authentication for public paths
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)

        # Skip authentication if disabled (development mode)
        if not settings.api_auth_enabled:
            return await call_next(request)

        # Extract API key from headers
        api_key = self._extract_api_key(request)

        if not api_key:
            logger.warning(f"Missing API key for {request.url.path} from {request.client.host}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "API key required. Provide via X-API-Key header or Authorization: Bearer token."
                },
            )

        # Validate API key
        async with async_session_factory() as session:
            validation_result = await self._validate_api_key(session, api_key, request)

            if validation_result is not None:
                return validation_result  # Return error response

        # API key is valid, proceed with request
        return await call_next(request)

    def _extract_api_key(self, request: Request) -> str | None:
        """
        Extract API key from request headers.

        Checks:
        1. X-API-Key header
        2. Authorization: Bearer <token> header
        """
        # Check X-API-Key header
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return api_key

        # Check Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix

        return None

    async def _validate_api_key(
        self, session: AsyncSession, api_key: str, request: Request
    ) -> JSONResponse | None:
        """
        Validate API key against database.

        Returns:
            - None if validation successful
            - JSONResponse with error if validation fails
        """
        # Fetch API key from database
        result = await session.execute(select(APIKey).where(APIKey.key == api_key))
        key_obj = result.scalar_one_or_none()

        if not key_obj:
            logger.warning(f"Invalid API key attempted from {request.client.host}")
            return JSONResponse(status_code=401, content={"detail": "Invalid API key."})

        # Check if key is active
        if not key_obj.is_active:
            logger.warning(f"Inactive API key {key_obj.name} attempted from {request.client.host}")
            return JSONResponse(status_code=401, content={"detail": "API key is inactive."})

        # Check rate limiting
        now = datetime.now(UTC)

        # Reset counter if hour has passed
        if now >= key_obj.rate_limit_reset_at:
            await session.execute(
                update(APIKey)
                .where(APIKey.id == key_obj.id)
                .values(requests_this_hour=0, rate_limit_reset_at=now + timedelta(hours=1))
            )
            await session.commit()
            key_obj.requests_this_hour = 0

        # Check if rate limit exceeded
        if key_obj.requests_this_hour >= key_obj.rate_limit:
            reset_in = int((key_obj.rate_limit_reset_at - now).total_seconds())
            logger.warning(
                f"Rate limit exceeded for API key {key_obj.name} "
                f"({key_obj.requests_this_hour}/{key_obj.rate_limit})"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Limit: {key_obj.rate_limit} requests/hour. "
                    f"Resets in {reset_in} seconds."
                },
                headers={"Retry-After": str(reset_in)},
            )

        # Update usage statistics
        await session.execute(
            update(APIKey)
            .where(APIKey.id == key_obj.id)
            .values(
                requests_this_hour=APIKey.requests_this_hour + 1,
                total_requests=APIKey.total_requests + 1,
                last_used_at=now,
            )
        )
        await session.commit()

        logger.debug(
            f"API key {key_obj.name} validated "
            f"({key_obj.requests_this_hour + 1}/{key_obj.rate_limit})"
        )

        # Attach key info to request state for use in endpoints
        request.state.api_key = key_obj

        return None  # Validation successful
