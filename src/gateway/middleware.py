from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, Any, Optional
import time
import logging

logger = logging.getLogger(__name__)

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware for API Gateway.

    Implements the rate limiting flow as specified:
    1. Client sends request to API Gateway
    2. API Gateway checks rate limit data from Redis
    3. Based on token availability, request is either:
       - Allowed (200 OK) - Forwarded to appropriate microservice
       - Rejected (429 Too Many Requests) - Returns error with headers
    """

    def __init__(self, app, rate_limiter_service, excluded_paths: Optional[list] = None):
        super().__init__(app)
        self.rate_limiter_service = rate_limiter_service
        self.excluded_paths = excluded_paths or ["/health", "/docs", "/openapi.json", "/rate-limit/reset", "/rate-limit/status"]

    async def dispatch(self, request: Request, call_next):
        """Process request through rate limiting"""

        # Skip rate limiting for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        try:
            # Measure rate limiter processing time (API Gateway perspective)
            rate_limiter_start = time.perf_counter()

            # Check rate limit
            rate_limit_result = await self.rate_limiter_service.check_rate_limit(request)

            rate_limiter_end = time.perf_counter()
            rate_limiter_processing_time_ms = (rate_limiter_end - rate_limiter_start) * 1000

            # Add rate limit headers to response
            headers = {
                "X-RateLimit-Limit": str(rate_limit_result["X-RateLimit-Limit"]),
                "X-RateLimit-Remaining": str(rate_limit_result["X-RateLimit-Remaining"]),
                "X-RateLimit-Reset": str(rate_limit_result["resetTime"]),
                "X-RateLimit-Processing-Time": f"{rate_limiter_processing_time_ms:.2f}"
            }

            if rate_limit_result["passed"]:
                # Request allowed - proceed to service
                response = await call_next(request)

                # Add rate limit headers to successful response
                for key, value in headers.items():
                    response.headers[key] = value

                return response
            else:
                # Request denied - return 429 Too Many Requests
                error_response = {
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Try again at {rate_limit_result['resetTime']}",
                    "resetTime": rate_limit_result["resetTime"],
                    "limit": rate_limit_result["X-RateLimit-Limit"],
                    "remaining": rate_limit_result["X-RateLimit-Remaining"]
                }

                return JSONResponse(
                    status_code=429,
                    content=error_response,
                    headers=headers
                )

        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Fail closed: Deny request if rate limiter is unavailable
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Service Unavailable",
                    "message": "Rate limiter is temporarily unavailable",
                    "detail": "Please try again later"
                }
            )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging requests with rate limit information"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Log request details
        process_time = time.time() - start_time
        client_ip = request.client.host if request.client else "unknown"

        log_data = {
            "method": request.method,
            "path": request.url.path,
            "client_ip": client_ip,
            "status_code": response.status_code,
            "process_time": round(process_time * 1000, 2),  # ms
            "rate_limit_remaining": response.headers.get("X-RateLimit-Remaining"),
            "rate_limit_limit": response.headers.get("X-RateLimit-Limit")
        }

        logger.info(f"Request processed: {log_data}")
        return response