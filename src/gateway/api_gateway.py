from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
import os
from typing import Dict, Any
import uvicorn

from ..rate_limiter.service import rate_limiter_service
from .middleware import RateLimitMiddleware, RequestLoggingMiddleware
from ..config.constants import RATE_LIMIT_DESCRIPTION

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Rate Limiter API Gateway",
    description="High-performance distributed rate limiter using Token Bucket algorithm",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs (can be configured via environment variables)
SERVICES = {
    "service-a": os.getenv("SERVICE_A_URL", "http://localhost:8001"),
    "service-b": os.getenv("SERVICE_B_URL", "http://localhost:8002"),
    "service-c": os.getenv("SERVICE_C_URL", "http://localhost:8003")
}

@app.on_event("startup")
async def startup_event():
    """Initialize rate limiter service on startup"""
    try:
        await rate_limiter_service.initialize()
        logger.info("API Gateway started successfully")
    except Exception as e:
        logger.error(f"Failed to start API Gateway: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await rate_limiter_service.close()
    logger.info("API Gateway shut down")

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware, rate_limiter_service=rate_limiter_service)
app.add_middleware(RequestLoggingMiddleware)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    service_health = await rate_limiter_service.health_check()
    return {
        "status": "healthy",
        "timestamp": "2025-09-29T00:00:00Z",
        "services": service_health
    }

@app.get("/rate-limit/status")
async def get_rate_limit_status(request: Request):
    """Get current rate limit status for client"""
    status = await rate_limiter_service.get_rate_limit_status(request)
    return status

@app.post("/rate-limit/reset")
async def reset_rate_limit(request: Request):
    """Reset rate limit for client (admin endpoint)"""
    success = await rate_limiter_service.reset_rate_limit(request)
    return {"success": success}

# Microservice proxy endpoints
async def proxy_request(service_name: str, path: str, request: Request):
    """Proxy request to microservice"""
    if service_name not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found")

    service_url = SERVICES[service_name]
    target_url = f"{service_url}/{path}"

    try:
        async with httpx.AsyncClient() as client:
            # Forward the request to the microservice
            response = await client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items()
                        if k.lower() not in ["host", "content-length"]},
                content=await request.body(),
                timeout=30.0
            )

            # Return the response from microservice
            return JSONResponse(
                content=response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
                status_code=response.status_code,
                headers=dict(response.headers)
            )

    except httpx.RequestError as e:
        logger.error(f"Error proxying request to {service_name}: {e}")
        raise HTTPException(status_code=503, detail=f"Service {service_name} unavailable")
    except Exception as e:
        logger.error(f"Unexpected error proxying request: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.api_route("/service-a/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_service_a(path: str, request: Request):
    """Proxy requests to Service A"""
    return await proxy_request("service-a", path, request)

@app.api_route("/service-b/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_service_b(path: str, request: Request):
    """Proxy requests to Service B"""
    return await proxy_request("service-b", path, request)

@app.api_route("/service-c/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_service_c(path: str, request: Request):
    """Proxy requests to Service C"""
    return await proxy_request("service-c", path, request)

# Direct API Gateway endpoints (not proxied)
@app.get("/")
async def root():
    """Root endpoint with system information"""
    return {
        "message": "Rate Limiter API Gateway",
        "version": "1.0.0",
        "algorithm": "Token Bucket",
        "rate": RATE_LIMIT_DESCRIPTION,
        "services": list(SERVICES.keys()),
        "docs": "/docs"
    }

@app.get("/stats")
async def get_stats(request: Request):
    """Get rate limiting statistics"""
    status = await rate_limiter_service.get_rate_limit_status(request)
    client_id = rate_limiter_service.extract_client_id(request)

    return {
        "client_id": client_id,
        "current_tokens": status["tokens"],
        "capacity": status["capacity"],
        "rate": status["rate"],
        "last_refill": status["last_refill"]
    }

if __name__ == "__main__":
    uvicorn.run(
        "src.gateway.api_gateway:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )