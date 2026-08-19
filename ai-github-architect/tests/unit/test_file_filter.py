"""
Unit tests for app/utils/file_filter.py

Tests cover:
- SKIP patterns (binaries, lock files, node_modules, build artifacts)
- CRITICAL patterns (README, package.json, Dockerfile, etc.)
- HIGH patterns (controllers, services, repositories, etc.)
- MEDIUM patterns (tests, utilities)
- LOW fallback for unrecognized files
- File size limits
- Skip directories
- rank_and_filter with budget cap
- format_files_for_prompt output
"""
from __future__ import annotations

import pytest

from app.utils.file_filter import FilePriority, FileRelevanceScorer, ScoredFile


@pytest.fixture
def scorer() -> FileRelevanceScorer:
    return FileRelevanceScorer(max_file_size_kb=500)


# ── SKIP patterns ─────────────────────────────────────────────────────────────


class TestSkipPatterns:
    def test_node_modules_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("node_modules/react/index.js")
        assert result.priority == FilePriority.SKIP

    def test_git_dir_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score(".git/config")
        assert result.priority == FilePriority.SKIP

    def test_dist_dir_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("dist/bundle.min.js")
        assert result.priority == FilePriority.SKIP

    def test_yarn_lock_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("yarn.lock")
        assert result.priority == FilePriority.SKIP

    def test_package_lock_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("package-lock.json")
        assert result.priority == FilePriority.SKIP

    def test_poetry_lock_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("poetry.lock")
        assert result.priority == FilePriority.SKIP

    def test_png_image_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("assets/logo.png")
        assert result.priority == FilePriority.SKIP

    def test_pyc_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("app/__pycache__/main.cpython-311.pyc")
        assert result.priority == FilePriority.SKIP

    def test_file_exceeding_size_limit_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/huge_file.js", size_bytes=600 * 1024)  # 600 KB
        assert result.priority == FilePriority.SKIP
        assert "exceeds size limit" in result.reason

    def test_file_within_size_limit_not_skipped(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/index.js", size_bytes=100 * 1024)  # 100 KB
        assert result.priority != FilePriority.SKIP


# ── CRITICAL patterns ─────────────────────────────────────────────────────────


class TestCriticalPatterns:
    def test_readme_md(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("README.md")
        assert result.priority == FilePriority.CRITICAL

    def test_readme_lowercase(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("readme.md")
        assert result.priority == FilePriority.CRITICAL

    def test_package_json(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("package.json")
        assert result.priority == FilePriority.CRITICAL

    def test_pyproject_toml(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("pyproject.toml")
        assert result.priority == FilePriority.CRITICAL

    def test_requirements_txt(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("requirements.txt")
        assert result.priority == FilePriority.CRITICAL

    def test_dockerfile(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("Dockerfile")
        assert result.priority == FilePriority.CRITICAL

    def test_docker_compose(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("docker-compose.yml")
        assert result.priority == FilePriority.CRITICAL

    def test_application_yml(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("application.yml")
        assert result.priority == FilePriority.CRITICAL

    def test_pom_xml(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("pom.xml")
        assert result.priority == FilePriority.CRITICAL

    def test_main_py(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("main.py")
        assert result.priority == FilePriority.CRITICAL

    def test_github_ci_workflow(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score(".github/workflows/ci.yml")
        assert result.priority == FilePriority.CRITICAL


# ── HIGH patterns ─────────────────────────────────────────────────────────────


class TestHighPatterns:
    def test_service_file(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/services/userService.ts")
        assert result.priority == FilePriority.HIGH

    def test_controller_file(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/api/userController.py")
        assert result.priority == FilePriority.HIGH

    def test_repository_file(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/repositories/userRepository.java")
        assert result.priority == FilePriority.HIGH

    def test_auth_middleware(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/auth/middleware.py")
        assert result.priority == FilePriority.HIGH

    def test_terraform_file(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("infra/main.tf")
        assert result.priority == FilePriority.HIGH

    def test_openapi_yaml(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("openapi.yaml")
        assert result.priority == FilePriority.HIGH


# ── MEDIUM patterns ───────────────────────────────────────────────────────────


class TestMediumPatterns:
    def test_test_file_python(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("tests/unit/test_user.py")
        assert result.priority == FilePriority.MEDIUM

    def test_spec_file_typescript(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/user.spec.ts")
        assert result.priority == FilePriority.MEDIUM

    def test_util_file(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/utils/helpers.py")
        assert result.priority == FilePriority.MEDIUM

    def test_makefile(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("Makefile")
        assert result.priority == FilePriority.MEDIUM


# ── LOW fallback ──────────────────────────────────────────────────────────────


class TestLowFallback:
    def test_unrecognized_source_file(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/random_module.py")
        assert result.priority == FilePriority.LOW

    def test_should_include_is_true_for_low(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/random_module.py")
        assert result.should_include is True

    def test_is_skipped_false_for_low(self, scorer: FileRelevanceScorer) -> None:
        result = scorer.score("src/random_module.py")
        assert result.is_skipped is False


# ── rank_and_filter ───────────────────────────────────────────────────────────


class TestRankAndFilter:
    def test_returns_sorted_by_priority_desc(
        self, scorer: FileRelevanceScorer, sample_repository_files: list[tuple[str, int]]
    ) -> None:
        results = scorer.rank_and_filter(sample_repository_files, max_files=100)
        priorities = [f.priority for f in results]
        assert priorities == sorted(priorities, reverse=True)

    def test_skips_are_excluded(
        self, scorer: FileRelevanceScorer, sample_repository_files: list[tuple[str, int]]
    ) -> None:
        results = scorer.rank_and_filter(sample_repository_files, max_files=100)
        assert all(not f.is_skipped for f in results)

    def test_max_files_cap_respected(
        self, scorer: FileRelevanceScorer, sample_repository_files: list[tuple[str, int]]
    ) -> None:
        results = scorer.rank_and_filter(sample_repository_files, max_files=3)
        assert len(results) <= 3

    def test_critical_files_appear_first(
        self, scorer: FileRelevanceScorer, sample_repository_files: list[tuple[str, int]]
    ) -> None:
        results = scorer.rank_and_filter(sample_repository_files, max_files=100)
        assert results[0].priority == FilePriority.CRITICAL

    def test_empty_input(self, scorer: FileRelevanceScorer) -> None:
        results = scorer.rank_and_filter([], max_files=10)
        assert results == []


# ── ScoredFile helpers ────────────────────────────────────────────────────────


class TestScoredFile:
    def test_should_include_high(self) -> None:
        f = ScoredFile("path", FilePriority.HIGH, "reason")
        assert f.should_include is True

    def test_should_include_skip(self) -> None:
        f = ScoredFile("path", FilePriority.SKIP, "reason")
        assert f.should_include is False

    def test_is_skipped(self) -> None:
        f = ScoredFile("path", FilePriority.SKIP, "reason")
        assert f.is_skipped is True
