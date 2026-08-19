"""
Shared pytest fixtures and configuration.

Fixtures defined here are available to all tests without explicit import.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app


# ── Sync test client (for simple endpoint tests) ──────────────────────────────


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Synchronous FastAPI test client for the full application."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Async test client ─────────────────────────────────────────────────────────


@pytest.fixture
async def async_client() -> AsyncClient:
    """Async HTTPX client wired to the FastAPI app (no real network calls)."""
    async with AsyncClient(app=app, base_url="http://testserver") as ac:
        yield ac


# ── GitHub URL fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def valid_github_urls() -> list[str]:
    return [
        "https://github.com/fastapi/fastapi",
        "https://github.com/fastapi/fastapi.git",
        "https://github.com/fastapi/fastapi/tree/main",
        "https://github.com/fastapi/fastapi/blob/main/README.md",
        "http://github.com/owner/repo",
        "git@github.com:owner/repo.git",
        "git@github.com:owner/repo",
        "https://github.com/my-org/my.repo_name",
    ]


@pytest.fixture
def invalid_github_urls() -> list[str]:
    return [
        "",
        "   ",
        "not-a-url",
        "https://gitlab.com/owner/repo",
        "https://github.com/",
        "https://github.com/owner",
        "https://github.com/owner/",
        "https://github.com/-invalid-owner/repo",
        "https://github.com/owner/-invalid-repo",
        "ftp://github.com/owner/repo",
    ]


# ── File filter fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def sample_repository_files() -> list[tuple[str, int]]:
    """Representative sample of repository file paths with sizes."""
    return [
        ("README.md", 5_000),
        ("package.json", 2_000),
        ("src/index.ts", 3_000),
        ("src/api/router.ts", 4_000),
        ("src/services/userService.ts", 6_000),
        ("src/models/user.ts", 2_500),
        ("tests/unit/userService.test.ts", 3_000),
        ("node_modules/react/index.js", 10_000),  # SKIP
        ("yarn.lock", 500_000),  # SKIP
        ("dist/bundle.js", 200_000),  # SKIP
        ("Dockerfile", 1_500),
        ("docker-compose.yml", 2_000),
        (".github/workflows/ci.yml", 3_000),
        ("src/utils/helpers.ts", 2_000),
        ("src/auth/middleware.ts", 4_000),
        ("openapi.yaml", 8_000),
        ("src/logo.png", 50_000),  # SKIP
    ]
