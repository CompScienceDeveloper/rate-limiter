import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import time

from src.gateway.api_gateway import app
from src.rate_limiter.service import rate_limiter_service

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

        # Should have been called with a request containing the API key
        mock_extract.assert_called_once()

@pytest.mark.asyncio
async def test_jwt_token_extraction():
    """Test JWT token extraction from Authorization header"""
    with patch.object(rate_limiter_service, 'extract_client_id') as mock_extract:
        mock_extract.return_value = "user:123"

        client = TestClient(app)
        response = client.get("/", headers={"Authorization": "Bearer jwt-token"})

        # Should have been called with a request containing the JWT
        mock_extract.assert_called_once()

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