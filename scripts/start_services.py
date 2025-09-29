#!/usr/bin/env python3
"""
Script to start all services in the rate limiter system.

Usage:
    python scripts/start_services.py [--dev] [--service SERVICE_NAME]

Options:
    --dev: Start in development mode with auto-reload
    --service: Start only a specific service (gateway, service-a, service-b, service-c)
"""

import subprocess
import sys
import time
import argparse
import signal
import os
from pathlib import Path

# Service configurations
SERVICES = {
    "gateway": {
        "module": "src.gateway.api_gateway:app",
        "port": 8000,
        "description": "API Gateway with Rate Limiter"
    },
    "service-a": {
        "module": "src.services.service_a:app",
        "port": 8001,
        "description": "Microservice A"
    },
    "service-b": {
        "module": "src.services.service_b:app",
        "port": 8002,
        "description": "Microservice B"
    },
    "service-c": {
        "module": "src.services.service_c:app",
        "port": 8003,
        "description": "Microservice C"
    }
}

class ServiceManager:
    def __init__(self, dev_mode=False):
        self.dev_mode = dev_mode
        self.processes = {}
        self.running = True

    def start_service(self, name, config):
        """Start a single service"""
        print(f"Starting {config['description']} on port {config['port']}...")

        cmd = [
            "uvicorn",
            config["module"],
            "--host", "0.0.0.0",
            "--port", str(config["port"])
        ]

        if self.dev_mode:
            cmd.extend(["--reload", "--log-level", "debug"])

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            self.processes[name] = process
            print(f"✓ {name} started (PID: {process.pid})")
            return process
        except Exception as e:
            print(f"✗ Failed to start {name}: {e}")
            return None

    def start_all_services(self):
        """Start all services"""
        print("🚀 Starting Rate Limiter System...")
        print("=" * 50)

        for name, config in SERVICES.items():
            self.start_service(name, config)
            time.sleep(1)  # Small delay between service starts

        print("\n" + "=" * 50)
        print("📊 Service Status:")
        self.print_status()

        print("\n🌐 Available Endpoints:")
        print("  • API Gateway:    http://localhost:8000")
        print("  • Service A:      http://localhost:8001")
        print("  • Service B:      http://localhost:8002")
        print("  • Service C:      http://localhost:8003")
        print("  • Gateway Docs:   http://localhost:8000/docs")
        print("  • Health Check:   http://localhost:8000/health")

    def start_single_service(self, service_name):
        """Start a single service by name"""
        if service_name not in SERVICES:
            print(f"❌ Unknown service: {service_name}")
            print(f"Available services: {', '.join(SERVICES.keys())}")
            return

        config = SERVICES[service_name]
        print(f"🚀 Starting {config['description']}...")

        process = self.start_service(service_name, config)
        if process:
            print(f"\n🌐 Service available at: http://localhost:{config['port']}")

    def print_status(self):
        """Print status of all services"""
        for name, process in self.processes.items():
            if process and process.poll() is None:
                print(f"  ✓ {name:<12} Running (PID: {process.pid})")
            else:
                print(f"  ✗ {name:<12} Stopped")

    def stop_all_services(self):
        """Stop all running services"""
        print("\n🛑 Stopping all services...")
        self.running = False

        for name, process in self.processes.items():
            if process and process.poll() is None:
                print(f"  Stopping {name}...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                    print(f"  ✓ {name} stopped")
                except subprocess.TimeoutExpired:
                    print(f"  Force killing {name}...")
                    process.kill()

        print("✅ All services stopped")

    def monitor_services(self):
        """Monitor services and restart if they crash"""
        print("\n👀 Monitoring services (Ctrl+C to stop)...")

        try:
            while self.running:
                time.sleep(5)

                for name, process in list(self.processes.items()):
                    if process.poll() is not None:
                        print(f"⚠️  {name} crashed! Restarting...")
                        config = SERVICES[name]
                        new_process = self.start_service(name, config)
                        if new_process:
                            self.processes[name] = new_process

        except KeyboardInterrupt:
            self.stop_all_services()

def check_dependencies():
    """Check if required dependencies are available"""
    try:
        import redis
        import fastapi
        import uvicorn
        print("✅ All dependencies available")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please install dependencies: pip install -r requirements.txt")
        return False

def check_redis():
    """Check if Redis is available"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("✅ Redis is running")
        return True
    except Exception as e:
        print(f"⚠️  Redis check failed: {e}")
        print("Please ensure Redis is running on localhost:6379")
        print("You can start Redis with Docker: docker run -p 6379:6379 redis:alpine")
        return False

def main():
    parser = argparse.ArgumentParser(description="Start Rate Limiter System Services")
    parser.add_argument("--dev", action="store_true", help="Enable development mode")
    parser.add_argument("--service", help="Start only specific service", choices=list(SERVICES.keys()))
    parser.add_argument("--no-deps-check", action="store_true", help="Skip dependency checks")
    args = parser.parse_args()

    # Check dependencies
    if not args.no_deps_check:
        if not check_dependencies():
            sys.exit(1)
        check_redis()  # Warning only, not fatal

    # Create service manager
    manager = ServiceManager(dev_mode=args.dev)

    # Setup signal handler for graceful shutdown
    def signal_handler(signum, frame):
        manager.stop_all_services()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if args.service:
            # Start single service
            manager.start_single_service(args.service)
            if args.service in manager.processes:
                # Monitor single service
                process = manager.processes[args.service]
                process.wait()
        else:
            # Start all services
            manager.start_all_services()
            manager.monitor_services()

    except Exception as e:
        print(f"❌ Error: {e}")
        manager.stop_all_services()
        sys.exit(1)

if __name__ == "__main__":
    main()