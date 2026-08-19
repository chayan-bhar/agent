"""
Token counting utilities for managing LLM context window budgets.

Uses tiktoken with cl100k_base encoding (compatible with GPT-4/Gemini
for approximate counting; exact token counts vary by model).

The primary goal is to stay safely under context window limits when
constructing prompts from repository file contents.
"""
from __future__ import annotations

import functools
from typing import Sequence

try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
    _TIKTOKEN_AVAILABLE = True
except Exception:
    _TIKTOKEN_AVAILABLE = False
    _ENCODING = None  # type: ignore[assignment]


# ── Constants ─────────────────────────────────────────────────────────────────

CHARS_PER_TOKEN_FALLBACK = 4  # Rough approximation when tiktoken unavailable


# ── Public API ────────────────────────────────────────────────────────────────


def count_tokens(text: str) -> int:
    """
    Count the approximate number of tokens in a string.

    Uses tiktoken when available, falls back to character-based estimation.
    """
    if not text:
        return 0
    if _TIKTOKEN_AVAILABLE and _ENCODING is not None:
        return len(_ENCODING.encode(text))
    # Fallback: ~4 chars per token
    return max(1, len(text) // CHARS_PER_TOKEN_FALLBACK)


def truncate_to_tokens(text: str, max_tokens: int, suffix: str = "\n[... truncated ...]") -> str:
    """
    Truncate text to fit within a token budget.

    Args:
        text: Input text to truncate.
        max_tokens: Maximum allowed tokens.
        suffix: String appended when truncation occurs.

    Returns:
        Original text if within budget, or truncated text with suffix.
    """
    if count_tokens(text) <= max_tokens:
        return text

    if _TIKTOKEN_AVAILABLE and _ENCODING is not None:
        tokens = _ENCODING.encode(text)
        suffix_tokens = len(_ENCODING.encode(suffix))
        keep = max(0, max_tokens - suffix_tokens)
        truncated = _ENCODING.decode(tokens[:keep])
        return truncated + suffix

    # Fallback: character truncation
    max_chars = max_tokens * CHARS_PER_TOKEN_FALLBACK - len(suffix)
    return text[:max(0, max_chars)] + suffix


def budget_files(
    files: Sequence[tuple[str, str]],  # (path, content)
    total_budget: int,
    per_file_max: int = 3000,
) -> list[tuple[str, str]]:
    """
    Select files that fit within a total token budget.

    Files are processed in the order provided (caller is responsible for
    sorting by priority before calling). Each file is truncated to
    per_file_max tokens. Files are included until the budget is exhausted.

    Args:
        files: Sequence of (path, content) tuples, priority-ordered.
        total_budget: Total token budget across all files.
        per_file_max: Maximum tokens per individual file.

    Returns:
        List of (path, truncated_content) tuples that fit within budget.
    """
    result: list[tuple[str, str]] = []
    remaining = total_budget

    for path, content in files:
        if remaining <= 0:
            break
        # Truncate the file to per_file_max or remaining budget, whichever is smaller
        file_budget = min(per_file_max, remaining)
        truncated = truncate_to_tokens(content, file_budget)
        tokens_used = count_tokens(truncated)
        result.append((path, truncated))
        remaining -= tokens_used

    return result


def format_files_for_prompt(
    files: Sequence[tuple[str, str]],  # (path, content)
    total_budget: int,
    per_file_max: int = 3000,
) -> str:
    """
    Format a list of files as a single string for inclusion in a prompt.

    Each file is wrapped with a clear delimiter so the LLM can distinguish
    individual files. Content is token-budgeted automatically.

    Args:
        files: (path, content) tuples, priority-ordered.
        total_budget: Total token budget for all file content.
        per_file_max: Max tokens per file.

    Returns:
        Formatted multi-file string for prompt injection.
    """
    selected = budget_files(files, total_budget, per_file_max)
    parts: list[str] = []
    for path, content in selected:
        parts.append(f"### FILE: {path}\n```\n{content}\n```")
    return "\n\n".join(parts)
