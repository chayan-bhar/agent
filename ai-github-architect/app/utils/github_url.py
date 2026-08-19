"""
GitHub URL parsing and validation utilities.

Handles various GitHub URL formats:
  - https://github.com/owner/repo
  - https://github.com/owner/repo.git
  - https://github.com/owner/repo/tree/main
  - git@github.com:owner/repo.git   (SSH — normalized to HTTPS)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# ── Constants ─────────────────────────────────────────────────────────────────

# GitHub owner / repo name constraints:
# - owner: alphanumeric, hyphens (no leading/trailing), 1–39 chars
# - repo: alphanumeric, hyphens, dots, underscores, 1–100 chars
_OWNER_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,37}[a-zA-Z0-9])?$")
_REPO_RE = re.compile(r"^[a-zA-Z0-9_.\-]{1,100}$")

# HTTPS pattern: https://github.com/<owner>/<repo>[/...]
_HTTPS_PATTERN = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/?#]+?)(?:\.git)?(?:[/?#].*)?$",
    re.IGNORECASE,
)

# SSH pattern: git@github.com:<owner>/<repo>[.git]
_SSH_PATTERN = re.compile(
    r"^git@github\.com:([^/]+)/([^/?#]+?)(?:\.git)?$",
    re.IGNORECASE,
)


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedGitHubURL:
    """Structured result from parsing a GitHub URL."""

    owner: str
    repo: str
    original_url: str

    @property
    def full_name(self) -> str:
        """Return '<owner>/<repo>' identifier used by the GitHub API."""
        return f"{self.owner}/{self.repo}"

    @property
    def canonical_url(self) -> str:
        """Return normalized HTTPS URL without .git suffix."""
        return f"https://github.com/{self.owner}/{self.repo}"

    @property
    def api_url(self) -> str:
        """Return the GitHub REST API v3 repository URL."""
        return f"https://api.github.com/repos/{self.owner}/{self.repo}"


# ── Exceptions ────────────────────────────────────────────────────────────────


class InvalidGitHubURLError(ValueError):
    """Raised when the provided string is not a valid GitHub repository URL."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Invalid GitHub URL '{url}': {reason}")


# ── Public API ────────────────────────────────────────────────────────────────


def parse_github_url(url: str) -> ParsedGitHubURL:
    """
    Parse a GitHub repository URL and return a structured result.

    Supports HTTPS and SSH formats. Strips .git suffix, query strings,
    and subpaths (e.g. /tree/main).

    Args:
        url: Raw GitHub URL string supplied by the user.

    Returns:
        ParsedGitHubURL with owner, repo, and helper properties.

    Raises:
        InvalidGitHubURLError: If the URL cannot be parsed or fails validation.
    """
    if not url or not isinstance(url, str):
        raise InvalidGitHubURLError(str(url), "URL must be a non-empty string")

    raw = url.strip()

    # Try SSH first, then HTTPS
    match = _SSH_PATTERN.match(raw) or _HTTPS_PATTERN.match(raw)
    if not match:
        raise InvalidGitHubURLError(
            raw,
            "URL must be a GitHub repository URL "
            "(e.g. https://github.com/owner/repo)",
        )

    owner, repo = match.group(1), match.group(2)

    # Validate owner
    if not _OWNER_RE.match(owner):
        raise InvalidGitHubURLError(
            raw,
            f"Invalid owner name '{owner}'. "
            "Must be 1–39 alphanumeric characters or hyphens.",
        )

    # Validate repo
    if not _REPO_RE.match(repo):
        raise InvalidGitHubURLError(
            raw,
            f"Invalid repository name '{repo}'. "
            "Must be 1–100 alphanumeric characters, hyphens, dots, or underscores.",
        )

    return ParsedGitHubURL(owner=owner, repo=repo, original_url=raw)


def is_valid_github_url(url: str) -> bool:
    """Return True if the URL is a valid GitHub repository URL, False otherwise."""
    try:
        parse_github_url(url)
        return True
    except InvalidGitHubURLError:
        return False
