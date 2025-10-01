import asyncio
import time
from src.rate_limiter.token_bucket import TokenBucketRateLimiter


class LocalDummyRedis:
    def __init__(self):
        self.store = {}

    def register_script(self, script):
        async def run_script(keys=None, args=None):
            key = keys[0]
            rate = float(args[0])
            capacity = int(float(args[1]))
            tokens_requested = int(float(args[2]))
            current_time = float(args[3])
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
                tokens_needed = tokens_requested - tokens
                reset_time = current_time + (tokens_needed / rate) if rate > 0 else current_time + 31536000
                return [0, tokens, capacity - tokens, reset_time]
        return run_script


async def run():
    redis = LocalDummyRedis()
    limiter = TokenBucketRateLimiter(redis_client=redis, default_rate=100.0, default_capacity=100)
    await limiter.initialize()

    # Warmup
    for _ in range(10):
        await limiter.is_allowed('bench-user')

    # Measure
    runs = 100
    total_redis = 0.0
    total_wall = 0.0
    for _ in range(runs):
        start = time.perf_counter()
        res = await limiter.is_allowed('bench-user')
        wall = (time.perf_counter() - start) * 1000
        total_wall += wall
        redis_time = float(res.get('X-RateLimit-Redis-Time', '0.00'))
        total_redis += redis_time

    print(f"Runs: {runs}, avg wall={total_wall/runs:.2f}ms, avg redis={total_redis/runs:.2f}ms")

if __name__ == '__main__':
    asyncio.run(run())
