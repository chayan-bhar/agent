"""
GitHub MCP Server — Tool Implementations.

Each function here is a standalone tool that will be exposed via FastMCP.
Tools interact ONLY with the GitHub API — no LLM logic here.

All tools return plain Python dicts (JSON-serializable) so the MCP
protocol can serialize them efficiently.

Rate limiting and caching are handled at the MCP client layer (Redis).
"""
from __future__ import annotations

import base64
import fnmatch
from typing import Any, Optional

from github import Github, GithubException, UnknownObjectException
from github.Repository import Repository

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Directories / files to exclude when building the file tree
_TREE_EXCLUDE_DIRS = {
    "node_modules", ".git", "__pycache__", "dist", "build", "target",
    ".tox", ".eggs", "htmlcov", ".idea", ".vscode", "vendor",
}

_TREE_EXCLUDE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".pdf", ".zip", ".tar", ".gz",
    ".exe", ".dll", ".so", ".dylib", ".whl", ".jar", ".class",
    ".pyc", ".pyo", ".lock",
}


# ── GitHub Client Factory ─────────────────────────────────────────────────────

def _get_github_client() -> Github:
    """Create an authenticated GitHub client from settings."""
    settings = get_settings()
    token = settings.github_token
    return Github(token if token else None, per_page=100)


def _get_repo(owner: str, repo: str) -> Repository:
    """Fetch a GitHub repository object, raising clear errors."""
    g = _get_github_client()
    try:
        return g.get_repo(f"{owner}/{repo}")
    except UnknownObjectException:
        raise ValueError(f"Repository '{owner}/{repo}' not found or is private.")
    except GithubException as exc:
        if exc.status == 403:
            raise PermissionError(
                f"Access denied to '{owner}/{repo}'. "
                "Provide a GITHUB_TOKEN with repo read access."
            )
        raise RuntimeError(f"GitHub API error: {exc.data}") from exc


# ── Tool Implementations ───────────────────────────────────────────────────────


def get_repository_info(owner: str, repo: str) -> dict[str, Any]:
    """
    Fetch high-level metadata about a GitHub repository.

    Returns name, description, language, stars, forks, topics,
    license, default branch, size, and timestamps.
    """
    logger.info("mcp_tool_called", tool="get_repository_info", owner=owner, repo=repo)
    repository = _get_repo(owner, repo)

    license_info = None
    if repository.license:
        license_info = {
            "key": repository.license.key,
            "name": repository.license.name,
            "spdx_id": repository.license.spdx_id,
        }

    return {
        "name": repository.name,
        "full_name": repository.full_name,
        "description": repository.description,
        "private": repository.private,
        "fork": repository.fork,
        "default_branch": repository.default_branch,
        "language": repository.language,
        "languages_url": repository.languages_url,
        "size_kb": repository.size,
        "stars": repository.stargazers_count,
        "forks": repository.forks_count,
        "open_issues": repository.open_issues_count,
        "topics": repository.get_topics(),
        "license": license_info,
        "created_at": repository.created_at.isoformat() if repository.created_at else None,
        "updated_at": repository.updated_at.isoformat() if repository.updated_at else None,
        "pushed_at": repository.pushed_at.isoformat() if repository.pushed_at else None,
        "html_url": repository.html_url,
        "clone_url": repository.clone_url,
        "homepage": repository.homepage,
        "has_wiki": repository.has_wiki,
        "has_issues": repository.has_issues,
        "archived": repository.archived,
    }


def get_languages(owner: str, repo: str) -> dict[str, int]:
    """
    Return the programming languages used in the repository.

    Returns a dict mapping language name to bytes of code.
    Example: {"Python": 45320, "TypeScript": 12800}
    """
    logger.info("mcp_tool_called", tool="get_languages", owner=owner, repo=repo)
    repository = _get_repo(owner, repo)
    return dict(repository.get_languages())


