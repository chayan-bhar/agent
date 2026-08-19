"""
Unit tests for app/utils/github_url.py

Tests cover:
- Valid HTTPS GitHub URLs
- Valid SSH GitHub URLs
- URLs with subpaths (tree/blob)
- .git suffix stripping
- Invalid URLs (non-GitHub, malformed)
- Edge cases (empty string, None, whitespace)
- ParsedGitHubURL properties
"""
from __future__ import annotations

import pytest

from app.utils.github_url import (
    InvalidGitHubURLError,
    ParsedGitHubURL,
    is_valid_github_url,
    parse_github_url,
)


# ── Valid URL parsing ─────────────────────────────────────────────────────────


class TestParseValidHttpsUrls:
    def test_simple_https_url(self) -> None:
        result = parse_github_url("https://github.com/fastapi/fastapi")
        assert result.owner == "fastapi"
        assert result.repo == "fastapi"

    def test_https_with_git_suffix(self) -> None:
        result = parse_github_url("https://github.com/fastapi/fastapi.git")
        assert result.owner == "fastapi"
        assert result.repo == "fastapi"

    def test_https_with_tree_subpath(self) -> None:
        result = parse_github_url("https://github.com/fastapi/fastapi/tree/main")
        assert result.owner == "fastapi"
        assert result.repo == "fastapi"

    def test_https_with_blob_subpath(self) -> None:
        result = parse_github_url("https://github.com/fastapi/fastapi/blob/main/README.md")
        assert result.owner == "fastapi"
        assert result.repo == "fastapi"

    def test_http_without_s(self) -> None:
        result = parse_github_url("http://github.com/owner/repo")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_www_prefix(self) -> None:
        result = parse_github_url("https://www.github.com/owner/repo")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_hyphenated_owner_and_repo(self) -> None:
        result = parse_github_url("https://github.com/my-org/my-project")
        assert result.owner == "my-org"
        assert result.repo == "my-project"

    def test_underscore_and_dot_in_repo(self) -> None:
        result = parse_github_url("https://github.com/owner/my.repo_name")
        assert result.owner == "owner"
        assert result.repo == "my.repo_name"

    def test_url_with_query_string(self) -> None:
        result = parse_github_url("https://github.com/owner/repo?tab=readme")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_trailing_whitespace_stripped(self) -> None:
        result = parse_github_url("  https://github.com/owner/repo  ")
        assert result.owner == "owner"
        assert result.repo == "repo"


class TestParseValidSshUrls:
    def test_ssh_with_git_suffix(self) -> None:
        result = parse_github_url("git@github.com:owner/repo.git")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_ssh_without_git_suffix(self) -> None:
        result = parse_github_url("git@github.com:owner/repo")
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_ssh_with_hyphenated_names(self) -> None:
        result = parse_github_url("git@github.com:my-org/my-project.git")
        assert result.owner == "my-org"
        assert result.repo == "my-project"


# ── ParsedGitHubURL properties ────────────────────────────────────────────────


class TestParsedGitHubURLProperties:
    def setup_method(self) -> None:
        self.parsed = parse_github_url("https://github.com/fastapi/fastapi")

    def test_full_name(self) -> None:
        assert self.parsed.full_name == "fastapi/fastapi"

    def test_canonical_url(self) -> None:
        assert self.parsed.canonical_url == "https://github.com/fastapi/fastapi"

    def test_api_url(self) -> None:
        assert self.parsed.api_url == "https://api.github.com/repos/fastapi/fastapi"

    def test_original_url_preserved(self) -> None:
        raw = "https://github.com/fastapi/fastapi.git"
        parsed = parse_github_url(raw)
        assert parsed.original_url == raw

    def test_immutability(self) -> None:
        """ParsedGitHubURL must be frozen (immutable)."""
        with pytest.raises((AttributeError, TypeError)):
            self.parsed.owner = "other"  # type: ignore[misc]


# ── Invalid URL rejection ─────────────────────────────────────────────────────


class TestInvalidUrls:
    def test_empty_string(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("   ")

    def test_non_github_host(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://gitlab.com/owner/repo")

    def test_bitbucket_host(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://bitbucket.org/owner/repo")

    def test_url_with_only_owner(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://github.com/owner")

    def test_url_with_trailing_slash_no_repo(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://github.com/owner/")

    def test_github_root_url(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://github.com/")

    def test_ftp_scheme(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("ftp://github.com/owner/repo")

    def test_plain_string(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("just-a-string")

    def test_owner_starting_with_hyphen(self) -> None:
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://github.com/-badowner/repo")

    def test_error_contains_url(self) -> None:
        bad_url = "https://notgithub.com/owner/repo"
        with pytest.raises(InvalidGitHubURLError) as exc_info:
            parse_github_url(bad_url)
        assert bad_url in str(exc_info.value)


# ── is_valid_github_url helper ────────────────────────────────────────────────


class TestIsValidGitHubUrl:
    def test_returns_true_for_valid_url(self) -> None:
        assert is_valid_github_url("https://github.com/owner/repo") is True

    def test_returns_false_for_invalid_url(self) -> None:
        assert is_valid_github_url("https://gitlab.com/owner/repo") is False

    def test_returns_false_for_empty_string(self) -> None:
        assert is_valid_github_url("") is False

    def test_does_not_raise(self) -> None:
        """is_valid_github_url must never raise, only return bool."""
        for url in ["", "   ", "not-a-url", None]:  # type: ignore[list-item]
            result = is_valid_github_url(url)  # type: ignore[arg-type]
            assert isinstance(result, bool)
