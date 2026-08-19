"""
LLM Provider abstraction.

All LLM interactions go through this layer. No Gemini-specific code
should appear anywhere else in the codebase.

Extension pattern:
    LLMProvider (ABC)
        ├── GeminiProvider   ← implemented
        ├── OpenAIProvider   ← future
        └── LocalProvider    ← future (Ollama)
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Send a prompt to the LLM and return the raw text response.

        Args:
            system_prompt: System/instruction prompt.
            user_prompt: User message / analysis context.
            temperature: Override provider default temperature.
            max_tokens: Override provider default max output tokens.

        Returns:
            Raw text response from the LLM.
        """

    @abstractmethod
    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: Type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> T:
        """
        Send a prompt and parse the response into a Pydantic model.

        The provider should instruct the LLM to return valid JSON matching
        the schema, then validate and return the parsed model.

        Args:
            system_prompt: System/instruction prompt.
            user_prompt: User message / analysis context.
            output_schema: Pydantic model class to parse the response into.
            temperature: Override provider default temperature.
            max_tokens: Override provider default max output tokens.

        Returns:
            Validated Pydantic model instance.

        Raises:
            ValueError: If the LLM response cannot be parsed into the schema.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g. 'gemini', 'openai')."""
