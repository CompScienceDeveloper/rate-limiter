from fastapi import FastAPI
import uvicorn
import time
import asyncio

# Minimal Service A: keep only health and a single test endpoint for rate-limiter tests
app = FastAPI(
    title="Microservice A",
    description="Minimal microservice used for rate limiter testing",
    version="1.0.0",
)


@app.get("/health")
async def health_check():
    """Health check for Service A"""
    return {"service": "A", "status": "healthy", "timestamp": time.time()}


@app.get("/test")
async def test_endpoint(delay: float = 0.0):
    """Single test endpoint for rate limiter tests.

    - delay: non-blocking simulated latency (seconds). Uses asyncio.sleep so the event loop stays responsive.
    """
    await asyncio.sleep(delay)
    return {"service": "A", "test": True, "delay": delay, "timestamp": time.time()}


if __name__ == "__main__":
    uvicorn.run("src.services.service_a:app", host="0.0.0.0", port=8001, reload=True)