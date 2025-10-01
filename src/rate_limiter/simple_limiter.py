import time
import math
from typing import Dict, Optional
from datetime import datetime, timezone
import redis.asyncio as redis
import logging

logger = logging.getLogger(__name__)

class SimpleTokenBucketRateLimiter:
    """
    Simplified Token Bucket Rate Limiter without Lua scripts for easier debugging.
    """

    def __init__(self, redis_client: redis.Redis, default_rate: float = 20/60, default_capacity: int = 20):
        self.redis = redis_client
        self.default_rate = default_rate
        self.default_capacity = default_capacity

    async def initialize(self):
        """Initialize - no script needed"""
        pass

    async def is_allowed(
        self,
        client_id: str,
        rule_id: str = "default",
        tokens_requested: int = 1,
        rate: Optional[int] = None,
        capacity: Optional[int] = None
    ) -> Dict:
        """
        Check if request is allowed using simple Redis operations.
        """
        rate = rate or self.default_rate
        capacity = capacity or self.default_capacity

        key = f"rate_limit:{client_id}:{rule_id}"
        current_time = time.time()

        try:
            # Get current bucket state
            bucket_data = await self.redis.hmget(key, 'tokens', 'last_refill')

            # Parse current state
            current_tokens = float(bucket_data[0]) if bucket_data[0] else capacity
            last_refill = float(bucket_data[1]) if bucket_data[1] else current_time

            # Calculate tokens to add
            time_elapsed = current_time - last_refill
            tokens_to_add = time_elapsed * rate

            # Update tokens (don't exceed capacity)
            current_tokens = min(capacity, current_tokens + tokens_to_add)

            # Check if we have enough tokens
            if current_tokens >= tokens_requested:
                # Consume tokens
                current_tokens -= tokens_requested

                # Update Redis in single pipeline for better performance
                pipe = self.redis.pipeline()
                pipe.hmset(key, {
                    'tokens': current_tokens,
                    'last_refill': current_time
                })
                pipe.expire(key, 3600)  # 1 hour TTL
                await pipe.execute()

                # Format reset time as ISO8601 UTC string
                try:
                    reset_iso = datetime.fromtimestamp(current_time + 1, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
                except Exception:
                    reset_iso = int(current_time + 1)

                # Also provide epoch and backward-compatible int resetTime
                try:
                    reset_epoch = int(current_time + 1)
                except Exception:
                    reset_epoch = int(time.time() + 1)

                return {
                    "passed": True,
                    "resetTimeEpoch": reset_epoch,
                    "resetTime": reset_epoch,
                    "resetTimeISO": reset_iso,
                    "X-RateLimit-Limit": capacity,
                    "X-RateLimit-Remaining": int(current_tokens),
                }
            else:
                # Not enough tokens - update Redis in pipeline
                pipe = self.redis.pipeline()
                pipe.hmset(key, {
                    'tokens': current_tokens,
                    'last_refill': current_time
                })
                pipe.expire(key, 3600)
                await pipe.execute()

                # Calculate when we'll have enough tokens
                tokens_needed = tokens_requested - current_tokens
                reset_time = current_time + (tokens_needed / rate)

                # Format reset time as ISO8601 UTC string
                try:
                    reset_iso = datetime.fromtimestamp(reset_time, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
                except Exception:
                    reset_iso = int(reset_time)

                try:
                    reset_epoch = int(reset_time)
                except Exception:
                    reset_epoch = int(time.time() + 1)

                return {
                    "passed": False,
                    "resetTimeEpoch": reset_epoch,
                    "resetTime": reset_epoch,
                    "resetTimeISO": reset_iso,
                    "X-RateLimit-Limit": capacity,
                    "X-RateLimit-Remaining": int(current_tokens),
                }

        except Exception as e:
            logger.error(f"Rate limiting error for {client_id}: {e}")
            # Fallback: allow request
            try:
                reset_iso = datetime.fromtimestamp(current_time + 1, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            except Exception:
                reset_iso = None

            reset_epoch = int(current_time + 1)
            fallback = {
                "passed": True,
                "resetTimeEpoch": reset_epoch,
                "resetTime": reset_epoch,
                "X-RateLimit-Limit": capacity,
                "X-RateLimit-Remaining": capacity,
            }
            if reset_iso:
                fallback["resetTimeISO"] = reset_iso

            return fallback

    async def get_bucket_status(self, client_id: str, rule_id: str = "default") -> Dict:
        """Get current bucket status"""
        key = f"rate_limit:{client_id}:{rule_id}"

        try:
            bucket_data = await self.redis.hmget(key, 'tokens', 'last_refill')
            tokens = float(bucket_data[0]) if bucket_data[0] else float(self.default_capacity)
            last_refill = float(bucket_data[1]) if bucket_data[1] else time.time()

            # Float refill math to match enforcement
            time_elapsed = time.time() - last_refill
            tokens_to_add = time_elapsed * self.default_rate
            current_tokens = min(self.default_capacity, tokens + tokens_to_add)

            # Compute reset epoch with divide-by-zero guard
            if self.default_rate <= 0:
                reset_epoch = time.time() + 31536000
            else:
                if current_tokens >= 1:
                    reset_epoch = time.time() + 1
                else:
                    tokens_needed = 1 - current_tokens
                    reset_epoch = time.time() + (tokens_needed / self.default_rate)

            try:
                reset_iso = datetime.fromtimestamp(reset_epoch, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            except Exception:
                reset_iso = int(reset_epoch)

            return {
                "tokens": int(current_tokens),
                "capacity": self.default_capacity,
                "rate": self.default_rate,
                "last_refill": last_refill,
                "resetTimeEpoch": int(reset_epoch),
                "resetTime": reset_iso
            }
        except Exception as e:
            logger.error(f"Error getting bucket status: {e}")
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
            logger.error(f"Error resetting bucket: {e}")
            return False