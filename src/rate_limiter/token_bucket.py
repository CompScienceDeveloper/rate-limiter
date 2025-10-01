import time
import math
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
import redis.asyncio as redis
from redis.asyncio.cluster import RedisCluster
import json
import logging
from ..config.constants import DEFAULT_RATE, DEFAULT_CAPACITY, REDIS_KEY_TTL

logger = logging.getLogger(__name__)

class TokenBucketRateLimiter:
    """
    Token Bucket Rate Limiter implementation using Redis for distributed rate limiting.

    According to the spec:
    - Rate: Configurable via constants (default from environment)
    - Uses Lua scripts for atomicity
    - Handles burst traffic efficiently
    """

    def __init__(self, redis_client, default_rate: Optional[float] = None, default_capacity: Optional[int] = None):
        self.redis = redis_client
        self.default_rate = default_rate if default_rate is not None else DEFAULT_RATE  # tokens per second
        self.default_capacity = default_capacity if default_capacity is not None else DEFAULT_CAPACITY  # max tokens in bucket

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
        local tokens_to_add = time_elapsed * rate

        -- Add tokens but don't exceed capacity
        tokens = math.min(capacity, tokens + tokens_to_add)

        -- Check if we have enough tokens
        if tokens >= tokens_requested then
            -- Consume tokens
            tokens = tokens - tokens_requested

            -- Update bucket state with TTL
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', current_time)
            redis.call('EXPIRE', key, ARGV[5])

            -- Return success with remaining tokens
            return {1, tokens, capacity - tokens}
        else
            -- Update bucket state even if request is denied
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', current_time)
            redis.call('EXPIRE', key, ARGV[5])
            -- Calculate reset time (when bucket will have enough tokens)
            local tokens_needed = tokens_requested - tokens

            -- Guard against division by zero / misconfiguration (rate <= 0)
            if rate <= 0 then
                -- No refill configured: set reset time very far in the future (1 year)
                local reset_time = current_time + 31536000
                return {0, tokens, capacity - tokens, reset_time}
            end

            local reset_time = current_time + (tokens_needed / rate)

            -- Return failure with reset time
            return {0, tokens, capacity - tokens, reset_time}
        end
        """

        self.script = None

    async def initialize(self):
        """Initialize the Lua script in Redis"""
        try:
            self.script = self.redis.register_script(self.lua_script)
            # Test that script registration worked
            logger.info("Lua script registered successfully")
        except Exception as e:
            logger.error(f"Failed to register Lua script: {e}")
            raise

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
            # Execute Lua script atomically and measure Redis execution time
            script_start = time.perf_counter()
            result = await self.script(
                keys=[key],
                args=[rate, capacity, tokens_requested, current_time, REDIS_KEY_TTL]
            )
            script_end = time.perf_counter()
            redis_exec_time_ms = (script_end - script_start) * 1000

            allowed = bool(result[0])
            remaining_tokens = int(result[1])
            used_tokens = int(result[2])

            response = {
                "passed": allowed,
                "X-RateLimit-Limit": capacity,
                "X-RateLimit-Remaining": remaining_tokens,
            }

            # attach measured Redis execution time (ms) for profiling
            try:
                response["X-RateLimit-Redis-Time"] = f"{redis_exec_time_ms:.2f}"
            except Exception:
                pass

            # Format reset time as human-readable UTC ISO8601 string
            if not allowed and len(result) > 3:
                reset_ts = float(result[3])
            else:
                reset_ts = current_time + 1  # Next second

            # Provide both epoch (backward-compatible) and ISO string
            try:
                iso = datetime.fromtimestamp(reset_ts, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            except Exception:
                iso = None

            response["resetTimeEpoch"] = int(reset_ts)
            response["resetTime"] = int(reset_ts)  # backward-compatible integer field expected by tests
            if iso:
                response["resetTimeISO"] = iso

            logger.debug(f"Rate limit check for {client_id}: {response}")
            return response

        except Exception as e:
            logger.error(f"Rate limiting error for {client_id}: {e}")
            # Fallback: allow request when Redis fails (availability over strict consistency)
            try:
                reset_iso = datetime.fromtimestamp(current_time + 1, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            except Exception:
                reset_iso = None

            fallback = {
                "passed": True,
                "X-RateLimit-Limit": capacity,
                "X-RateLimit-Remaining": capacity,
                "resetTimeEpoch": int(current_time + 1),
                "resetTime": int(current_time + 1)
            }
            if reset_iso:
                fallback["resetTimeISO"] = reset_iso

            return fallback

    async def get_bucket_status(self, client_id: str, rule_id: str = "default") -> Dict:
        """Get current bucket status without consuming tokens"""
        key = f"rate_limit:{client_id}:{rule_id}"

        try:
            bucket_data = await self.redis.hmget(key, 'tokens', 'last_refill')
            tokens = float(bucket_data[0]) if bucket_data[0] else float(self.default_capacity)
            last_refill = float(bucket_data[1]) if bucket_data[1] else time.time()

            # Calculate current tokens using float refill math (same as Lua)
            time_elapsed = time.time() - last_refill
            tokens_to_add = time_elapsed * self.default_rate
            current_tokens = min(self.default_capacity, tokens + tokens_to_add)

            # compute reset epoch when bucket will be full/next token
            # If rate <= 0, set far-future reset
            if self.default_rate <= 0:
                reset_epoch = time.time() + 31536000
            else:
                # If already has at least 1 token, reset is next second
                if current_tokens >= 1:
                    reset_epoch = time.time() + 1
                else:
                    tokens_needed = 1 - current_tokens
                    reset_epoch = time.time() + (tokens_needed / self.default_rate)

            reset_iso = datetime.fromtimestamp(reset_epoch, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

            return {
                "tokens": current_tokens,
                "capacity": self.default_capacity,
                "rate": self.default_rate,
                "last_refill": last_refill,
                "resetTimeEpoch": int(reset_epoch),
                "resetTime": reset_iso
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