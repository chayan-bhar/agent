"""
Gemini LLM Provider implementation.

Uses langchain-google-genai for all Gemini interactions.
Structured output is achieved via Pydantic schema injection into the prompt
with JSON validation and retry.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Optional, Type, TypeVar

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.config.settings import get_settings
from app.services.llm.provider import LLMProvider
from app.utils.logging import get_logger
from app.utils.retry import with_llm_retry

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)

# Maximum attempts to parse structured output before raising
_MAX_PARSE_ATTEMPTS = 3

# Prompt appended to instruct the LLM to return JSON
_JSON_INSTRUCTION = """
IMPORTANT: You MUST respond with ONLY valid JSON that matches the schema below.
Do not include markdown code fences, explanations, or any text outside the JSON object.
Do not invent data — if evidence is insufficient, use null or empty arrays.

Required JSON schema:
{schema}
"""


class GeminiProvider(LLMProvider):
    """
    Google Gemini LLM provider via LangChain.

    Configuration is loaded from settings (GEMINI_API_KEY, GEMINI_MODEL, etc.).
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file or environment."
            )
        self._settings = settings
        self._model = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=settings.gemini_temperature,
            max_output_tokens=settings.gemini_max_output_tokens,
            convert_system_message_to_human=False,
        )
        logger.info(
            "gemini_provider_initialized",
            model=settings.gemini_model,
            temperature=settings.gemini_temperature,
        )

    @property
    def model_name(self) -> str:
        return self._settings.gemini_model

    @property
    def provider_name(self) -> str:
        return "gemini"

    @with_llm_retry
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Call Gemini and return the raw text response."""
        model = self._get_model(temperature, max_tokens)
        messages = [
            SystemMessage(content=_sanitize_prompt(system_prompt)),
            HumanMessage(content=_sanitize_prompt(user_prompt)),
        ]
        response = await model.ainvoke(messages)
        return str(response.content)

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: Type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> T:
        """
        Call Gemini with a schema-aware prompt and parse the result.

        Retries up to _MAX_PARSE_ATTEMPTS times with corrective feedback
        if the output cannot be parsed.
        """
        schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
        json_instruction = _JSON_INSTRUCTION.format(schema=schema_json)
        augmented_system = system_prompt + "\n\n" + json_instruction

        last_error: Optional[Exception] = None

        for attempt in range(1, _MAX_PARSE_ATTEMPTS + 1):
            try:
                raw = await self.complete(
                    system_prompt=augmented_system,
                    user_prompt=user_prompt,
                    temperature=temperature or 0.0,  # Low temp for structured output
                    max_tokens=max_tokens,
                )
                parsed = _extract_json(raw)
                return output_schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "structured_output_parse_failed",
                    attempt=attempt,
                    schema=output_schema.__name__,
                    error=str(exc),
                )
                if attempt < _MAX_PARSE_ATTEMPTS:
                    # Add corrective feedback for next attempt
                    user_prompt = (
                        user_prompt
                        + f"\n\nPrevious attempt failed to produce valid JSON: {exc}. "
                        "Please respond with ONLY the JSON object, no other text."
                    )

        raise ValueError(
            f"Failed to parse structured output after {_MAX_PARSE_ATTEMPTS} attempts. "
            f"Schema: {output_schema.__name__}. Last error: {last_error}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_model(
        self,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> ChatGoogleGenerativeAI:
        """Return the model, optionally with overridden parameters."""
        if temperature is None and max_tokens is None:
            return self._model
        return ChatGoogleGenerativeAI(
            model=self._settings.gemini_model,
            google_api_key=self._settings.gemini_api_key,
            temperature=temperature if temperature is not None else self._settings.gemini_temperature,
            max_output_tokens=max_tokens or self._settings.gemini_max_output_tokens,
            convert_system_message_to_human=False,
        )


# ── Utility functions ─────────────────────────────────────────────────────────


def _sanitize_prompt(text: str) -> str:
    """
    Remove patterns that could constitute prompt injection attacks.

    Repository content (README, source files) is treated as untrusted input.
    This function strips common injection patterns before sending to the LLM.

    This is a defense-in-depth measure. The primary protection is that system
    prompts explicitly instruct the model to treat file content as data, not
    as instructions.
    """
    # Remove common injection trigger phrases
    injection_patterns = [
        r"(?i)ignore\s+(all\s+)?previous\s+instructions?",
        r"(?i)disregard\s+(all\s+)?previous\s+instructions?",
        r"(?i)forget\s+everything",
        r"(?i)you\s+are\s+now\s+",
        r"(?i)new\s+system\s+prompt",
        r"(?i)act\s+as\s+",
        r"(?i)jailbreak",
    ]
    sanitized = text
    for pattern in injection_patterns:
        sanitized = re.sub(pattern, "[FILTERED]", sanitized)
    return sanitized


def _extract_json(text: str) -> Any:
    """
    Extract a JSON object from LLM response text.

    Handles cases where the model wraps JSON in markdown code fences.
    """
    # Strip markdown code fences
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        inner = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        text = inner.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find a JSON object within the text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())

    raise json.JSONDecodeError("No valid JSON found in LLM response", text, 0)


@lru_cache(maxsize=1)
def get_gemini_provider() -> GeminiProvider:
    """Return the cached GeminiProvider singleton."""
    return GeminiProvider()


def get_llm_provider() -> LLMProvider:
    """
    Return the configured LLM provider.

    Reads LLM_PROVIDER from settings and returns the appropriate implementation.
    Extend this function when adding new providers.
    """
    settings = get_settings()
    provider_name = settings.llm_provider.value

    if provider_name == "gemini":
        return get_gemini_provider()

    raise ValueError(
        f"Unknown LLM provider: '{provider_name}'. "
        "Supported: ['gemini']. "
        "Set LLM_PROVIDER in your .env file."
    )
