"""
OpenAI GPT-4o LLM Provider
Implements LLMProvider interface using LiteLLM for OpenAI API
"""

from typing import Dict, List, Any
import structlog
import litellm

from ..config import settings
from .interface import LLMProvider

logger = structlog.get_logger()


class OpenAIProvider(LLMProvider):
    """
    OpenAI GPT-4o LLM Provider using LiteLLM
    Provides a unified interface for OpenAI models
    """

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.model = "gpt-4o"  # GPT-4o model

        # Configure LiteLLM
        litellm.api_key = self.api_key
        litellm.set_verbose = settings.DEBUG  # Enable verbose logging in debug mode

        logger.info(
            "openai_provider_initialized",
            model=self.model,
            api_key_set=bool(self.api_key),
        )

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Complete a prompt with GPT-4o

        Args:
            prompt: The prompt to complete
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            **kwargs: Additional parameters (reasoning_mode is ignored for OpenAI)

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        try:
            # Ignore reasoning_mode for OpenAI
            if "reasoning_mode" in kwargs:
                logger.debug(
                    "openai_ignoring_reasoning_mode",
                    reasoning_mode=kwargs["reasoning_mode"],
                )

            logger.info(
                "openai_completion_request",
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                prompt_length=len(prompt),
                prompt=prompt,
            )

            response = await litellm.acompletion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=18.0,  # Match ASI timeout
            )

            # Extract response text
            response_text = response.choices[0].message.content

            # Extract usage stats
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            logger.info(
                "openai_completion_response",
                tokens=usage["total_tokens"],
                response_length=len(response_text),
                response=response_text,
            )

            return {
                "text": response_text,
                "usage": usage,
                "reasoning_time": 0,  # OpenAI doesn't provide reasoning time
            }

        except litellm.exceptions.Timeout:
            logger.error("openai_completion_timeout")
            raise Exception(
                f"OpenAI API timeout (>18s): model={self.model}"
            )
        except Exception as e:
            logger.error("openai_completion_failed", error=str(e))
            raise

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
            **kwargs: Additional parameters (reasoning_mode is ignored for OpenAI)

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        try:
            # Ignore reasoning_mode for OpenAI
            if "reasoning_mode" in kwargs:
                logger.debug(
                    "openai_ignoring_reasoning_mode",
                    reasoning_mode=kwargs["reasoning_mode"],
                )

            # Build message list with system prompt
            full_messages = [{"role": "system", "content": system}] + messages

            logger.info(
                "openai_chat_request",
                model=self.model,
                message_count=len(messages),
                max_tokens=max_tokens,
                temperature=temperature,
                system_length=len(system),
                system=system,
                user_message=messages[0]["content"] if messages else "",
            )

            response = await litellm.acompletion(
                model=self.model,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=18.0,  # Match ASI timeout
            )

            # Extract response text
            response_text = response.choices[0].message.content

            # Extract usage stats
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            logger.info(
                "openai_chat_response",
                tokens=usage["total_tokens"],
                response_length=len(response_text),
                response=response_text,
            )

            return {
                "text": response_text,
                "usage": usage,
                "reasoning_time": 0,  # OpenAI doesn't provide reasoning time
            }

        except litellm.exceptions.Timeout:
            logger.error("openai_chat_timeout")
            raise Exception(
                f"OpenAI API timeout (>18s): model={self.model}"
            )
        except Exception as e:
            logger.error("openai_chat_failed", error=str(e))
            raise

    async def close(self):
        """Close HTTP client (LiteLLM handles cleanup internally)"""
        logger.info("openai_provider_closed")
        # LiteLLM manages its own connection pool, no explicit cleanup needed
