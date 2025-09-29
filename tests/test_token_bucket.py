import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
import redis.asyncio as redis

from src.rate_limiter.token_bucket import TokenBucketRateLimiter

@pytest.fixture
async def mock_redis():
    """Mock Redis client for testing"""
    mock_client = AsyncMock(spec=redis.Redis)
    return mock_client

@pytest.fixture
async def rate_limiter(mock_redis):
    """Rate limiter instance with mocked Redis"""
    limiter = TokenBucketRateLimiter(mock_redis, default_rate=100, default_capacity=100)
    await limiter.initialize()
    return limiter

@pytest.mark.asyncio
async def test_token_bucket_initialization(mock_redis):
    """Test rate limiter initialization"""
    limiter = TokenBucketRateLimiter(mock_redis)
    assert limiter.redis == mock_redis
    assert limiter.default_rate == 100
    assert limiter.default_capacity == 100

@pytest.mark.asyncio
async def test_is_allowed_success(rate_limiter, mock_redis):
    """Test successful rate limit check"""
    # Mock Lua script execution result: [allowed, remaining_tokens, used_tokens]
    mock_redis.register_script.return_value.return_value = [1, 99, 1]

    result = await rate_limiter.is_allowed("user123", "default", 1)

    assert result["passed"] is True
    assert result["X-RateLimit-Limit"] == 100
    assert result["X-RateLimit-Remaining"] == 99
    assert "resetTime" in result

@pytest.mark.asyncio
async def test_is_allowed_rate_limited(rate_limiter, mock_redis):
    """Test rate limit exceeded scenario"""
    # Mock Lua script execution result: [denied, remaining_tokens, used_tokens, reset_time]
    reset_time = time.time() + 10
    mock_redis.register_script.return_value.return_value = [0, 0, 100, reset_time]

    result = await rate_limiter.is_allowed("user123", "default", 1)

    assert result["passed"] is False
    assert result["X-RateLimit-Limit"] == 100
    assert result["X-RateLimit-Remaining"] == 0
    assert result["resetTime"] == int(reset_time)

@pytest.mark.asyncio
async def test_is_allowed_redis_error_fallback(rate_limiter, mock_redis):
    """Test fallback behavior when Redis fails"""
    # Simulate Redis error
    mock_redis.register_script.return_value.side_effect = Exception("Redis connection error")

    result = await rate_limiter.is_allowed("user123", "default", 1)

    # Should allow request when Redis fails (availability > consistency)
    assert result["passed"] is True
    assert result["X-RateLimit-Limit"] == 100
    assert result["X-RateLimit-Remaining"] == 100

@pytest.mark.asyncio
async def test_get_bucket_status(rate_limiter, mock_redis):
    """Test getting bucket status"""
    # Mock bucket data
    mock_redis.hmget.return_value = [50, time.time() - 1]

    status = await rate_limiter.get_bucket_status("user123")

    assert status["tokens"] >= 50  # Should have refilled some tokens
    assert status["capacity"] == 100
    assert status["rate"] == 100

@pytest.mark.asyncio
async def test_reset_bucket(rate_limiter, mock_redis):
    """Test bucket reset functionality"""
    mock_redis.delete.return_value = 1

    result = await rate_limiter.reset_bucket("user123")

    assert result is True
    mock_redis.delete.assert_called_once_with("rate_limit:user123:default")

@pytest.mark.asyncio
async def test_custom_rate_and_capacity(rate_limiter, mock_redis):
    """Test custom rate and capacity parameters"""
    mock_redis.register_script.return_value.return_value = [1, 49, 1]

    result = await rate_limiter.is_allowed(
        "user123", "custom", 1, rate=50, capacity=50
    )

    assert result["passed"] is True
    assert result["X-RateLimit-Limit"] == 50

@pytest.mark.asyncio
async def test_multiple_tokens_request(rate_limiter, mock_redis):
    """Test requesting multiple tokens at once"""
    mock_redis.register_script.return_value.return_value = [1, 95, 5]

    result = await rate_limiter.is_allowed("user123", "default", 5)

    assert result["passed"] is True
    assert result["X-RateLimit-Remaining"] == 95

@pytest.mark.asyncio
async def test_concurrent_requests():
    """Test concurrent rate limit checks"""
    mock_redis = AsyncMock(spec=redis.Redis)
    mock_redis.register_script.return_value.return_value = [1, 99, 1]

    limiter = TokenBucketRateLimiter(mock_redis)
    await limiter.initialize()

    # Run multiple concurrent requests
    tasks = [
        limiter.is_allowed(f"user{i}", "default", 1)
        for i in range(10)
    ]

    results = await asyncio.gather(*tasks)

    # All should be successful in this mock scenario
    assert all(result["passed"] for result in results)
    assert len(results) == 10