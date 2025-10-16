"""
ASI-1 Mini LLM Provider
Implements LLMProvider interface for ASI-1 Mini API
"""

import httpx
from typing import Dict, List, Any
import structlog

from ..config import settings
from .interface import LLMProvider

logger = structlog.get_logger()


class ASIProvider(LLMProvider):
    """
    ASI-1 Mini LLM Provider
    Supports different reasoning modes for various use cases
    """

    def __init__(self):
        self.api_url = settings.ASI_MINI_API_URL
        self.api_key = settings.ASI_MINI_API_KEY
        self.client = httpx.AsyncClient(timeout=18.0)
        logger.info("asi_provider_initialized", api_url=self.api_url)

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 500,
        temperature: float = 0.7,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Complete a prompt with ASI-1 Mini

        Args:
            prompt: The prompt to complete
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            **kwargs: Supports reasoning_mode ("Short" | "Optimized" | "Multi-Step" | "Complete")

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        reasoning_mode = kwargs.get("reasoning_mode", "Short")

        try:
            payload = {
                "model": "asi1-mini",
                "messages": [{"role": "user", "content": prompt}],
                "reasoning_mode": reasoning_mode,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            logger.info(
                "asi_completion_request",
                url=f"{self.api_url}/chat/completions",
                model=payload["model"],
                reasoning_mode=reasoning_mode,
                max_tokens=max_tokens,
                temperature=temperature,
                prompt_length=len(prompt),
                prompt=prompt,
            )

            response = await self.client.post(
                f"{self.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            response.raise_for_status()
            data = response.json()

            logger.info(
                "asi_completion_response",
                reasoning_mode=reasoning_mode,
                tokens=data.get("usage", {}).get("total_tokens", 0),
                response_length=len(data["choices"][0]["message"]["content"]),
                response=data["choices"][0]["message"]["content"],
            )

            return {
                "text": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
                "reasoning_time": data.get("reasoning_time", 0),
            }

        except httpx.TimeoutException:
            logger.error("asi_completion_timeout")
            raise Exception(
                f"ASI-1 Mini API timeout (>{self.client.timeout.read}s): {self.api_url}/chat/completions"
            )
        except Exception as e:
            logger.error("asi_completion_failed", error=str(e))
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
            **kwargs: Provider-specific parameters (reasoning_mode not used for chat)

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        try:
            payload = {
                "model": "asi1-mini",
                "messages": [{"role": "system", "content": system}] + messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            # Note: reasoning_mode might not be supported in chat completions
            # Only add it if explicitly requested
            if "reasoning_mode" in kwargs:
                payload["reasoning_mode"] = kwargs["reasoning_mode"]

            # Log request for debugging
            logger.info(
                "asi_chat_request",
                url=f"{self.api_url}/chat/completions",
                model=payload["model"],
                message_count=len(messages),
                max_tokens=max_tokens,
                temperature=temperature,
                system_length=len(system),
                system=system,
                user_message=messages[0]["content"] if messages else "",
            )

            response = await self.client.post(
                f"{self.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            response.raise_for_status()
            data = response.json()

            logger.info(
                "asi_chat_response",
                tokens=data.get("usage", {}).get("total_tokens", 0),
                response_length=len(data["choices"][0]["message"]["content"]),
                response=data["choices"][0]["message"]["content"],
            )

            return {
                "text": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
                "reasoning_time": data.get("reasoning_time", 0),
            }

        except httpx.TimeoutException:
            logger.error("asi_chat_timeout")
            raise Exception(
                f"ASI-1 Mini API timeout (>{self.client.timeout.read}s): {self.api_url}/chat/completions"
            )
        except Exception as e:
            logger.error("asi_chat_failed", error=str(e))
            raise

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
        logger.info("asi_provider_closed")
