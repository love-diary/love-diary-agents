"""
Abstract LLM Interface
Defines the interface for all LLM providers (ASI-1 Mini, OpenAI, etc.)
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any
import structlog

from ..config import settings

logger = structlog.get_logger()


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers
    All providers must implement these methods
    """

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Complete a prompt

        Args:
            prompt: The prompt to complete
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            **kwargs: Provider-specific parameters (e.g., reasoning_mode for ASI)

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        pass

    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 200,
        temperature: float = 0.8,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Chat completion with conversation history

        Args:
            system: System prompt
            messages: List of {role, content} messages
            max_tokens: Max tokens
            temperature: Sampling temperature
            **kwargs: Provider-specific parameters

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        pass

    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for text

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding vector
        """
        pass

    @abstractmethod
    async def close(self):
        """Close HTTP client and cleanup resources"""
        pass


def get_llm_provider() -> LLMProvider:
    """
    Factory function to get the configured LLM provider

    Returns:
        LLMProvider instance based on settings.LLM_PROVIDER

    Raises:
        ValueError: If provider is not supported
    """
    provider = settings.LLM_PROVIDER.lower()

    logger.info(
        "llm_provider_factory",
        provider=provider,
        env_llm_provider=settings.LLM_PROVIDER,
        available_providers=["asi", "openai"],
    )

    if provider == "asi":
        from .asi_provider import ASIProvider
        logger.info("llm_provider_selected", provider_class="ASIProvider")
        return ASIProvider()
    elif provider == "openai":
        from .openai_provider import OpenAIProvider
        logger.info("llm_provider_selected", provider_class="OpenAIProvider")
        return OpenAIProvider()
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported providers: asi, openai"
        )
