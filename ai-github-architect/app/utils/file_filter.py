"""
File relevance scoring system.

Determines which files in a repository are worth sending to the LLM for analysis.
This is the primary mechanism for staying within context window limits.

Priority levels:
  HIGH    — Always include; critical for understanding the project
  MEDIUM  — Include when budget allows
  LOW     — Skip unless explicitly needed
  SKIP    — Never include (binaries, lock files, generated artifacts, etc.)
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import PurePosixPath
from typing import Sequence


# ── Priority Enum ─────────────────────────────────────────────────────────────


class FilePriority(IntEnum):
    """Integer priority — higher = more important."""
    SKIP = -1
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


# ── Pattern Tables ────────────────────────────────────────────────────────────

# Patterns matched against the **full relative path** (case-insensitive).
# Order: most specific first; first match wins.

_SKIP_PATTERNS: list[str] = [
    # Binary / media
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.ico", "*.webp",
    "*.mp4", "*.mp3", "*.wav", "*.pdf", "*.zip", "*.tar.gz", "*.tgz",
    "*.7z", "*.rar", "*.exe", "*.dll", "*.so", "*.dylib", "*.whl",
    "*.jar", "*.class", "*.pyc",
    # Lock files (too large / machine-generated)
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "go.sum", "composer.lock",
    # Generated / build artifacts  (.git is handled via _SKIP_DIRS)
    "node_modules/**", "dist/**", "build/**", "target/**",
    "__pycache__/**", ".pytest_cache/**", ".mypy_cache/**",
    "*.egg-info/**", "htmlcov/**", ".tox/**",
    # IDE / OS
    ".idea/**", ".vscode/**", "*.DS_Store", "Thumbs.db",
    # Coverage / test reports
    "coverage.xml", "*.lcov",
]

_CRITICAL_PATTERNS: list[str] = [
    # Entry points & manifests
    "readme.md", "readme.rst", "readme.txt", "readme",
    "package.json",
    "pom.xml",
    "build.gradle", "build.gradle.kts",
    "requirements.txt", "requirements/*.txt",
    "pyproject.toml", "setup.py", "setup.cfg",
    "cargo.toml",
    "go.mod",
    "composer.json",
    "gemfile",
    # Infrastructure
    "dockerfile", "dockerfile.*",
    "docker-compose.yml", "docker-compose.yaml", "docker-compose.*.yml",
    # Config / environment
    "application.yml", "application.yaml",
    "application.properties",
    "application-*.yml", "application-*.yaml",
    "config.yml", "config.yaml", "config.json",
    ".env.example", ".env.sample",
    "settings.py", "config.py", "configuration.py",
    # CI/CD
    ".github/workflows/*.yml", ".github/workflows/*.yaml",
    ".gitlab-ci.yml",
    "jenkinsfile",
    "azure-pipelines.yml",
    ".circleci/config.yml",
    # Main application files
    "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
    "main.go", "main.ts", "main.js", "index.ts", "index.js",
    "main.rs", "lib.rs",
    "program.cs",
    "application.java",
]

_HIGH_PATTERNS: list[str] = [
    # Controllers / routes / views
    "*controller*", "*router*", "*route*", "*view*", "*handler*",
    "*endpoint*", "*api*",
    # Services / business logic
    "*service*", "*usecase*", "*use_case*", "*interactor*", "*manager*",
    # Data access
    "*repository*", "*repo*", "*dao*", "*store*", "*database*",
    "*migration*", "*schema*",
    # Domain model
    "*model*", "*entity*", "*domain*",
    # Security
    "*auth*", "*security*", "*permission*", "*middleware*",
    # Configuration
    "*config*", "*settings*", "*constants*", "*env*",
    # DI / bootstrapping
    "*container*", "*injector*", "*factory*", "*bootstrap*", "*startup*",
    "*application*",
    # K8s / Helm
    "k8s/**", "helm/**", "kubernetes/**",
    "*.tf", "*.tfvars",  # Terraform
    # OpenAPI
    "openapi.yml", "openapi.yaml", "swagger.yml", "swagger.yaml",
]

_MEDIUM_PATTERNS: list[str] = [
    # Utilities / helpers
    "*util*", "*helper*", "*common*", "*shared*",
    # DTOs / schemas / types
    "*dto*", "*schema*", "*type*", "*interface*",
    # Tests (give signal about coverage)
    "test_*.py", "*_test.py", "*.test.ts", "*.spec.ts",
    "*.test.js", "*.spec.js",
    "*test*/**",
    # Documentation
    "docs/**", "doc/**",
    # Scripts
    "scripts/**", "script/**",
    # Makefile
    "makefile", "makefile.*",
]

# Directories that should be entirely skipped
_SKIP_DIRS: set[str] = {
    "node_modules", ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    "dist", "build", "target", ".tox", ".eggs", "htmlcov",
    ".idea", ".vscode", "vendor",
}


# ── Scoring Result ────────────────────────────────────────────────────────────


@dataclass
class ScoredFile:
    """A file with its computed relevance priority."""

    path: str
    priority: FilePriority
    reason: str
    size_bytes: int = 0

    @property
    def should_include(self) -> bool:
        return self.priority >= FilePriority.LOW

    @property
    def is_skipped(self) -> bool:
        return self.priority == FilePriority.SKIP


# ── Core Scorer ───────────────────────────────────────────────────────────────


class FileRelevanceScorer:
    """
    Scores repository files by their relevance to architectural analysis.

    The scorer is stateless and thread-safe; create one instance and reuse it.
    """

    def __init__(self, max_file_size_kb: int = 500) -> None:
        self._max_file_size_bytes = max_file_size_kb * 1024

    # ── Public interface ──────────────────────────────────────────────────────

    def score(self, path: str, size_bytes: int = 0) -> ScoredFile:
        """Score a single file path."""
        normalized = path.lower().replace("\\", "/")
        pure = PurePosixPath(normalized)

        # 1. Check if any path component is a skip directory
        if self._in_skip_dir(pure):
            return ScoredFile(path, FilePriority.SKIP, "skip directory", size_bytes)

        # 2. File size guard
        if size_bytes > self._max_file_size_bytes:
            return ScoredFile(
                path, FilePriority.SKIP,
                f"exceeds size limit ({size_bytes // 1024}KB)", size_bytes,
            )

        # 3. Pattern matching (most restrictive first)
        for pattern in _SKIP_PATTERNS:
            if _match(normalized, pattern):
                return ScoredFile(path, FilePriority.SKIP, f"skip pattern: {pattern}", size_bytes)

        for pattern in _CRITICAL_PATTERNS:
            if _match(normalized, pattern):
                return ScoredFile(path, FilePriority.CRITICAL, f"critical: {pattern}", size_bytes)

        for pattern in _HIGH_PATTERNS:
            if _match(normalized, pattern):
                return ScoredFile(path, FilePriority.HIGH, f"high: {pattern}", size_bytes)

        for pattern in _MEDIUM_PATTERNS:
            if _match(normalized, pattern):
                return ScoredFile(path, FilePriority.MEDIUM, f"medium: {pattern}", size_bytes)

        return ScoredFile(path, FilePriority.LOW, "no specific pattern matched", size_bytes)

    def rank_and_filter(
        self,
        files: Sequence[tuple[str, int]],  # (path, size_bytes)
        max_files: int = 150,
        min_priority: FilePriority = FilePriority.LOW,
    ) -> list[ScoredFile]:
        """
        Score, filter, sort by priority, and cap at max_files.

        Args:
            files: Iterable of (path, size_bytes) tuples.
            max_files: Maximum number of files to return.
            min_priority: Exclude files with priority below this.

        Returns:
            Sorted list of ScoredFile (CRITICAL first, LOW last).
        """
        scored = [self.score(path, size) for path, size in files]
        filtered = [f for f in scored if f.priority >= min_priority]
        filtered.sort(key=lambda f: (-f.priority.value, f.path))
        return filtered[:max_files]

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _in_skip_dir(pure: PurePosixPath) -> bool:
        # Check if any path component (except the final filename) is a skip dir.
        # Use exact equality to avoid matching .github when .git is in skip set.
        return any(part in _SKIP_DIRS for part in pure.parts[:-1])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _match(path: str, pattern: str) -> bool:
    """Match a path against a glob pattern (case-insensitive)."""
    # Handle ** glob (directory wildcard)
    if "**" in pattern:
        prefix = pattern.split("**")[0].rstrip("/")
        return path.startswith(prefix) if prefix else True
    # fnmatch handles * and ? within a single path component
    filename = path.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(path, pattern)
