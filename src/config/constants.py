"""
Rate Limiter Constants - Environment-aware configuration

Configuration is read from environment variables at runtime:
- RATE_LIMIT_RATE: Explicit rate (tokens/sec)
- RATE_LIMIT_CAPACITY: Explicit capacity
- ENVIRONMENT: Preset (test/dev/production)
"""
import os
from typing import Dict, Any, Tuple

def get_rate_limit_config() -> Tuple[float, int, str]:
    """
    Get rate limit configuration from environment variables.
    Each service reads its own environment, making it suitable for distributed systems.

    Returns:
        Tuple of (rate, capacity, description)

    Environment Variables:
        RATE_LIMIT_RATE: Tokens per second (float)
        RATE_LIMIT_CAPACITY: Max bucket capacity (int)
        ENVIRONMENT: Environment name (test/dev/production)
    """
    # Check if explicit values are set
    rate_env = os.getenv("RATE_LIMIT_RATE")
    capacity_env = os.getenv("RATE_LIMIT_CAPACITY")

    if rate_env and capacity_env:
        rate = float(rate_env)
        capacity = int(capacity_env)
        description = f"{rate} requests per second per user (custom)"
        return rate, capacity, description

    # Otherwise use environment presets
    env = os.getenv("ENVIRONMENT", "local").lower()

    # Production Configuration (as per system design spec)
    if env in ["production", "prod"]:
        return 100.0, 100, "100 requests per second per user (production spec)"

    # Development Configuration
    elif env in ["development", "dev"]:
        # Dev settings tuned for enhanced testing: higher rate and capacity
        # to exercise sustained and burst scenarios without being identical to production.
        return 50.0, 100, "50 requests per second per user, capacity 100 (development)"

    # Test Configuration (default)
    else:
        # Default test/local configuration: 20 requests per minute per user
        # Production should be selected via ENVIRONMENT=production
        return 20.0 / 60.0, 20, "20 requests per minute per user (test environment)"

# Load configuration from environment (each service reads independently)
DEFAULT_RATE, DEFAULT_CAPACITY, RATE_LIMIT_DESCRIPTION = get_rate_limit_config()

# Redis Configuration
REDIS_DEFAULT_URL = "redis://localhost:6379"
REDIS_TIMEOUT_MS = 1000  # 1 second timeout for fast-fail
REDIS_CONNECT_TIMEOUT_MS = 1000
REDIS_KEY_TTL = 3600  # 1 hour TTL for rate limit keys

# System Performance Targets
TARGET_LATENCY_MS = 10  # < 10ms for rate limit check
MAX_REQUESTS_PER_SECOND = 1_000_000  # System capacity: 1M RPS
REDIS_INSTANCES_REQUIRED = 20  # Based on 100k RPS per Redis instance

# Identity Extraction
IDENTITY_PREFIX_API_KEY = "api_key"
IDENTITY_PREFIX_USER = "user"
IDENTITY_PREFIX_IP = "ip"
IDENTITY_HASH_LENGTH = 16

# Rate Limiter Behavior
FAIL_CLOSED = True  # Deny requests when Redis fails (fail closed for security)

# HTTP Headers
HEADER_RATE_LIMIT = "X-RateLimit-Limit"
HEADER_RATE_REMAINING = "X-RateLimit-Remaining"
HEADER_RATE_RESET = "X-RateLimit-Reset"

# Lua Script Keys
LUA_KEY_TOKENS = "tokens"
LUA_KEY_LAST_REFILL = "last_refill"

# Logging
LOG_RATE_LIMIT_CHECKS = True
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Print current configuration on import
if __name__ != "__main__":
    import logging
    logger = logging.getLogger(__name__)
    env = os.getenv("ENVIRONMENT", "test")
    logger.info(f"Rate Limiter Environment: {env.upper()}")
    logger.info(f"Configuration: {RATE_LIMIT_DESCRIPTION}")
    logger.info(f"Rate: {DEFAULT_RATE} tokens/sec, Capacity: {DEFAULT_CAPACITY}")