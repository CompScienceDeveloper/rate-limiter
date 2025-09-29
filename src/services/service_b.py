from fastapi import FastAPI
import uvicorn
import time
import random
import asyncio

# Create Service B
app = FastAPI(
    title="Microservice B",
    description="Example microservice behind rate limiter",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint for Service B"""
    return {
        "service": "B",
        "message": "Hello from Service B!",
        "timestamp": time.time()
    }

@app.get("/users")
async def get_users():
    """Get user data from Service B"""
    # Simulate database query time
    query_time = random.uniform(0.05, 0.3)
    await asyncio.sleep(query_time)

    users = [
        {"id": i, "name": f"User {i}", "email": f"user{i}@example.com"}
        for i in range(1, random.randint(5, 15))
    ]

    return {
        "service": "B",
        "users": users,
        "count": len(users),
        "query_time": query_time,
        "timestamp": time.time()
    }

@app.post("/users")
async def create_user(user_data: dict):
    """Create a new user in Service B"""
    # Simulate user creation
    await asyncio.sleep(0.1)

    new_user = {
        "id": random.randint(1000, 9999),
        "name": user_data.get("name", "Unknown"),
        "email": user_data.get("email", "unknown@example.com"),
        "created_at": time.time()
    }

    return {
        "service": "B",
        "action": "user_created",
        "user": new_user,
        "timestamp": time.time()
    }

@app.get("/analytics")
async def get_analytics():
    """Get analytics data from Service B"""
    # Simulate complex analytics query
    await asyncio.sleep(random.uniform(0.2, 0.8))

    analytics = {
        "total_users": random.randint(1000, 10000),
        "active_users": random.randint(100, 1000),
        "daily_signups": random.randint(10, 100),
        "revenue": random.uniform(1000, 50000)
    }

    return {
        "service": "B",
        "analytics": analytics,
        "generated_at": time.time()
    }

@app.get("/health")
async def health_check():
    """Health check for Service B"""
    return {
        "service": "B",
        "status": "healthy",
        "database": "connected",
        "timestamp": time.time()
    }

if __name__ == "__main__":
    uvicorn.run(
        "src.services.service_b:app",
        host="0.0.0.0",
        port=8002,
        reload=True
    )