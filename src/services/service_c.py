from fastapi import FastAPI
import uvicorn
import time
import random
import asyncio

# Create Service C
app = FastAPI(
    title="Microservice C",
    description="Example microservice behind rate limiter",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint for Service C"""
    return {
        "service": "C",
        "message": "Hello from Service C!",
        "timestamp": time.time()
    }

@app.get("/orders")
async def get_orders():
    """Get order data from Service C"""
    # Simulate database query
    await asyncio.sleep(random.uniform(0.1, 0.4))

    orders = [
        {
            "id": 1000 + i,
            "customer_id": random.randint(1, 100),
            "total": random.uniform(10.0, 500.0),
            "status": random.choice(["pending", "processing", "shipped", "delivered"])
        }
        for i in range(random.randint(3, 10))
    ]

    return {
        "service": "C",
        "orders": orders,
        "count": len(orders),
        "timestamp": time.time()
    }

@app.post("/orders")
async def create_order(order_data: dict):
    """Create a new order in Service C"""
    # Simulate order processing
    await asyncio.sleep(random.uniform(0.1, 0.3))

    new_order = {
        "id": random.randint(10000, 99999),
        "customer_id": order_data.get("customer_id", 1),
        "items": order_data.get("items", []),
        "total": order_data.get("total", 0.0),
        "status": "pending",
        "created_at": time.time()
    }

    return {
        "service": "C",
        "action": "order_created",
        "order": new_order,
        "timestamp": time.time()
    }

@app.get("/inventory")
async def get_inventory():
    """Get inventory data from Service C"""
    await asyncio.sleep(random.uniform(0.05, 0.2))

    inventory = [
        {
            "product_id": i,
            "name": f"Product {i}",
            "quantity": random.randint(0, 100),
            "price": random.uniform(10.0, 200.0)
        }
        for i in range(1, random.randint(10, 25))
    ]

    return {
        "service": "C",
        "inventory": inventory,
        "total_items": len(inventory),
        "timestamp": time.time()
    }

@app.get("/reports")
async def get_reports():
    """Generate reports in Service C"""
    # Simulate heavy report generation
    await asyncio.sleep(random.uniform(0.5, 1.5))

    report = {
        "total_orders": random.randint(1000, 5000),
        "total_revenue": random.uniform(50000, 500000),
        "top_products": [
            {"name": f"Product {i}", "sales": random.randint(50, 500)}
            for i in range(1, 6)
        ],
        "period": "last_30_days"
    }

    return {
        "service": "C",
        "report": report,
        "generated_at": time.time()
    }

@app.get("/health")
async def health_check():
    """Health check for Service C"""
    return {
        "service": "C",
        "status": "healthy",
        "database": "connected",
        "cache": "active",
        "timestamp": time.time()
    }

if __name__ == "__main__":
    uvicorn.run(
        "src.services.service_c:app",
        host="0.0.0.0",
        port=8003,
        reload=True
    )