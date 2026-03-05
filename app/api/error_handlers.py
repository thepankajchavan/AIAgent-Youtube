"""Centralized error handlers for sanitized error responses."""

import uuid
from typing import Union

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger


def generate_request_id() -> str:
    """Generate a unique request ID for error tracking."""
    return str(uuid.uuid4())


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handle HTTP exceptions with sanitized error messages.

    Security:
        - Status < 500: Returns user-friendly error with request_id
        - Status >= 500: Returns generic message, logs full details internally
    """
    request_id = generate_request_id()

    # Client errors (4xx) - safe to return detailed message
    if exc.status_code < 500:
        logger.warning(
            f"HTTP {exc.status_code} - {request.method} {request.url.path} - {exc.detail} "
            f"[request_id: {request_id}]"
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "request_id": request_id,
            },
        )

    # Server errors (5xx) - sanitize details, log internally
    logger.error(
        f"HTTP {exc.status_code} - {request.method} {request.url.path} - {exc.detail} "
        f"[request_id: {request_id}]"
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "Internal server error. Please contact support with the request ID.",
            "request_id": request_id,
        },
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
) -> JSONResponse:
    """
    Handle request validation errors with structured field-level errors.

    Returns:
        422 status with detailed field validation errors
    """
    request_id = generate_request_id()

    logger.warning(
        f"Validation error - {request.method} {request.url.path} - "
        f"{len(exc.errors())} errors [request_id: {request_id}]"
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation error",
            "details": exc.errors(),
            "request_id": request_id,
        },
    )


async def generic_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """
    Catch-all handler for unexpected exceptions.

    Security:
        - Never exposes internal exception details to user
        - Logs full traceback internally
        - Returns generic error message with request_id for support
    """
    request_id = generate_request_id()

    logger.exception(
        f"Unhandled exception - {request.method} {request.url.path} "
        f"[request_id: {request_id}]: {exc}"
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "An unexpected error occurred. Please contact support with the request ID.",
            "request_id": request_id,
        },
    )
