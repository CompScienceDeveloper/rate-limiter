#!/usr/bin/env python3
"""
Enhanced Comprehensive Rate Limiter Test Suite

Features:
- Same-user rate limit testing
- Token reset between test cases
- Multiple user types and authentication methods
- Edge cases and error scenarios
- Performance benchmarking
- Detailed analysis and reporting

Usage:
    python enhanced_comprehensive_test.py [options]
"""

import asyncio
import os
import aiohttp
import time
import argparse
import json
import statistics
import random
import uuid
import hashlib
import jwt
import base64
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

class UserType(Enum):
    API_KEY = "api_key"
    JWT_TOKEN = "jwt_token"
    IP_ONLY = "ip_only"
    SHARED_IP = "shared_ip"
    UNAUTHENTICATED = "unauthenticated"
    MALFORMED_TOKEN = "malformed_token"

@dataclass
class TestUser:
    user_id: str
    user_type: UserType
    api_key: Optional[str] = None
    jwt_token: Optional[str] = None
    ip_address: Optional[str] = None
    expected_rate_limit: int = 100  # requests per second

@dataclass
class TestResult:
    user_id: str
    user_type: UserType
    status_code: int
    total_latency_ms: float
    rate_limiter_latency_ms: Optional[float]
    rate_limit_remaining: Optional[str]
    rate_limit_limit: Optional[str]
    timestamp: float
    success: bool
    rate_limited: bool
    error: Optional[str] = None
    endpoint: str = "/"
    identification_method: Optional[str] = None

class EnhancedRateLimiterTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[TestResult] = []
        self.test_users: List[TestUser] = []
        self.jwt_secret = "secret"  # Match the default service JWT secret
        # Optional override from environment to help tests adapt to different presets
        try:
            self.env_rate_limit_rate = int(float(os.getenv("RATE_LIMIT_RATE"))) if os.getenv("RATE_LIMIT_RATE") else None
        except Exception:
            self.env_rate_limit_rate = None

    def generate_test_users(self) -> List[TestUser]:
        """Generate diverse set of test users"""
        users = []

        # 1. Regular API Key Users (8 users)
        for i in range(8):
            users.append(TestUser(
                user_id=f"api-user-{i:03d}",
                user_type=UserType.API_KEY,
                api_key=f"api-key-{uuid.uuid4().hex[:16]}",
                ip_address=f"10.0.1.{i+10}",
                expected_rate_limit=self.env_rate_limit_rate or 100
            ))

        # 2. JWT Token Users (6 users)
        for i in range(6):
            jwt_payload = {
                "user_id": f"jwt-user-{i:03d}",
                "exp": datetime.utcnow() + timedelta(hours=1),
                "iat": datetime.utcnow(),
                "scope": ["read", "write"]
            }
            jwt_token = jwt.encode(jwt_payload, self.jwt_secret, algorithm="HS256")

            users.append(TestUser(
                user_id=f"jwt-user-{i:03d}",
                user_type=UserType.JWT_TOKEN,
                jwt_token=jwt_token,
                ip_address=f"10.0.2.{i+10}",
                expected_rate_limit=self.env_rate_limit_rate or 100
            ))

        # 3. IP-Only Users (4 users)
        for i in range(4):
            users.append(TestUser(
                user_id=f"ip-user-{i:03d}",
                user_type=UserType.IP_ONLY,
                ip_address=f"192.168.1.{i+20}",
                expected_rate_limit=self.env_rate_limit_rate or 100
            ))

        # 4. Shared IP Users (4 users, 2 shared IPs)
        shared_ips = ["192.168.100.1", "192.168.100.2"]
        for i in range(4):
            shared_ip = shared_ips[i % len(shared_ips)]
            users.append(TestUser(
                user_id=f"shared-ip-user-{i:03d}",
                user_type=UserType.SHARED_IP,
                api_key=f"shared-api-{uuid.uuid4().hex[:12]}",
                ip_address=shared_ip,
                expected_rate_limit=self.env_rate_limit_rate or 100
            ))

        # 5. Unauthenticated Users (2 users)
        for i in range(2):
            users.append(TestUser(
                user_id=f"unauth-user-{i:03d}",
                user_type=UserType.UNAUTHENTICATED,
                ip_address=f"203.0.113.{i+10}",  # TEST-NET-3
                expected_rate_limit=self.env_rate_limit_rate or 100
            ))

        # 6. Malformed Token Users (3 users for error testing)
        malformed_tokens = [
            "invalid.jwt.token",
            "Bearer malformed-api-key",
            "api-key-" + "x" * 500  # Very long key
        ]
        for i, token in enumerate(malformed_tokens):
            users.append(TestUser(
                user_id=f"malformed-user-{i:03d}",
                user_type=UserType.MALFORMED_TOKEN,
                api_key=token if i % 2 == 0 else None,
                jwt_token=token if i % 2 == 1 else None,
                ip_address=f"198.51.100.{i+10}",  # TEST-NET-2
                expected_rate_limit=self.env_rate_limit_rate or 100
            ))

        self.test_users = users
        return users

    def _get_request_headers(self, user: TestUser) -> Dict[str, str]:
        """Generate appropriate headers for user type"""
        headers = {}

        # Add authentication headers
        if user.user_type == UserType.API_KEY and user.api_key:
            headers["X-API-Key"] = user.api_key
        elif user.user_type == UserType.JWT_TOKEN and user.jwt_token:
            headers["Authorization"] = f"Bearer {user.jwt_token}"
        elif user.user_type == UserType.SHARED_IP and user.api_key:
            headers["X-API-Key"] = user.api_key
        elif user.user_type == UserType.MALFORMED_TOKEN:
            if user.api_key:
                headers["X-API-Key"] = user.api_key
            if user.jwt_token:
                headers["Authorization"] = f"Bearer {user.jwt_token}"

        # Add IP headers for all users with IP addresses
        if user.ip_address:
            headers["X-Forwarded-For"] = user.ip_address
            headers["X-Real-IP"] = user.ip_address
            headers["X-Client-IP"] = user.ip_address

        # Add consistent headers for same user identification
        headers["User-Agent"] = f"TestClient-{user.user_type.value}-{user.user_id}"
        # Use consistent request ID per user (not random) to avoid affecting rate limiting
        headers["X-Request-ID"] = f"test-{user.user_id}"

        return headers

    async def reset_user_rate_limit(self, session: aiohttp.ClientSession, user: TestUser) -> bool:
        """Reset rate limit for a specific user"""
        try:
            headers = self._get_request_headers(user)
            async with session.post(f"{self.base_url}/rate-limit/reset", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("success", False)
                return False
        except Exception as e:
            print(f"⚠️ Failed to reset rate limit for {user.user_id}: {e}")
            return False

    async def reset_all_users_rate_limits(self, session: aiohttp.ClientSession, users: List[TestUser]) -> int:
        """Reset rate limits for all users and return count of successful resets"""
        print("🔄 Resetting rate limits for all users...")
        reset_tasks = [self.reset_user_rate_limit(session, user) for user in users]
        results = await asyncio.gather(*reset_tasks, return_exceptions=True)
        successful_resets = sum(1 for result in results if result is True)
        print(f"   ✅ Reset {successful_resets}/{len(users)} users successfully")
        return successful_resets

    async def make_request(self, session: aiohttp.ClientSession, user: TestUser, endpoint: str = "/") -> TestResult:
        """Make a single request for a user"""
        start_time = time.time()
        headers = self._get_request_headers(user)

        try:
            async with session.get(f"{self.base_url}{endpoint}", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                end_time = time.time()
                latency_ms = (end_time - start_time) * 1000

                # Extract rate limiter processing time
                rate_limiter_latency = response.headers.get("X-RateLimit-Processing-Time")
                rate_limiter_latency_ms = float(rate_limiter_latency) if rate_limiter_latency else None

                # Read response for debugging (only on errors)
                response_text = ""
                if not (200 <= response.status < 300 or response.status == 429):
                    try:
                        response_text = await response.text()
                        print(f"   ⚠️ Error {response.status} for {user.user_id} at {endpoint}: {response_text[:100]}")
                    except:
                        pass

                return TestResult(
                    user_id=user.user_id,
                    user_type=user.user_type,
                    status_code=response.status,
                    total_latency_ms=latency_ms,
                    rate_limiter_latency_ms=rate_limiter_latency_ms,
                    rate_limit_remaining=response.headers.get("X-RateLimit-Remaining"),
                    rate_limit_limit=response.headers.get("X-RateLimit-Limit"),
                    timestamp=start_time,
                    success=200 <= response.status < 300 or response.status == 429,
                    rate_limited=response.status == 429,
                    endpoint=endpoint,
                    identification_method=user.user_type.value
                )

        except asyncio.TimeoutError:
            end_time = time.time()
            return TestResult(
                user_id=user.user_id,
                user_type=user.user_type,
                status_code=0,
                total_latency_ms=(end_time - start_time) * 1000,
                rate_limiter_latency_ms=None,
                rate_limit_remaining=None,
                rate_limit_limit=None,
                timestamp=start_time,
                success=False,
                rate_limited=False,
                error="Request timeout",
                endpoint=endpoint,
                identification_method=user.user_type.value
            )
        except Exception as e:
            end_time = time.time()
            return TestResult(
                user_id=user.user_id,
                user_type=user.user_type,
                status_code=0,
                total_latency_ms=(end_time - start_time) * 1000,
                rate_limiter_latency_ms=None,
                rate_limit_remaining=None,
                rate_limit_limit=None,
                timestamp=start_time,
                success=False,
                rate_limited=False,
                error=str(e),
                endpoint=endpoint,
                identification_method=user.user_type.value
            )

    async def test_single_user_rate_limit_exhaustion(self, user: TestUser, burst_size: int = 150):
        """Test rate limit exhaustion for a single user"""
        print(f"💥 Testing Single User Rate Limit Exhaustion")
        print(f"   👤 User: {user.user_id} ({user.user_type.value})")
        print(f"   🚀 Burst: {burst_size} rapid requests")

        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Reset user's rate limit first
            await self.reset_user_rate_limit(session, user)
            await asyncio.sleep(0.5)

            # Phase 1: Send burst requests to exhaust rate limit
            print(f"   📊 Phase 1: Sending {burst_size} requests as fast as possible...")
            burst_tasks = [self.make_request(session, user) for _ in range(burst_size)]

            start_time = time.time()
            burst_results = await asyncio.gather(*burst_tasks)
            end_time = time.time()

            successful = [r for r in burst_results if r.success and not r.rate_limited]
            rate_limited = [r for r in burst_results if r.rate_limited]
            errors = [r for r in burst_results if not r.success]

            print(f"     ✅ Successful: {len(successful)}")
            print(f"     🚫 Rate Limited: {len(rate_limited)}")
            print(f"     ❌ Errors: {len(errors)}")
            print(f"     ⏱️ Total Time: {end_time - start_time:.2f}s")

            # Phase 2: Wait for token recovery
            recovery_time = 2
            print(f"   ⏳ Phase 2: Waiting {recovery_time}s for token recovery...")
            await asyncio.sleep(recovery_time)

            # Phase 3: Test requests after recovery
            recovery_requests = 10
            print(f"   🔄 Phase 3: Testing {recovery_requests} requests after recovery...")
            recovery_tasks = [self.make_request(session, user) for _ in range(recovery_requests)]
            recovery_results = await asyncio.gather(*recovery_tasks)

            recovered_successful = [r for r in recovery_results if r.success and not r.rate_limited]
            print(f"     ✅ Post-recovery Successful: {len(recovered_successful)}/{recovery_requests}")

            self.results.extend(burst_results + recovery_results)

            # Analysis
            rate_limiting_triggered = len(rate_limited) > 0
            recovery_working = len(recovered_successful) > 0

            print(f"   📊 Single User Test Results:")
            print(f"     Rate limiting triggered: {'✅ YES' if rate_limiting_triggered else '❌ NO'}")
            print(f"     Recovery working: {'✅ YES' if recovery_working else '❌ NO'}")

            return {
                "rate_limiting_triggered": rate_limiting_triggered,
                "recovery_working": recovery_working,
                "total_requests": len(burst_results) + len(recovery_results),
                "rate_limited_count": len(rate_limited)
            }

    async def test_same_user_sustained_load(self, user: TestUser, duration_seconds: int = 15, target_rps: int = 120):
        """Test sustained load from same user over time"""
        print(f"⚡ Testing Same User Sustained Load")
        print(f"   👤 User: {user.user_id}")
        print(f"   🎯 Target: {target_rps} RPS for {duration_seconds}s")

        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Reset user's rate limit first
            await self.reset_user_rate_limit(session, user)
            await asyncio.sleep(0.5)

            results = []
            start_time = time.time()
            request_interval = 1.0 / target_rps

            request_count = 0
            while time.time() - start_time < duration_seconds:
                request_start = time.time()

                # Make request
                result = await self.make_request(session, user)
                results.append(result)
                request_count += 1

                # Calculate sleep time to maintain target RPS
                elapsed = time.time() - request_start
                sleep_time = max(0, request_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            end_time = time.time()
            actual_duration = end_time - start_time
            actual_rps = len(results) / actual_duration

            self.results.extend(results)

            # Analysis
            successful = [r for r in results if r.success and not r.rate_limited]
            rate_limited = [r for r in results if r.rate_limited]
            errors = [r for r in results if not r.success]

            print(f"   📊 Sustained Load Results:")
            print(f"     Duration: {actual_duration:.2f}s")
            print(f"     Target RPS: {target_rps}, Actual RPS: {actual_rps:.2f}")
            print(f"     Total requests: {len(results)}")
            print(f"     ✅ Successful: {len(successful)}")
            print(f"     🚫 Rate Limited: {len(rate_limited)}")
            print(f"     ❌ Errors: {len(errors)}")

            # Calculate rate limiting effectiveness
            expected_successful = min(len(results), user.expected_rate_limit * duration_seconds)
            rate_limiting_working = len(rate_limited) > 0 if len(results) > expected_successful else True

            print(f"     Rate limiting working: {'✅ YES' if rate_limiting_working else '❌ NO'}")

            return {
                "actual_rps": actual_rps,
                "rate_limiting_working": rate_limiting_working,
                "rate_limited_percentage": len(rate_limited) / len(results) * 100 if results else 0
            }

    async def test_user_type_isolation(self, requests_per_user: int = 30):
        """Test that different user types are properly isolated"""
        print(f"🔒 Testing User Type Isolation ({requests_per_user} requests per user)")

        users = self.generate_test_users()

        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Reset all users before testing
            await self.reset_all_users_rate_limits(session, users)
            await asyncio.sleep(1)  # Wait for reset to take effect

            tasks = []

            # Create requests in smaller batches to avoid overwhelming the system
            batch_size = 50  # Process 50 requests at a time
            all_results = []

            all_requests = []
            for user in users:
                for _ in range(requests_per_user):
                    all_requests.append(user)

            start_time = time.time()

            # Process in batches
            for i in range(0, len(all_requests), batch_size):
                batch_users = all_requests[i:i + batch_size]
                batch_tasks = [self.make_request(session, user) for user in batch_users]
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

                # Filter out exceptions
                valid_results = [r for r in batch_results if isinstance(r, TestResult)]
                all_results.extend(valid_results)

                # Small delay between batches
                if i + batch_size < len(all_requests):
                    await asyncio.sleep(0.1)

            results = all_results
            end_time = time.time()

            self.results.extend(results)

            # Analyze by user type
            by_user_type = {}
            for result in results:
                user_type = result.user_type.value
                if user_type not in by_user_type:
                    by_user_type[user_type] = []
                by_user_type[user_type].append(result)

            print(f"   📊 Results by User Type:")
            isolation_working = True

            for user_type, type_results in by_user_type.items():
                successful = [r for r in type_results if r.success and not r.rate_limited]
                rate_limited = [r for r in type_results if r.rate_limited]
                errors = [r for r in type_results if not r.success]

                print(f"     {user_type.upper()}:")
                print(f"       ✅ Successful: {len(successful)}")
                print(f"       🚫 Rate Limited: {len(rate_limited)}")
                print(f"       ❌ Errors: {len(errors)}")

                if successful:
                    avg_latency = statistics.mean(r.total_latency_ms for r in successful)
                    print(f"       ⏱️  Avg Latency: {avg_latency:.2f}ms")

                # Check isolation - legitimate user types should have some successful requests
                if user_type not in ["malformed_token"] and len(successful) == 0:
                    isolation_working = False

            print(f"   🔒 User Type Isolation: {'✅ WORKING' if isolation_working else '❌ FAILED'}")

    async def test_concurrent_same_user_multiple_sessions(self, user: TestUser, session_count: int = 5, requests_per_session: int = 50):
        """Test same user from multiple concurrent sessions"""
        print(f"👥 Testing Same User Multiple Sessions")
        print(f"   👤 User: {user.user_id}")
        print(f"   📱 Sessions: {session_count}")
        print(f"   📊 Requests per session: {requests_per_session}")

        # Reset user first
        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector) as reset_session:
            await self.reset_user_rate_limit(reset_session, user)
            await asyncio.sleep(0.5)

        # Create multiple sessions for the same user
        async def session_worker(session_id: int):
            async with aiohttp.ClientSession() as session:
                session_results = []
                # Create all requests for this session as fast as possible
                session_tasks = [self.make_request(session, user) for _ in range(requests_per_session)]
                session_results = await asyncio.gather(*session_tasks)
                return session_results

        # Run concurrent sessions
        session_tasks = [session_worker(i) for i in range(session_count)]
        all_session_results = await asyncio.gather(*session_tasks)

        # Flatten results
        all_results = []
        for session_results in all_session_results:
            all_results.extend(session_results)

        self.results.extend(all_results)

        # Analysis
        successful = [r for r in all_results if r.success and not r.rate_limited]
        rate_limited = [r for r in all_results if r.rate_limited]
        errors = [r for r in all_results if not r.success]

        print(f"   📊 Multi-Session Results:")
        print(f"     Total requests: {len(all_results)}")
        print(f"     ✅ Successful: {len(successful)}")
        print(f"     🚫 Rate Limited: {len(rate_limited)}")
        print(f"     ❌ Errors: {len(errors)}")

        # Check if rate limiting works across sessions
        rate_limiting_across_sessions = len(rate_limited) > 0
        print(f"     Rate limiting across sessions: {'✅ WORKING' if rate_limiting_across_sessions else '❌ NOT WORKING'}")

    async def test_different_endpoints_same_user(self, user: TestUser, requests_per_endpoint: int = 100):
        """Test same user accessing different endpoints"""
        print(f"🔄 Testing Different Endpoints Same User")
        print(f"   👤 User: {user.user_id}")

        endpoints = ["/", "/health", "/stats", "/rate-limit/status"]

        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Reset user first (no delay after reset to test true burst)
            reset_success = await self.reset_user_rate_limit(session, user)
            print(f"   🔄 Reset successful: {reset_success}")

            # Create all tasks for burst test
            tasks = []
            for endpoint in endpoints:
                for _ in range(requests_per_endpoint):
                    tasks.append(self.make_request(session, user, endpoint))

            print(f"   🚀 Sending {len(tasks)} requests simultaneously...")
            start_time = time.time()
            results = await asyncio.gather(*tasks)
            end_time = time.time()
            print(f"   ⏱️ Completed in {end_time - start_time:.2f}s")
            self.results.extend(results)

            # Analyze by endpoint
            by_endpoint = {}
            for result in results:
                endpoint = result.endpoint
                if endpoint not in by_endpoint:
                    by_endpoint[endpoint] = {"successful": 0, "rate_limited": 0, "errors": 0}

                if result.success and not result.rate_limited:
                    by_endpoint[endpoint]["successful"] += 1
                elif result.rate_limited:
                    by_endpoint[endpoint]["rate_limited"] += 1
                else:
                    by_endpoint[endpoint]["errors"] += 1

            print(f"   📊 Results by endpoint:")
            total_rate_limited = sum(stats["rate_limited"] for stats in by_endpoint.values())
            total_requests = len(results)

            for endpoint, stats in by_endpoint.items():
                total = sum(stats.values())
                success_pct = (stats["successful"] / total * 100) if total > 0 else 0
                print(f"     {endpoint}: {stats['successful']}✅ {stats['rate_limited']}🚫 {stats['errors']}❌ ({success_pct:.1f}% success)")

            print(f"   📈 Total: {total_requests} requests, {total_rate_limited} rate limited ({total_rate_limited/total_requests*100:.1f}%)")

            # Rate limiting should work consistently across endpoints
            consistent_rate_limiting = total_rate_limited > 0
            print(f"   🔄 Consistent rate limiting: {'✅ WORKING' if consistent_rate_limiting else '❌ NOT WORKING'}")

    async def test_edge_cases_and_errors(self):
        """Test various edge cases and error scenarios"""
        print(f"⚠️ Testing Edge Cases and Error Scenarios")

        edge_case_users = [
            # Very long API key
            TestUser("edge-long-key", UserType.MALFORMED_TOKEN, api_key="x" * 500),
            # Empty API key
            TestUser("edge-empty-key", UserType.MALFORMED_TOKEN, api_key=""),
            # SQL injection attempt in API key
            TestUser("edge-sql-inject", UserType.MALFORMED_TOKEN, api_key="'; DROP TABLE users; --"),
            # Invalid IP
            TestUser("edge-invalid-ip", UserType.IP_ONLY, ip_address="not.an.ip.address"),
        ]

        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for user in edge_case_users:
                # Test each edge case user multiple times
                for _ in range(3):
                    tasks.append(self.make_request(session, user))

            results = await asyncio.gather(*tasks)
            self.results.extend(results)

            # Analyze edge case results
            by_user = {}
            for result in results:
                # Defensive guard: some tasks may return non-TestResult values (e.g., bools) if
                # an auxiliary helper was accidentally included or an unexpected codepath
                # returned a primitive. Skip those and log for debugging.
                if not hasattr(result, 'user_id'):
                    print(f"   ⚠️ Skipping non-TestResult entry in edge-case results: {result!r}")
                    continue

                user_id = result.user_id
                if user_id not in by_user:
                    by_user[user_id] = []
                by_user[user_id].append(result)

            print(f"   📊 Edge case results:")
            for user_id, user_results in by_user.items():
                errors = [r for r in user_results if not r.success]
                successful = [r for r in user_results if r.success]
                print(f"     {user_id}: {len(successful)}✅ {len(errors)}❌")

    def analyze_comprehensive_results(self):
        """Comprehensive analysis of all test results"""
        if not self.results:
            print("❌ No results to analyze")
            return

        print("\n" + "="*80)
        print("🔍 ENHANCED COMPREHENSIVE RATE LIMITER ANALYSIS")
        print("="*80)

        # Overall statistics
        total_requests = len(self.results)
        successful = [r for r in self.results if r.success and not r.rate_limited]
        rate_limited = [r for r in self.results if r.rate_limited]
        errors = [r for r in self.results if not r.success]

        print(f"\n📊 OVERALL STATISTICS:")
        print(f"  Total Requests: {total_requests:,}")
        print(f"  ✅ Successful: {len(successful):,} ({len(successful)/total_requests*100:.1f}%)")
        print(f"  🚫 Rate Limited: {len(rate_limited):,} ({len(rate_limited)/total_requests*100:.1f}%)")
        print(f"  ❌ Errors: {len(errors):,} ({len(errors)/total_requests*100:.1f}%)")

        # Latency analysis for successful requests
        if successful:
            total_latencies = [r.total_latency_ms for r in successful]
            rate_limiter_latencies = [r.rate_limiter_latency_ms for r in successful if r.rate_limiter_latency_ms is not None]

            print(f"\n⏱️ LATENCY ANALYSIS (Successful Requests):")
            print(f"  End-to-End Latency:")
            print(f"    Average: {statistics.mean(total_latencies):.2f}ms")
            print(f"    Median: {statistics.median(total_latencies):.2f}ms")
            print(f"    Min: {min(total_latencies):.2f}ms")
            print(f"    Max: {max(total_latencies):.2f}ms")

            if len(total_latencies) > 10:
                p95 = statistics.quantiles(total_latencies, n=20)[18]
                p99 = statistics.quantiles(total_latencies, n=100)[98] if len(total_latencies) > 20 else max(total_latencies)
                print(f"    95th percentile: {p95:.2f}ms")
                print(f"    99th percentile: {p99:.2f}ms")

            if rate_limiter_latencies:
                print(f"  Rate Limiter Processing Time:")
                print(f"    Average: {statistics.mean(rate_limiter_latencies):.2f}ms")
                print(f"    Median: {statistics.median(rate_limiter_latencies):.2f}ms")
                print(f"    Min: {min(rate_limiter_latencies):.2f}ms")
                print(f"    Max: {max(rate_limiter_latencies):.2f}ms")

                under_10ms = [l for l in rate_limiter_latencies if l < 10]
                print(f"    Under 10ms target: {len(under_10ms)}/{len(rate_limiter_latencies)} ({len(under_10ms)/len(rate_limiter_latencies)*100:.1f}%)")

        # Analysis by user type
        print(f"\n👥 USER TYPE ANALYSIS:")
        by_user_type = {}
        for result in self.results:
            user_type = result.user_type.value
            if user_type not in by_user_type:
                by_user_type[user_type] = []
            by_user_type[user_type].append(result)

        for user_type, type_results in by_user_type.items():
            type_successful = [r for r in type_results if r.success and not r.rate_limited]
            type_rate_limited = [r for r in type_results if r.rate_limited]
            type_errors = [r for r in type_results if not r.success]

            print(f"  {user_type.upper()}:")
            print(f"    Total: {len(type_results)}")
            print(f"    ✅ Successful: {len(type_successful)} ({len(type_successful)/len(type_results)*100:.1f}%)")
            print(f"    🚫 Rate Limited: {len(type_rate_limited)} ({len(type_rate_limited)/len(type_results)*100:.1f}%)")
            print(f"    ❌ Errors: {len(type_errors)} ({len(type_errors)/len(type_results)*100:.1f}%)")

            if type_successful:
                avg_latency = statistics.mean(r.total_latency_ms for r in type_successful)
                print(f"    ⏱️ Avg Latency: {avg_latency:.2f}ms")

        # Rate limiting effectiveness
        print(f"\n🛡️ RATE LIMITING EFFECTIVENESS:")
        rate_limiting_working = len(rate_limited) > 0
        print(f"  Rate limiting triggered: {'✅ YES' if rate_limiting_working else '❌ NO'}")

        if rate_limited:
            # Analyze rate limited requests by user
            rl_by_user = {}
            for result in rate_limited:
                user_id = result.user_id
                if user_id not in rl_by_user:
                    rl_by_user[user_id] = 0
                rl_by_user[user_id] += 1

            print(f"  Users that hit rate limits: {len(rl_by_user)}")
            print(f"  Most rate limited users:")
            sorted_users = sorted(rl_by_user.items(), key=lambda x: x[1], reverse=True)
            for user_id, count in sorted_users[:5]:
                print(f"    {user_id}: {count} requests")

        # Performance verdict
        print(f"\n🎯 PERFORMANCE VERDICT:")

        # Check latency requirement (<10ms for rate limiter)
        if successful and rate_limiter_latencies:
            avg_rl_latency = statistics.mean(rate_limiter_latencies)
            latency_ok = avg_rl_latency < 10.0
            print(f"  Rate limiter latency <10ms: {'✅ PASS' if latency_ok else '❌ FAIL'} (avg: {avg_rl_latency:.2f}ms)")
        else:
            print(f"  Rate limiter latency: ⚠️ NO DATA")

        # Check rate limiting functionality
        print(f"  Rate limiting functional: {'✅ PASS' if rate_limiting_working else '❌ FAIL'}")

        # Check error rate
        error_rate = len(errors) / total_requests * 100
        low_error_rate = error_rate < 5.0
        print(f"  Low error rate (<5%): {'✅ PASS' if low_error_rate else '❌ FAIL'} ({error_rate:.1f}%)")

        # Overall assessment
        all_checks_pass = (
            rate_limiting_working and
            low_error_rate and
            (not rate_limiter_latencies or statistics.mean(rate_limiter_latencies) < 10.0)
        )
        print(f"\n🏆 OVERALL ASSESSMENT: {'✅ PASS' if all_checks_pass else '❌ NEEDS ATTENTION'}")

    async def run_enhanced_test_suite(self):
        """Run the complete enhanced test suite"""
        print("🚀 STARTING ENHANCED COMPREHENSIVE RATE LIMITER TEST SUITE")
        print("="*80)

        # Generate test users
        self.generate_test_users()
        print(f"👥 Generated {len(self.test_users)} test users across {len(set(u.user_type for u in self.test_users))} user types")

        # Select representative users for single-user tests
        api_user = next((u for u in self.test_users if u.user_type == UserType.API_KEY), None)
        jwt_user = next((u for u in self.test_users if u.user_type == UserType.JWT_TOKEN), None)
        ip_user = next((u for u in self.test_users if u.user_type == UserType.IP_ONLY), None)

        # Test 1: Single user rate limit exhaustion
        if api_user:
            await self.test_single_user_rate_limit_exhaustion(api_user, burst_size=130)
            await asyncio.sleep(2)

        # Test 2: Same user sustained load
        if jwt_user:
            await self.test_same_user_sustained_load(jwt_user, duration_seconds=12, target_rps=110)
            await asyncio.sleep(2)

        # Test 3: User type isolation
        await self.test_user_type_isolation(requests_per_user=30)
        await asyncio.sleep(2)

        # Test 4: Same user multiple sessions
        if api_user:
            await self.test_concurrent_same_user_multiple_sessions(api_user, session_count=4, requests_per_session=50)
            await asyncio.sleep(2)

        # Test 5: Different endpoints same user
        if ip_user:
            await self.test_different_endpoints_same_user(ip_user, requests_per_endpoint=100)
            await asyncio.sleep(1)

        # Test 6: Edge cases and errors
        await self.test_edge_cases_and_errors()

        # Final comprehensive analysis
        self.analyze_comprehensive_results()

async def main():
    parser = argparse.ArgumentParser(description="Enhanced Comprehensive Rate Limiter Testing")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL for testing")
    parser.add_argument("--test", choices=[
        "single-exhaustion", "sustained-load", "isolation", "multi-session",
        "endpoints", "edge-cases", "all"
    ], default="all", help="Type of test to run")
    parser.add_argument("--users", type=int, default=5, help="Number of users for applicable tests")
    parser.add_argument("--requests", type=int, default=25, help="Number of requests per user")
    parser.add_argument("--duration", type=int, default=15, help="Duration for sustained load test")
    parser.add_argument("--rps", type=int, default=120, help="Target RPS for sustained load test")
    parser.add_argument("--burst", type=int, default=150, help="Burst size for exhaustion test")

    args = parser.parse_args()

    tester = EnhancedRateLimiterTester(args.url)

    print(f"🎯 Testing Rate Limiter at {args.url}")
    print(f"📋 Test mode: {args.test}")

    try:
        tester.generate_test_users()
        api_user = next((u for u in tester.test_users if u.user_type == UserType.API_KEY), None)
        jwt_user = next((u for u in tester.test_users if u.user_type == UserType.JWT_TOKEN), None)
        ip_user = next((u for u in tester.test_users if u.user_type == UserType.IP_ONLY), None)

        if args.test == "single-exhaustion" and api_user:
            await tester.test_single_user_rate_limit_exhaustion(api_user, args.burst)
        elif args.test == "sustained-load" and jwt_user:
            await tester.test_same_user_sustained_load(jwt_user, args.duration, args.rps)
        elif args.test == "isolation":
            await tester.test_user_type_isolation(args.requests)
        elif args.test == "multi-session" and api_user:
            await tester.test_concurrent_same_user_multiple_sessions(api_user, session_count=args.users, requests_per_session=args.requests)
        elif args.test == "endpoints" and ip_user:
            await tester.test_different_endpoints_same_user(ip_user, args.requests)
        elif args.test == "edge-cases":
            await tester.test_edge_cases_and_errors()
        else:
            await tester.run_enhanced_test_suite()

        if args.test != "all":
            tester.analyze_comprehensive_results()

    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
        if tester.results:
            tester.analyze_comprehensive_results()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())