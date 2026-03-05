"""Security headers middleware for defense-in-depth."""

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.

    Headers added:
        - X-Content-Type-Options: nosniff
        - X-Frame-Options: DENY
        - X-XSS-Protection: 1; mode=block
        - Referrer-Policy: strict-origin-when-cross-origin
        - Permissions-Policy: geolocation=(), microphone=(), camera=()
        - Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
        - Strict-Transport-Security: max-age=31536000; includeSubDomains (HTTPS only)

    Note:
        - Defense-in-depth: These headers are also set by Nginx in production
        - Ensures headers are present even if request bypasses Nginx
        - HSTS only added on HTTPS requests to avoid browser warnings
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to response."""

        response = await call_next(request)

        # ── Prevent MIME sniffing ────────────────────────────────
        # Prevents browsers from interpreting files as different type
        response.headers["X-Content-Type-Options"] = "nosniff"

        # ── Prevent clickjacking ─────────────────────────────────
        # Prevents page from being embedded in frames/iframes
        response.headers["X-Frame-Options"] = "DENY"

        # ── XSS Protection (legacy, defense-in-depth) ────────────
        # Modern CSP is preferred, but this adds extra protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # ── Referrer Policy ──────────────────────────────────────
        # Only send origin when navigating to same/more secure protocol
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # ── Permissions Policy ───────────────────────────────────
        # Disable access to sensitive browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )

        # ── Content Security Policy ─────────────────────────────
        # Very strict policy for API (no content loading)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "frame-ancestors 'none'"
        )

        # ── Strict Transport Security (HTTPS only) ──────────────
        # Only add HSTS if request was made over HTTPS
        # Adding to HTTP causes browser warnings
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; "  # 1 year
                "includeSubDomains"
            )

        logger.debug("Security headers added to response")
        return response
