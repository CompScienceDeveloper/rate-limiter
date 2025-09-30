import jwt
import hashlib
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException
import redis.asyncio as redis
import logging
from .token_bucket import TokenBucketRateLimiter
from ..config.constants import (
    REDIS_DEFAULT_URL,
    IDENTITY_PREFIX_API_KEY,
    IDENTITY_PREFIX_USER,
    IDENTITY_PREFIX_IP,
    IDENTITY_HASH_LENGTH
)

logger = logging.getLogger(__name__)

class RateLimiterService:
    """
    Rate Limiter Service that handles client identification and rate limiting.

    Supports multiple identity extraction methods:
    1. API keys
    2. JWT tokens
    3. IP addresses (fallback)
    """

    def __init__(self, redis_url: str = "redis://localhost:6379", jwt_secret: str = "secret"):
        self.redis_url = redis_url
        self.jwt_secret = jwt_secret
        self.redis_client = None
        self.rate_limiter = None

    async def initialize(self):
        """Initialize Redis connection and rate limiter"""
        try:
            # Optimize Redis for rate limiter performance only
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,  # Fast connection
                socket_timeout=1,          # Fast operations
                retry_on_timeout=False     # Fail fast for rate limiting
            )
            await self.redis_client.ping()

            self.rate_limiter = TokenBucketRateLimiter(self.redis_client)
            await self.rate_limiter.initialize()

            logger.info("Rate limiter service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize rate limiter service: {e}")
            raise

    async def close(self):
        """Close Redis connections"""
        if self.redis_client:
            await self.redis_client.close()

    def extract_client_id(self, request: Request) -> str:
        """
        Extract client ID from request using multiple methods:
        1. API key from headers
        2. JWT token
        3. IP address as fallback
        """

        # Method 1: API Key
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"{IDENTITY_PREFIX_API_KEY}:{hashlib.sha256(api_key.encode()).hexdigest()[:IDENTITY_HASH_LENGTH]}"

        # Method 2: JWT Token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
                user_id = payload.get("user_id") or payload.get("sub")
                if user_id:
                    return f"{IDENTITY_PREFIX_USER}:{user_id}"
            except jwt.InvalidTokenError:
                logger.warning("Invalid JWT token provided")

        # Method 3: IP Address (fallback)
        client_ip = self._get_client_ip(request)
        return f"{IDENTITY_PREFIX_IP}:{client_ip}"

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request"""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fallback to direct client IP
        if hasattr(request, "client") and request.client:
            return request.client.host

        return "unknown"

    async def check_rate_limit(
        self,
        request: Request,
        rule_id: str = "default",
        tokens_requested: int = 1,
        custom_rate: Optional[int] = None,
        custom_capacity: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Check rate limit for incoming request.

        Returns the API interface as specified:
        {
            passed: Boolean,
            resetTime: timestamp,
            X-RateLimit-limit,
            X-RateLimit-remaining,
        }
        """
        if not self.rate_limiter:
            raise HTTPException(status_code=500, detail="Rate limiter not initialized")

        # Extract client identity
        client_id = self.extract_client_id(request)

        # Check rate limit
        result = await self.rate_limiter.is_allowed(
            client_id=client_id,
            rule_id=rule_id,
            tokens_requested=tokens_requested,
            rate=custom_rate,
            capacity=custom_capacity
        )

        logger.info(f"Rate limit check: {client_id} -> {result['passed']}")
        return result

    async def get_rate_limit_status(
        self,
        request: Request,
        rule_id: str = "default"
    ) -> Dict[str, Any]:
        """Get current rate limit status without consuming tokens"""
        if not self.rate_limiter:
            raise HTTPException(status_code=500, detail="Rate limiter not initialized")

        client_id = self.extract_client_id(request)
        return await self.rate_limiter.get_bucket_status(client_id, rule_id)

    async def reset_rate_limit(
        self,
        request: Request,
        rule_id: str = "default"
    ) -> bool:
        """Reset rate limit for a client (admin function)"""
        if not self.rate_limiter:
            raise HTTPException(status_code=500, detail="Rate limiter not initialized")

        client_id = self.extract_client_id(request)
        return await self.rate_limiter.reset_bucket(client_id, rule_id)

    async def health_check(self) -> Dict[str, str]:
        """Health check for rate limiter service"""
        try:
            if self.redis_client:
                await self.redis_client.ping()
                return {"status": "healthy", "redis": "connected"}
            else:
                return {"status": "unhealthy", "redis": "disconnected"}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

# Global rate limiter service instance
rate_limiter_service = RateLimiterService()