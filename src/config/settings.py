import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    Configuration for the rate limiter system according to the spec:
    - Redis cluster configuration for 20 nodes handling 1M requests/second
    - Token bucket parameters (100 requests/second per user)
    - Service URLs and clustering options
    """

    # Redis Configuration
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_cluster_urls: Optional[str] = os.getenv("REDIS_CLUSTER_URLS")  # Comma-separated URLs
    redis_password: Optional[str] = os.getenv("REDIS_PASSWORD")
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_max_connections: int = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))

    # Rate Limiting Configuration
    default_rate_limit: int = int(os.getenv("DEFAULT_RATE_LIMIT", "100"))  # tokens per second
    default_bucket_capacity: int = int(os.getenv("DEFAULT_BUCKET_CAPACITY", "100"))  # max tokens
    burst_allowance: float = float(os.getenv("BURST_ALLOWANCE", "1.5"))  # 150% of normal rate

    # System Performance Settings
    target_latency_ms: int = int(os.getenv("TARGET_LATENCY_MS", "10"))  # <10ms requirement
    max_requests_per_second: int = int(os.getenv("MAX_RPS", "1000000"))  # 1M requests/second

    # JWT Configuration
    jwt_secret: str = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")

    # API Gateway Configuration
    gateway_host: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    gateway_port: int = int(os.getenv("GATEWAY_PORT", "8000"))

    # Microservice URLs
    service_a_url: str = os.getenv("SERVICE_A_URL", "http://localhost:8001")
    service_b_url: str = os.getenv("SERVICE_B_URL", "http://localhost:8002")
    service_c_url: str = os.getenv("SERVICE_C_URL", "http://localhost:8003")

    # Logging Configuration
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    enable_request_logging: bool = os.getenv("ENABLE_REQUEST_LOGGING", "true").lower() == "true"

    # Health Check Configuration
    health_check_interval: int = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))  # seconds
    redis_ping_timeout: int = int(os.getenv("REDIS_PING_TIMEOUT", "5"))  # seconds

    # Rate Limiter Behavior
    availability_over_consistency: bool = os.getenv("AVAILABILITY_OVER_CONSISTENCY", "true").lower() == "true"
    fallback_on_redis_error: bool = os.getenv("FALLBACK_ON_REDIS_ERROR", "true").lower() == "true"

    # Security Settings
    enable_cors: bool = os.getenv("ENABLE_CORS", "true").lower() == "true"
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")

    # Monitoring and Metrics
    enable_metrics: bool = os.getenv("ENABLE_METRICS", "true").lower() == "true"
    metrics_port: int = int(os.getenv("METRICS_PORT", "9090"))

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def get_redis_cluster_urls(self) -> list:
        """Parse Redis cluster URLs from environment variable"""
        if self.redis_cluster_urls:
            return [url.strip() for url in self.redis_cluster_urls.split(",")]
        return [self.redis_url]

    def get_cors_origins(self) -> list:
        """Parse CORS origins from environment variable"""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]

# Global settings instance
settings = Settings()