def get_directory_tree(
    owner: str,
    repo: str,
    max_depth: int = 4,
    max_files: int = 500,
) -> dict[str, Any]:
    """
    Build a filtered directory tree of the repository.

    Excludes binary files, lock files, build artifacts, and common
    non-essential directories.

    Args:
        owner: Repository owner.
        repo: Repository name.
        max_depth: Maximum directory depth to traverse.
        max_files: Maximum number of files to return.

    Returns:
        Dict with 'tree' (list of file entries) and 'truncated' flag.
    """
    logger.info("mcp_tool_called", tool="get_directory_tree", owner=owner, repo=repo)
    repository = _get_repo(owner, repo)
    settings = get_settings()
    max_file_bytes = settings.github_max_file_size_kb * 1024

    try:
        git_tree = repository.get_git_tree(
            sha=repository.default_branch, recursive=True
        )
    except GithubException as exc:
        raise RuntimeError(f"Failed to fetch repository tree: {exc}") from exc

    files: list[dict[str, Any]] = []
    truncated = False

    for element in git_tree.tree:
        if element.type != "blob":
            continue

        path: str = element.path
        parts = path.split("/")

        # Depth check
        if len(parts) > max_depth + 1:
            continue

        # Skip excluded directories
        if any(p in _TREE_EXCLUDE_DIRS for p in parts[:-1]):
            continue

        # Skip by extension
        ext = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
        if ext.lower() in _TREE_EXCLUDE_EXTENSIONS:
            continue

        # Skip oversized files
        file_size = element.size or 0
        if file_size > max_file_bytes:
            continue

        if len(files) >= max_files:
            truncated = True
            break

        files.append({
            "path": path,
            "size_bytes": file_size,
            "sha": element.sha,
            "type": "file",
        })

    logger.info(
        "directory_tree_built",
        owner=owner,
        repo=repo,
        file_count=len(files),
        truncated=truncated,
    )

    return {
        "owner": owner,
        "repo": repo,
        "default_branch": repository.default_branch,
        "tree": files,
        "total_files": len(files),
        "truncated": truncated,
    }


def list_repository_files(
    owner: str,
    repo: str,
    path: str = "",
) -> list[dict[str, Any]]:
    """
    List files and directories at a specific path in the repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        path: Subdirectory path (empty string = root).

    Returns:
        List of dicts with name, path, type (file/dir), size.
    """
    logger.info("mcp_tool_called", tool="list_repository_files", owner=owner, repo=repo, path=path)
    repository = _get_repo(owner, repo)

    try:
        contents = repository.get_contents(path or "")
    except UnknownObjectException:
        raise ValueError(f"Path '{path}' not found in {owner}/{repo}.")
    except GithubException as exc:
        raise RuntimeError(f"Failed to list files at '{path}': {exc}") from exc

    if not isinstance(contents, list):
        contents = [contents]

    return [
        {
            "name": item.name,
            "path": item.path,
            "type": item.type,  # "file" or "dir"
            "size_bytes": item.size if item.type == "file" else None,
            "sha": item.sha,
            "download_url": item.download_url,
        }
        for item in contents
    ]


def get_file_content(
    owner: str,
    repo: str,
    file_path: str,
    ref: Optional[str] = None,
) -> dict[str, Any]:
    """
    Retrieve the decoded content of a single file.

    Args:
        owner: Repository owner.
        repo: Repository name.
        file_path: Path to the file (e.g. "src/main.py").
        ref: Branch, tag, or commit SHA (defaults to default branch).

    Returns:
        Dict with path, content (decoded), size, encoding, sha.
    """
    logger.info(
        "mcp_tool_called",
        tool="get_file_content",
        owner=owner,
        repo=repo,
        path=file_path,
    )
    settings = get_settings()
    repository = _get_repo(owner, repo)

    try:
        kwargs: dict[str, Any] = {}
        if ref:
            kwargs["ref"] = ref
        file_obj = repository.get_contents(file_path, **kwargs)
    except UnknownObjectException:
        raise ValueError(f"File '{file_path}' not found in {owner}/{repo}.")
    except GithubException as exc:
        raise RuntimeError(f"Failed to fetch file '{file_path}': {exc}") from exc

    if isinstance(file_obj, list):
        raise ValueError(f"'{file_path}' is a directory, not a file.")

    # Size guard
    size_bytes = file_obj.size or 0
    max_bytes = settings.github_max_file_size_kb * 1024
    if size_bytes > max_bytes:
        return {
            "path": file_path,
            "content": None,
            "size_bytes": size_bytes,
            "truncated": True,
            "error": (
                f"File exceeds size limit ({size_bytes // 1024}KB > "
                f"{settings.github_max_file_size_kb}KB). Skipped."
            ),
            "sha": file_obj.sha,
        }

    # Decode content
    try:
        if file_obj.encoding == "base64" and file_obj.content:
            content = base64.b64decode(file_obj.content).decode("utf-8", errors="replace")
        else:
            content = file_obj.decoded_content.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("file_decode_error", path=file_path, error=str(exc))
        content = f"[Binary or undecodable content — {size_bytes} bytes]"

    return {
        "path": file_path,
        "content": content,
        "size_bytes": size_bytes,
        "truncated": False,
        "encoding": "utf-8",
        "sha": file_obj.sha,
        "html_url": file_obj.html_url,
    }


