import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import redis.asyncio as redis
from fastapi.testclient import TestClient
import httpx

from src.rate_limiter.token_bucket import TokenBucketRateLimiter
from src.config.constants import DEFAULT_RATE, DEFAULT_CAPACITY
from src.gateway.api_gateway import app
from src.rate_limiter.service import rate_limiter_service


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing (synchronous fixture)"""
    mock_client = AsyncMock(spec=redis.Redis)
    # provide a register_script callable that returns an AsyncMock script
    mock_client.register_script = MagicMock(return_value=AsyncMock())
    # ensure commonly awaited methods are AsyncMock so `await mock_redis.delete(...)` works
    mock_client.delete = AsyncMock()
    mock_client.hmget = AsyncMock()
    return mock_client


@pytest.fixture
def rate_limiter(mock_redis):
    """Rate limiter instance with mocked Redis"""
    limiter = TokenBucketRateLimiter(mock_redis)
    # simulate initialize by assigning the script from mocked redis
    limiter.script = mock_redis.register_script.return_value
    return limiter


@pytest.fixture
def client():
    """Test client for API Gateway"""
    return TestClient(app)


@pytest.fixture
async def mock_rate_limiter_service():
    """Mock rate limiter service"""
    mock_service = AsyncMock()
    mock_service.check_rate_limit.return_value = {
        "passed": True,
        "resetTime": int(time.time() + 60),
        "X-RateLimit-Limit": 100,
        "X-RateLimit-Remaining": 99
    }
    mock_service.health_check.return_value = {"status": "healthy", "redis": "connected"}
    return mock_service


@pytest.mark.asyncio
async def test_token_bucket_initialization(mock_redis):
    """Test rate limiter initialization"""
    limiter = TokenBucketRateLimiter(mock_redis)
    assert limiter.redis == mock_redis
    assert limiter.default_rate == DEFAULT_RATE
    assert limiter.default_capacity == DEFAULT_CAPACITY


@pytest.mark.asyncio
async def test_is_allowed_success(rate_limiter, mock_redis):
    """Test successful rate limit check"""
    # Mock Lua script execution result: [allowed, remaining_tokens, used_tokens]
    mock_redis.register_script.return_value.return_value = [1, DEFAULT_CAPACITY - 1, 1]

    result = await rate_limiter.is_allowed("user123", "default", 1)

    assert result["passed"] is True
    assert result["X-RateLimit-Limit"] == DEFAULT_CAPACITY
    assert result["X-RateLimit-Remaining"] == DEFAULT_CAPACITY - 1
    assert "resetTime" in result


@pytest.mark.asyncio
async def test_is_allowed_rate_limited(rate_limiter, mock_redis):
    """Test rate limit exceeded scenario"""
    # Mock Lua script execution result: [denied, remaining_tokens, used_tokens, reset_time]
    reset_time = time.time() + 10
    mock_redis.register_script.return_value.return_value = [0, 0, DEFAULT_CAPACITY, reset_time]

    result = await rate_limiter.is_allowed("user123", "default", 1)

    assert result["passed"] is False
    assert result["X-RateLimit-Limit"] == DEFAULT_CAPACITY
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
    assert result["X-RateLimit-Limit"] == DEFAULT_CAPACITY
    assert result["X-RateLimit-Remaining"] == DEFAULT_CAPACITY


@pytest.mark.asyncio
async def test_get_bucket_status(rate_limiter, mock_redis):
    """Test getting bucket status"""
    # Mock bucket data
    mock_redis.hmget.return_value = [DEFAULT_CAPACITY // 2, time.time() - 1]

    status = await rate_limiter.get_bucket_status("user123")

    assert status["tokens"] >= DEFAULT_CAPACITY // 2  # Should have refilled some tokens
    assert status["capacity"] == DEFAULT_CAPACITY
    assert status["rate"] == DEFAULT_RATE


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


def test_root_endpoint(client):
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Rate Limiter API Gateway"
    assert data["algorithm"] == "Token Bucket"
    assert "services" in data


def test_health_check(client):
    """Test health check endpoint"""
    with patch.object(rate_limiter_service, 'health_check') as mock_health:
        mock_health.return_value = {"status": "healthy", "redis": "connected"}

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_rate_limit_middleware_allowed():
    """Test rate limit middleware when request is allowed"""
    with patch.object(rate_limiter_service, 'check_rate_limit') as mock_check:
        mock_check.return_value = {
            "passed": True,
            "resetTime": int(time.time() + 60),
            "X-RateLimit-Limit": 100,
            "X-RateLimit-Remaining": 99
        }

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        # Check rate limit headers are present
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers


@pytest.mark.asyncio
async def test_rate_limit_middleware_denied():
    """Test rate limit middleware when request is denied"""
    with patch.object(rate_limiter_service, 'check_rate_limit') as mock_check:
        mock_check.return_value = {
            "passed": False,
            "resetTime": int(time.time() + 60),
            "X-RateLimit-Limit": 100,
            "X-RateLimit-Remaining": 0
        }

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 429
        data = response.json()
        assert data["error"] == "Rate limit exceeded"
        assert "resetTime" in data


def test_rate_limit_status_endpoint(client):
    """Test rate limit status endpoint"""
    with patch.object(rate_limiter_service, 'get_rate_limit_status') as mock_status:
        mock_status.return_value = {
            "tokens": 95,
            "capacity": 100,
            "rate": 100,
            "last_refill": time.time()
        }

        response = client.get("/rate-limit/status")
        assert response.status_code == 200
        data = response.json()
        assert data["tokens"] == 95
        assert data["capacity"] == 100


def test_rate_limit_reset_endpoint(client):
    """Test rate limit reset endpoint"""
    with patch.object(rate_limiter_service, 'reset_rate_limit') as mock_reset:
        mock_reset.return_value = True

        response = client.post("/rate-limit/reset")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


def test_stats_endpoint(client):
    """Test stats endpoint"""
    with patch.object(rate_limiter_service, 'get_rate_limit_status') as mock_status, \
         patch.object(rate_limiter_service, 'extract_client_id') as mock_extract:

        mock_status.return_value = {
            "tokens": 95,
            "capacity": 100,
            "rate": 100,
            "last_refill": time.time()
        }
        mock_extract.return_value = "ip:127.0.0.1"

        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["client_id"] == "ip:127.0.0.1"
        assert data["current_tokens"] == 95


def test_excluded_paths_no_rate_limiting(client):
    """Test that excluded paths bypass rate limiting"""
    # These requests should work even if rate limiter fails
    response = client.get("/health")
    assert response.status_code == 200

    response = client.get("/docs")
    # This might return 404 or redirect, but shouldn't be rate limited
    assert response.status_code != 429


@pytest.mark.asyncio
async def test_api_key_extraction():
    """Test API key extraction from headers"""
    with patch.object(rate_limiter_service, 'extract_client_id') as mock_extract:
        mock_extract.return_value = "api_key:abcd1234"

        client = TestClient(app)
        response = client.get("/", headers={"X-API-Key": "test-api-key"})

    # Ensure request succeeds and returns 200
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_jwt_token_extraction():
    """Test JWT token extraction from Authorization header"""
    with patch.object(rate_limiter_service, 'extract_client_id') as mock_extract:
        mock_extract.return_value = "user:123"

        client = TestClient(app)
        response = client.get("/", headers={"Authorization": "Bearer jwt-token"})

    # Ensure request succeeds and returns 200
    assert response.status_code == 200


def test_concurrent_requests_load_test():
    """Test handling multiple concurrent requests"""
    import threading
    import queue

    results = queue.Queue()

    def make_request():
        client = TestClient(app)
        with patch.object(rate_limiter_service, 'check_rate_limit') as mock_check:
            mock_check.return_value = {
                "passed": True,
                "resetTime": int(time.time() + 60),
                "X-RateLimit-Limit": 100,
                "X-RateLimit-Remaining": 99
            }
            response = client.get("/")
            results.put(response.status_code)

    # Create multiple threads to simulate concurrent requests
    threads = []
    for _ in range(10):
        thread = threading.Thread(target=make_request)
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Check that all requests were processed
    assert results.qsize() == 10
    while not results.empty():
        status_code = results.get()
        assert status_code == 200


def test_gateway_redis_failure_returns_503():
    """Simulate a Redis/backend failure during rate-limit check and expect 503"""
    with patch.object(rate_limiter_service, 'check_rate_limit', side_effect=Exception("Redis timeout")):
        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 503
        data = response.json()
        assert data.get("error") == "Service Unavailable"


@pytest.mark.asyncio
async def test_token_bucket_rate_zero_get_status():
    """When rate == 0, get_bucket_status should not divide by zero and resetTimeEpoch should be far in future"""
    mock_redis = AsyncMock()
    # hmget returns [tokens, last_refill] -> None simulates no existing bucket
    mock_redis.hmget.return_value = [None, None]

    limiter = TokenBucketRateLimiter(mock_redis, default_rate=0, default_capacity=100)

    status = await limiter.get_bucket_status("test-user")

    now = time.time()
    # resetTimeEpoch should be large (1 year ahead as implemented)
    assert "resetTimeEpoch" in status
    assert status["resetTimeEpoch"] - now > 100000  # definitely > a day


def test_downstream_service_failure_returns_503():
    """If proxy to downstream service fails (request error), API should return 503"""
    # Patch the httpx AsyncClient.request to raise a RequestError
    mocked = AsyncMock(side_effect=httpx.RequestError("Downstream unreachable"))
    with patch('src.gateway.api_gateway.httpx.AsyncClient.request', new=mocked):
        client = TestClient(app)
        response = client.get("/service-a/anything")

        assert response.status_code == 503
        assert "Service service-a unavailable" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_jwt_canonicalization_consistent():
    """Ensure JWT-based user ids are canonicalized to fixed-length hashed client ids"""
    from fastapi import Request
    # Create a sample JWT payload matching service secret
    import jwt as pyjwt
    payload = {"user_id": "canonical-user-42", "exp": int(time.time()) + 3600}
    token = pyjwt.encode(payload, rate_limiter_service.jwt_secret, algorithm="HS256")

    # Build a dummy request with Authorization header
    class DummyClient:
        host = "127.0.0.1"

    req = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "client": ("127.0.0.1", 12345)
    })

    # Call extract_client_id twice and assert same result and hashed form
    cid1 = rate_limiter_service.extract_client_id(req)
    cid2 = rate_limiter_service.extract_client_id(req)

    assert cid1 == cid2
    assert cid1.startswith("user:")
    # After prefix, expect a hex hash of ID length equal to IDENTITY_HASH_LENGTH
    from src.config.constants import IDENTITY_HASH_LENGTH
    hash_part = cid1.split(":", 1)[1]
    assert len(hash_part) == IDENTITY_HASH_LENGTH
# Token Refill Recovery Tests (merged from test_token_refill.py)

class DummyRedis:
    """Minimal Redis simulation for token bucket refill testing"""
    def __init__(self):
        self.store = {}

    def register_script(self, script):
        # Return a callable that simulates Lua behavior by delegating to python
        async def run_script(keys=None, args=None):
            # Very small simulation: store tokens and last_refill
            key = keys[0]
            rate = float(args[0])
            capacity = int(float(args[1]))
            tokens_requested = int(float(args[2]))
            current_time = float(args[3])
            ttl = int(float(args[4]))

            bucket = self.store.get(key, {'tokens': capacity, 'last_refill': current_time})
            tokens = float(bucket.get('tokens', capacity))
            last_refill = float(bucket.get('last_refill', current_time))

            elapsed = current_time - last_refill
            tokens += elapsed * rate
            tokens = min(capacity, tokens)

            if tokens >= tokens_requested:
                tokens -= tokens_requested
                self.store[key] = {'tokens': tokens, 'last_refill': current_time}
                return [1, tokens, capacity - tokens]
            else:
                self.store[key] = {'tokens': tokens, 'last_refill': current_time}
                if rate <= 0:
                    reset_time = current_time + 31536000
                    return [0, tokens, capacity - tokens, reset_time]
                tokens_needed = tokens_requested - tokens
                reset_time = current_time + (tokens_needed / rate)
                return [0, tokens, capacity - tokens, reset_time]

        return run_script

    async def hmget(self, key, *fields):
        bucket = self.store.get(key, None)
        if not bucket:
            return [None, None]
        return [bucket.get('tokens'), bucket.get('last_refill')]

    async def delete(self, key):
        self.store.pop(key, None)
        return True


@pytest.mark.asyncio
async def test_refill_recovery():
    """Test that tokens refill over time and bucket recovery works"""
    redis = DummyRedis()
    limiter = TokenBucketRateLimiter(redis_client=redis, default_rate=100.0, default_capacity=100)
    await limiter.initialize()

    client = "test-user"
    # Consume entire bucket
    res = await limiter.is_allowed(client, tokens_requested=100)
    assert res['passed'] is True

    # Immediately request one more, should be rate-limited
    res2 = await limiter.is_allowed(client, tokens_requested=1)
    assert res2['passed'] is False

    # Wait 1 second (rate=100 tokens/sec -> should recover ~100 tokens)
    await asyncio.sleep(1.1)

    status = await limiter.get_bucket_status(client)
    assert status['tokens'] >= 1
