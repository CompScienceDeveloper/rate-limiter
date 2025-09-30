"""
Redis configuration optimized for low latency
"""
import redis.asyncio as redis
from typing import Optional

class OptimizedRedisConfig:
    """Redis configuration optimized for low latency rate limiting"""

    @staticmethod
    def get_redis_client(redis_url: str = "redis://localhost:6379") -> redis.Redis:
        """Get optimized Redis client for rate limiting"""
        return redis.from_url(
            redis_url,
            decode_responses=True,
            # Connection pool settings for low latency
            max_connections=50,  # Higher pool for concurrent requests
            retry_on_timeout=True,
            retry_on_error=[],

            # TCP optimizations
            socket_keepalive=True,
            socket_keepalive_options={
                1: 1,  # TCP_KEEPIDLE
                2: 3,  # TCP_KEEPINTVL
                3: 5   # TCP_KEEPCNT
            },
            socket_connect_timeout=5,
            socket_timeout=5,

            # Performance settings
            health_check_interval=30,

            # Disable response parsing for faster responses
            encoding='utf-8',
            encoding_errors='strict'
        )