def search_repository(
    owner: str,
    repo: str,
    query: str,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """
    Search for code within a repository using GitHub code search.

    Args:
        owner: Repository owner.
        repo: Repository name.
        query: Search query string.
        max_results: Maximum number of results.

    Returns:
        List of matching code items with path and fragment.
    """
    logger.info("mcp_tool_called", tool="search_repository", owner=owner, repo=repo, query=query)
    g = _get_github_client()

    try:
        results = g.search_code(f"{query} repo:{owner}/{repo}")
        items = []
        for item in results[:max_results]:
            items.append({
                "path": item.path,
                "name": item.name,
                "sha": item.sha,
                "html_url": item.html_url,
                "repository": item.repository.full_name,
            })
        return items
    except GithubException as exc:
        logger.warning("search_failed", query=query, error=str(exc))
        return []


def get_recent_commits(
    owner: str,
    repo: str,
    max_commits: int = 20,
    branch: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Return recent commits for the repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        max_commits: Maximum number of commits to return.
        branch: Branch name (defaults to default branch).

    Returns:
        List of commit dicts with sha, message, author, date.
    """
    logger.info("mcp_tool_called", tool="get_recent_commits", owner=owner, repo=repo)
    repository = _get_repo(owner, repo)

    kwargs: dict[str, Any] = {}
    if branch:
        kwargs["sha"] = branch

    commits = []
    for commit in repository.get_commits(**kwargs)[:max_commits]:
        commits.append({
            "sha": commit.sha[:10],
            "message": commit.commit.message.split("\n")[0],  # First line only
            "author": commit.commit.author.name if commit.commit.author else "Unknown",
            "author_email": commit.commit.author.email if commit.commit.author else None,
            "date": commit.commit.author.date.isoformat() if commit.commit.author else None,
            "html_url": commit.html_url,
        })

    return commits


def get_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    max_prs: int = 10,
) -> list[dict[str, Any]]:
    """
    Return pull requests for the repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: "open", "closed", or "all".
        max_prs: Maximum number of PRs to return.
    """
    logger.info("mcp_tool_called", tool="get_pull_requests", owner=owner, repo=repo)
    repository = _get_repo(owner, repo)

    prs = []
    for pr in repository.get_pulls(state=state, sort="updated", direction="desc")[:max_prs]:
        prs.append({
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "author": pr.user.login if pr.user else None,
            "created_at": pr.created_at.isoformat() if pr.created_at else None,
            "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
            "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
            "base_branch": pr.base.ref,
            "head_branch": pr.head.ref,
            "html_url": pr.html_url,
            "additions": pr.additions,
            "deletions": pr.deletions,
            "changed_files": pr.changed_files,
            "body_preview": (pr.body or "")[:200],
        })

    return prs


def get_issues(
    owner: str,
    repo: str,
    state: str = "open",
    max_issues: int = 10,
) -> list[dict[str, Any]]:
    """
    Return issues for the repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: "open", "closed", or "all".
        max_issues: Maximum number of issues to return.
    """
    logger.info("mcp_tool_called", tool="get_issues", owner=owner, repo=repo)
    repository = _get_repo(owner, repo)

    issues = []
    for issue in repository.get_issues(state=state, sort="updated", direction="desc")[:max_issues]:
        if issue.pull_request:  # Skip PRs (GitHub includes them in issues)
            continue
        issues.append({
            "number": issue.number,
            "title": issue.title,
            "state": issue.state,
            "author": issue.user.login if issue.user else None,
            "created_at": issue.created_at.isoformat() if issue.created_at else None,
            "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
            "closed_at": issue.closed_at.isoformat() if issue.closed_at else None,
            "labels": [label.name for label in issue.labels],
            "html_url": issue.html_url,
            "body_preview": (issue.body or "")[:200],
            "comments": issue.comments,
        })

    return issues
