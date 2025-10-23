"""
Configuration management using Pydantic Settings
"""

from pydantic_settings import BaseSettings  # Pydantic 2.x
from pydantic import ConfigDict
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
    LOVE_TOKEN_ADDRESS: str

    # Wallet Management
    WALLET_ENCRYPTION_KEY: str  # Fernet key for encrypting character wallet private keys

    # AI/LLM
    LLM_PROVIDER: str = "asi"  # "asi" or "openai"
    ASI_MINI_API_KEY: str = ""
    ASI_MINI_API_URL: str = "https://api.asi1mini.com/v1"  # Placeholder
    OPENAI_API_KEY: str = ""

    # Database (PostgreSQL via Supabase)
    DATABASE_URL: str

    # Agent Configuration
    AGENT_IDLE_TIMEOUT: int = 3600  # 1 hour in seconds
    AGENT_HIBERNATION_CHECK_INTERVAL: int = 300  # 5 minutes
    MAX_ACTIVE_AGENTS: int = 50  # Maximum agents to keep in memory

    # Redis (optional, for distributed setup)
    REDIS_URL: str = ""

    # Pydantic v2 configuration
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
    )


# Singleton instance
settings = Settings()
