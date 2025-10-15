"""
Configuration management using Pydantic Settings
"""

from pydantic import BaseSettings  # Pydantic 1.x has BaseSettings built-in
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Service Configuration
    PORT: int = 8000
    DEBUG: bool = False
    ALLOWED_ORIGINS: List[str] = ["*"]  # Configure in production

    # Authentication
    AGENT_SERVICE_SECRET: str = "change-me-in-production"

    # Blockchain
    BASE_RPC_URL: str = "https://sepolia.base.org"
    CHARACTER_NFT_ADDRESS: str

    # AI/LLM
    ASI_MINI_API_KEY: str
    ASI_MINI_API_URL: str = "https://api.asi1mini.com/v1"  # Placeholder

    # Database (PostgreSQL via Supabase)
    DATABASE_URL: str

    # Agent Configuration
    AGENT_IDLE_TIMEOUT: int = 3600  # 1 hour in seconds
    AGENT_HIBERNATION_CHECK_INTERVAL: int = 300  # 5 minutes
    MAX_ACTIVE_AGENTS: int = 50  # Maximum agents to keep in memory

    # Redis (optional, for distributed setup)
    REDIS_URL: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True


# Singleton instance
settings = Settings()
