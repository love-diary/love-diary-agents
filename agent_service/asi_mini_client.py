"""
ASI-1 Mini LLM Client
Wrapper for ASI-1 Mini API with different reasoning modes
"""

import httpx
from typing import Dict, List, Optional, Any
import structlog

from .config import settings

logger = structlog.get_logger()


class ASIMiniClient:
    """
    Client for ASI-1 Mini LLM API
    Supports different reasoning modes for various use cases
    """

    def __init__(self):
        self.api_url = settings.ASI_MINI_API_URL
        self.api_key = settings.ASI_MINI_API_KEY
        self.client = httpx.AsyncClient(timeout=30.0)

    async def complete(
        self,
        prompt: str,
        reasoning_mode: str = "Short",
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Complete a prompt with ASI-1 Mini

        Args:
            prompt: The prompt to complete
            reasoning_mode: "Short" | "Optimized" | "Multi-Step" | "Complete"
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        try:
            response = await self.client.post(
                f"{self.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "asi1-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "reasoning_mode": reasoning_mode,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )

            response.raise_for_status()
            data = response.json()

            logger.info(
                "llm_completion",
                reasoning_mode=reasoning_mode,
                tokens=data.get("usage", {}).get("total_tokens", 0),
            )

            return {
                "text": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
                "reasoning_time": data.get("reasoning_time", 0),
            }

        except Exception as e:
            logger.error("llm_completion_failed", error=str(e))
            # Fallback to simple response
            return {"text": self._fallback_response(prompt), "usage": {}, "reasoning_time": 0}

    async def chat(
        self,
        system: str,
        messages: List[Dict[str, str]],
        reasoning_mode: str = "Short",
        max_tokens: int = 200,
        temperature: float = 0.8,
    ) -> Dict[str, Any]:
        """
        Chat completion with conversation history

        Args:
            system: System prompt
            messages: List of {role, content} messages
            reasoning_mode: Reasoning mode to use
            max_tokens: Max tokens
            temperature: Sampling temperature

        Returns:
            Dict with {text, usage, reasoning_time}
        """
        try:
            response = await self.client.post(
                f"{self.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "asi1-mini",
                    "messages": [{"role": "system", "content": system}] + messages,
                    "reasoning_mode": reasoning_mode,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )

            response.raise_for_status()
            data = response.json()

            logger.info(
                "llm_chat",
                reasoning_mode=reasoning_mode,
                tokens=data.get("usage", {}).get("total_tokens", 0),
            )

            return {
                "text": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
                "reasoning_time": data.get("reasoning_time", 0),
            }

        except Exception as e:
            logger.error("llm_chat_failed", error=str(e))
            # Fallback
            user_message = next(
                (m["content"] for m in messages if m["role"] == "user"), ""
            )
            return {
                "text": self._fallback_response(user_message),
                "usage": {},
                "reasoning_time": 0,
            }

    def _fallback_response(self, prompt: str) -> str:
        """Simple fallback when API fails"""
        if "background story" in prompt.lower():
            return "I grew up in a small town and have always been passionate about my work. Over the years, I've learned a lot about myself and what I want in life. Meeting new people is exciting, and I'm looking forward to getting to know you better."

        return "That's interesting! Tell me more about yourself."

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
