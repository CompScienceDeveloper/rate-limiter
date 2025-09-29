import time
import math
from typing import Dict, Optional, Tuple
import redis.asyncio as redis
import json
import logging

logger = logging.getLogger(__name__)

class TokenBucketRateLimiter:
    """
    Token Bucket Rate Limiter implementation using Redis for distributed rate limiting.

    According to the spec:
    - Rate: 100 requests per second per user
    - Uses Lua scripts for atomicity
    - Handles burst traffic efficiently
    """

    def __init__(self, redis_client: redis.Redis, default_rate: int = 100, default_capacity: int = 100):
        self.redis = redis_client
        self.default_rate = default_rate  # tokens per second
        self.default_capacity = default_capacity  # max tokens in bucket

        # Lua script for atomic token bucket operations
        self.lua_script = """
        local key = KEYS[1]
        local rate = tonumber(ARGV[1])
        local capacity = tonumber(ARGV[2])
        local tokens_requested = tonumber(ARGV[3])
        local current_time = tonumber(ARGV[4])

        -- Get current bucket state
        local bucket_data = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket_data[1]) or capacity
        local last_refill = tonumber(bucket_data[2]) or current_time

        -- Calculate tokens to add based on time elapsed
        local time_elapsed = current_time - last_refill
        local tokens_to_add = math.floor(time_elapsed * rate)

        -- Add tokens but don't exceed capacity
        tokens = math.min(capacity, tokens + tokens_to_add)

        -- Check if we have enough tokens
        if tokens >= tokens_requested then
            -- Consume tokens
            tokens = tokens - tokens_requested

            -- Update bucket state with TTL of 1 hour
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', current_time)
            redis.call('EXPIRE', key, 3600)

            -- Return success with remaining tokens
            return {1, tokens, capacity - tokens}
        else
            -- Update bucket state even if request is denied
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', current_time)
            redis.call('EXPIRE', key, 3600)

            -- Calculate reset time (when bucket will have enough tokens)
            local tokens_needed = tokens_requested - tokens
            local reset_time = current_time + (tokens_needed / rate)

            -- Return failure with reset time
            return {0, tokens, capacity - tokens, reset_time}
        end
        """

        self.script = None

    async def initialize(self):
        """Initialize the Lua script in Redis"""
        self.script = self.redis.register_script(self.lua_script)

    async def is_allowed(
        self,
        client_id: str,
        rule_id: str = "default",
        tokens_requested: int = 1,
        rate: Optional[int] = None,
        capacity: Optional[int] = None
    ) -> Dict:
        """
        Check if request is allowed according to token bucket algorithm.

        Args:
            client_id: Unique identifier for the client
            rule_id: Rate limiting rule identifier
            tokens_requested: Number of tokens to consume
            rate: Custom rate (tokens per second)
            capacity: Custom bucket capacity

        Returns:
            Dict with keys:
            - passed: Boolean indicating if request is allowed
            - resetTime: Timestamp when bucket will refill
            - X-RateLimit-Limit: Rate limit capacity
            - X-RateLimit-Remaining: Remaining tokens
        """
        if not self.script:
            await self.initialize()

        # Use custom rates or defaults
        rate = rate or self.default_rate
        capacity = capacity or self.default_capacity

        # Create Redis key for this client and rule
        key = f"rate_limit:{client_id}:{rule_id}"
        current_time = time.time()

        try:
            # Execute Lua script atomically
            result = await self.script(
                keys=[key],
                args=[rate, capacity, tokens_requested, current_time]
            )

            allowed = bool(result[0])
            remaining_tokens = int(result[1])
            used_tokens = int(result[2])

            response = {
                "passed": allowed,
                "X-RateLimit-Limit": capacity,
                "X-RateLimit-Remaining": remaining_tokens,
            }

            if not allowed and len(result) > 3:
                response["resetTime"] = int(result[3])
            else:
                response["resetTime"] = int(current_time + 1)  # Next second

            logger.debug(f"Rate limit check for {client_id}: {response}")
            return response

        except Exception as e:
            logger.error(f"Rate limiting error for {client_id}: {e}")
            # In case of Redis errors, allow the request (availability > consistency)
            return {
                "passed": True,
                "resetTime": int(current_time + 1),
                "X-RateLimit-Limit": capacity,
                "X-RateLimit-Remaining": capacity,
            }

    async def get_bucket_status(self, client_id: str, rule_id: str = "default") -> Dict:
        """Get current bucket status without consuming tokens"""
        key = f"rate_limit:{client_id}:{rule_id}"

        try:
            bucket_data = await self.redis.hmget(key, 'tokens', 'last_refill')
            tokens = int(bucket_data[0]) if bucket_data[0] else self.default_capacity
            last_refill = float(bucket_data[1]) if bucket_data[1] else time.time()

            # Calculate current tokens
            time_elapsed = time.time() - last_refill
            tokens_to_add = math.floor(time_elapsed * self.default_rate)
            current_tokens = min(self.default_capacity, tokens + tokens_to_add)

            return {
                "tokens": current_tokens,
                "capacity": self.default_capacity,
                "rate": self.default_rate,
                "last_refill": last_refill
            }
        except Exception as e:
            logger.error(f"Error getting bucket status for {client_id}: {e}")
            return {
                "tokens": self.default_capacity,
                "capacity": self.default_capacity,
                "rate": self.default_rate,
                "last_refill": time.time()
            }

    async def reset_bucket(self, client_id: str, rule_id: str = "default") -> bool:
        """Reset bucket to full capacity"""
        key = f"rate_limit:{client_id}:{rule_id}"

        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error resetting bucket for {client_id}: {e}")
            return False