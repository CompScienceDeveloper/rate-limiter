#!/usr/bin/env python3
"""
Load testing script for the rate limiter system.

This script tests the rate limiter's performance according to the specifications:
- Target: 1M requests per second
- Latency: <10ms per request
- Rate: 100 requests per second per user

Usage:
    python scripts/load_test.py [options]
"""

import asyncio
import aiohttp
import time
import argparse
import json
import statistics
from typing import Dict, List
import random
import sys

class LoadTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = []
        self.errors = []

    async def make_request(self, session: aiohttp.ClientSession, client_id: str, endpoint: str = "/") -> Dict:
        """Make a single request and measure response time"""
        start_time = time.time()

        headers = {}
        # Randomly choose identity method
        identity_method = random.choice(["api_key", "jwt", "ip"])

        if identity_method == "api_key":
            headers["X-API-Key"] = f"api-key-{client_id}"
        elif identity_method == "jwt":
            headers["Authorization"] = f"Bearer fake-jwt-{client_id}"
        # For IP, let the system use the actual IP

        try:
            async with session.get(f"{self.base_url}{endpoint}", headers=headers) as response:
                end_time = time.time()
                latency_ms = (end_time - start_time) * 1000

                result = {
                    "client_id": client_id,
                    "status_code": response.status,
                    "latency_ms": latency_ms,
                    "rate_limit_remaining": response.headers.get("X-RateLimit-Remaining"),
                    "rate_limit_limit": response.headers.get("X-RateLimit-Limit"),
                    "timestamp": start_time,
                    "success": 200 <= response.status < 300 or response.status == 429
                }

                # Read response body for debugging
                if response.status == 429:
                    result["rate_limited"] = True
                else:
                    result["rate_limited"] = False

                return result

        except Exception as e:
            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000

            error_result = {
                "client_id": client_id,
                "status_code": 0,
                "latency_ms": latency_ms,
                "error": str(e),
                "timestamp": start_time,
                "success": False,
                "rate_limited": False
            }
            return error_result

    async def test_single_user_rate_limit(self, requests_per_second: int = 150, duration: int = 10):
        """Test rate limiting for a single user"""
        print(f"🧪 Testing single user rate limit ({requests_per_second} RPS for {duration}s)")

        async with aiohttp.ClientSession() as session:
            tasks = []
            interval = 1.0 / requests_per_second

            start_time = time.time()
            client_id = "load-test-user-1"

            for i in range(requests_per_second * duration):
                task = self.make_request(session, client_id)
                tasks.append(task)

                # Sleep to maintain rate
                if i < (requests_per_second * duration - 1):
                    await asyncio.sleep(interval)

            results = await asyncio.gather(*tasks)
            self.results.extend(results)

            # Analyze results
            successful = [r for r in results if r["success"] and not r["rate_limited"]]
            rate_limited = [r for r in results if r["rate_limited"]]
            errors = [r for r in results if not r["success"]]

            print(f"  ✅ Successful: {len(successful)}")
            print(f"  🚫 Rate Limited: {len(rate_limited)}")
            print(f"  ❌ Errors: {len(errors)}")

            if successful:
                avg_latency = statistics.mean(r["latency_ms"] for r in successful)
                print(f"  ⏱️  Average Latency: {avg_latency:.2f}ms")

    async def test_burst_traffic(self, burst_size: int = 200, client_id: str = "burst-user"):
        """Test burst traffic handling"""
        print(f"💥 Testing burst traffic ({burst_size} concurrent requests)")

        async with aiohttp.ClientSession() as session:
            # Send all requests simultaneously
            tasks = [
                self.make_request(session, client_id)
                for _ in range(burst_size)
            ]

            start_time = time.time()
            results = await asyncio.gather(*tasks)
            end_time = time.time()

            self.results.extend(results)

            successful = [r for r in results if r["success"] and not r["rate_limited"]]
            rate_limited = [r for r in results if r["rate_limited"]]

            print(f"  ✅ Successful: {len(successful)}")
            print(f"  🚫 Rate Limited: {len(rate_limited)}")
            print(f"  ⏱️  Total Time: {(end_time - start_time) * 1000:.2f}ms")

    async def test_multiple_users(self, num_users: int = 10, requests_per_user: int = 50):
        """Test multiple users simultaneously"""
        print(f"👥 Testing multiple users ({num_users} users, {requests_per_user} requests each)")

        async with aiohttp.ClientSession() as session:
            tasks = []

            for user_id in range(num_users):
                client_id = f"load-test-user-{user_id}"
                for _ in range(requests_per_user):
                    task = self.make_request(session, client_id)
                    tasks.append(task)

            start_time = time.time()
            results = await asyncio.gather(*tasks)
            end_time = time.time()

            self.results.extend(results)

            successful = [r for r in results if r["success"] and not r["rate_limited"]]
            rate_limited = [r for r in results if r["rate_limited"]]
            errors = [r for r in results if not r["success"]]

            total_time = end_time - start_time
            rps = len(results) / total_time

            print(f"  ✅ Successful: {len(successful)}")
            print(f"  🚫 Rate Limited: {len(rate_limited)}")
            print(f"  ❌ Errors: {len(errors)}")
            print(f"  🚀 Throughput: {rps:.2f} RPS")

    async def test_different_endpoints(self, num_requests: int = 100):
        """Test rate limiting across different service endpoints"""
        print(f"🔄 Testing different endpoints ({num_requests} requests)")

        endpoints = ["/", "/stats", "/service-a/data", "/service-b/users", "/service-c/orders"]

        async with aiohttp.ClientSession() as session:
            tasks = []
            client_id = "endpoint-test-user"

            for i in range(num_requests):
                endpoint = random.choice(endpoints)
                task = self.make_request(session, client_id, endpoint)
                tasks.append(task)

            results = await asyncio.gather(*tasks)
            self.results.extend(results)

            # Group by endpoint
            by_endpoint = {}
            for result in results:
                endpoint = result.get("endpoint", "unknown")
                if endpoint not in by_endpoint:
                    by_endpoint[endpoint] = []
                by_endpoint[endpoint].append(result)

            for endpoint, endpoint_results in by_endpoint.items():
                successful = [r for r in endpoint_results if r["success"]]
                print(f"  {endpoint}: {len(successful)}/{len(endpoint_results)} successful")

    def analyze_performance(self):
        """Analyze performance metrics"""
        if not self.results:
            print("❌ No results to analyze")
            return

        print("\n📊 Performance Analysis")
        print("=" * 50)

        successful = [r for r in self.results if r["success"] and not r["rate_limited"]]
        rate_limited = [r for r in self.results if r["rate_limited"]]
        errors = [r for r in self.results if not r["success"]]

        print(f"Total Requests: {len(self.results)}")
        print(f"Successful: {len(successful)} ({len(successful)/len(self.results)*100:.1f}%)")
        print(f"Rate Limited: {len(rate_limited)} ({len(rate_limited)/len(self.results)*100:.1f}%)")
        print(f"Errors: {len(errors)} ({len(errors)/len(self.results)*100:.1f}%)")

        if successful:
            latencies = [r["latency_ms"] for r in successful]
            print(f"\nLatency Statistics:")
            print(f"  Average: {statistics.mean(latencies):.2f}ms")
            print(f"  Median: {statistics.median(latencies):.2f}ms")
            print(f"  Min: {min(latencies):.2f}ms")
            print(f"  Max: {max(latencies):.2f}ms")

            # Check if we meet the <10ms requirement
            under_10ms = [l for l in latencies if l < 10]
            print(f"  Under 10ms: {len(under_10ms)}/{len(latencies)} ({len(under_10ms)/len(latencies)*100:.1f}%)")

            if len(latencies) > 1:
                print(f"  95th percentile: {statistics.quantiles(latencies, n=20)[18]:.2f}ms")
                print(f"  99th percentile: {statistics.quantiles(latencies, n=100)[98]:.2f}ms")

        # Rate limiting analysis
        if rate_limited:
            print(f"\nRate Limiting Analysis:")
            print(f"  Rate limited requests: {len(rate_limited)}")

            # Group by client
            by_client = {}
            for result in rate_limited:
                client = result["client_id"]
                if client not in by_client:
                    by_client[client] = 0
                by_client[client] += 1

            print(f"  Clients rate limited: {len(by_client)}")
            for client, count in sorted(by_client.items()):
                print(f"    {client}: {count} requests")

    async def run_comprehensive_test(self):
        """Run comprehensive load test suite"""
        print("🚀 Starting Comprehensive Rate Limiter Load Test")
        print("=" * 60)

        # Test 1: Single user rate limit
        await self.test_single_user_rate_limit(requests_per_second=120, duration=5)
        await asyncio.sleep(2)

        # Test 2: Burst traffic
        await self.test_burst_traffic(burst_size=150)
        await asyncio.sleep(2)

        # Test 3: Multiple users
        await self.test_multiple_users(num_users=5, requests_per_user=30)
        await asyncio.sleep(2)

        # Test 4: Different endpoints
        await self.test_different_endpoints(num_requests=100)

        # Analyze all results
        self.analyze_performance()

async def main():
    parser = argparse.ArgumentParser(description="Rate Limiter Load Testing")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL for testing")
    parser.add_argument("--test", choices=["single", "burst", "multi", "endpoints", "all"],
                       default="all", help="Type of test to run")
    parser.add_argument("--users", type=int, default=10, help="Number of users for multi-user test")
    parser.add_argument("--requests", type=int, default=100, help="Number of requests per user")
    parser.add_argument("--rps", type=int, default=120, help="Requests per second for single user test")
    parser.add_argument("--duration", type=int, default=10, help="Duration in seconds for single user test")

    args = parser.parse_args()

    tester = LoadTester(args.url)

    print(f"🎯 Testing Rate Limiter at {args.url}")

    try:
        if args.test == "single":
            await tester.test_single_user_rate_limit(args.rps, args.duration)
        elif args.test == "burst":
            await tester.test_burst_traffic(args.requests)
        elif args.test == "multi":
            await tester.test_multiple_users(args.users, args.requests)
        elif args.test == "endpoints":
            await tester.test_different_endpoints(args.requests)
        else:
            await tester.run_comprehensive_test()

        if args.test != "all":
            tester.analyze_performance()

    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())