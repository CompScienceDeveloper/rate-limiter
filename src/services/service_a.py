from fastapi import FastAPI
import uvicorn
import time
import random
import asyncio

# Create Service A
app = FastAPI(
    title="Microservice A",
    description="Example microservice behind rate limiter",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint for Service A"""
    return {
        "service": "A",
        "message": "Hello from Service A!",
        "timestamp": time.time()
    }

@app.get("/data")
async def get_data():
    """Get some data from Service A"""
    # Simulate some processing time
    processing_time = random.uniform(0.1, 0.5)
    await asyncio.sleep(processing_time)

    return {
        "service": "A",
        "data": [
            {"id": 1, "name": "Item 1", "value": random.randint(1, 100)},
            {"id": 2, "name": "Item 2", "value": random.randint(1, 100)},
            {"id": 3, "name": "Item 3", "value": random.randint(1, 100)}
        ],
        "processing_time": processing_time
    }

@app.post("/process")
async def process_data(data: dict):
    """Process some data in Service A"""
    # Simulate processing
    result = {
        "service": "A",
        "processed": True,
        "input": data,
        "result": f"Processed {len(str(data))} characters",
        "timestamp": time.time()
    }
    return result

@app.get("/health")
async def health_check():
    """Health check for Service A"""
    return {
        "service": "A",
        "status": "healthy",
        "timestamp": time.time()
    }

@app.get("/load")
async def simulate_load():
    """Simulate high load operation"""
    # Simulate some CPU intensive work
    start = time.time()
    result = sum(i * i for i in range(10000))
    end = time.time()

    return {
        "service": "A",
        "operation": "load_simulation",
        "result": result,
        "execution_time": end - start,
        "timestamp": time.time()
    }

if __name__ == "__main__":
    uvicorn.run(
        "src.services.service_a:app",
        host="0.0.0.0",
        port=8001,
        reload=True
    )