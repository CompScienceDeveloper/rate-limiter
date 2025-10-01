# Quick Start - Environment Configuration

## TL;DR

**Current setup:** Test environment (20 requests/minute) by default in code
**To use production:** set `ENVIRONMENT=production` (100 requests/second) or use the recommended compose override (shown below)

---

# Quick Switch

```bash
# Test (default - current setting; local python runner deprecated)
# (most testing is done via docker-compose)
docker-compose up -d

# Production (recommended) — preferred: use an override file or pass ENVIRONMENT
# Option A: override file (recommended)
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Option B: environment variable (one-off)
ENVIRONMENT=production docker-compose up -d --build

# Notes:
# - Use --build when you changed source or the Dockerfile so images are rebuilt.
# - The override file approach is safer for CI/ops and keeps the main compose file unchanged.
```

## TL;DR

Current setup uses Docker Compose with an nginx load balancer (external port 80).

- Test environment (default): 20 requests/minute
- Dev environment: 10 requests/second
- Prod environment: 100 requests/second

## Environment Profiles

| Name | ENVIRONMENT value | Rate | Use Case |
|------|-------------------|------|----------|
| Test | `test` (default)  | 20/min | CI / integration testing |
| Dev  | `dev`             | 10/sec | Local development |
| Prod | `production` or `prod` | 100/sec | Production deployment |

Set the environment per API Gateway instance in `docker-compose.yml` or via `environment` variables.

---

## Quick Setup (Docker Compose)

1. Build the image (if you changed code):

```bash
docker build -t rate-limiter .
```

2. Start all services (nginx, api gateways, redis, microservices):

```bash
docker-compose up -d
# rebuild and start whole stack (recommended if code changed)
docker-compose up -d --build
```

3. Verify the system is healthy:

```bash
# nginx LB health
curl http://localhost/nginx-health

# API Gateway health (proxied through nginx)
curl http://localhost/health

# Check a service via the load balancer
curl http://localhost/service-a/status
```

---

## Architecture Overview

Client → nginx:80 → api-gateway-1:8000
                      ↘ api-gateway-2:8000 → services (A:8001, B:8002, C:8003)

- nginx is the single external entrypoint (port 80)
- nginx uses `least_conn` and forwards client IP headers (X-Real-IP, X-Forwarded-For)
- API Gateways share Redis for rate limit state (master/replica in docker-compose)

---

## How to change environment / rate limits

Edit `docker-compose.yml` and set the `ENVIRONMENT` variable for the `api-gateway-*` services, or pass it via the environment when running the containers.

Example (`docker-compose.yml` snippet):

```yaml
services:
  api-gateway-1:
    environment:
      - ENVIRONMENT=dev
      - REDIS_URL=redis://redis-master:6379
      - SERVICE_A_URL=http://service-a:8001
```

You can also override rate limit values directly:

```yaml
  api-gateway-1:
    environment:
      - RATE_LIMIT_RATE=50.0
      - RATE_LIMIT_CAPACITY=100
```

---

## Testing rate limiting (dev/test)

Quick curl loop to observe rate limiting behavior (adjust loop count and sleep for your environment):

```bash
#!/bin/bash
for i in {1..30}; do
  echo "Request $i"
  curl -i -H "X-API-KEY: test-user-123" http://localhost/service-a
  sleep 0.5
done
```

Expected behavior:
- Test env: first 20 requests should succeed, later ones return 429 until tokens refill
- Dev env: ~10 requests/second allowed
- Prod env: ~100 requests/second allowed

---

## Notes

- `start_optimized.py` and the individual `docker run` instructions are deprecated for the compose-based setup and have been removed from this quick start.
- Keep `nginx.conf` and `docker-compose.yml` in sync when changing ports or service names.

If you want, I can also update `README.md` with a short section that mirrors this quick start.
