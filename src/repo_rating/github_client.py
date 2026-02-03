"""GitHub API client for fetching repository data."""

import io
import tarfile
import tempfile
from pathlib import Path
from datetime import datetime

import httpx

from .models import RepoMetadata, CommitInfo
from .log import get_logger


GITHUB_API = "https://api.github.com"


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner and repo name from GitHub URL or owner/repo format.
    
    Accepts:
        - https://github.com/owner/repo
        - github.com/owner/repo
        - owner/repo
    """
    url = url.rstrip("/")
    
    # Remove protocol and domain
    for prefix in ["https://github.com/", "http://github.com/", "github.com/"]:
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    
    # Remove .git suffix
    if url.endswith(".git"):
        url = url[:-4]
    
    parts = url.split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid GitHub URL: {url}")
    
    return parts[0], parts[1]


def parse_repo_source(source: str, token: str | None = None) -> tuple[str, str]:
    """Parse repo source into (owner, repo) tuple.
    
    Accepts:
        - Just repo name (requires token): myrepo
        - Owner/repo format: owner/repo
        - Full URL: https://github.com/owner/repo
    
    Returns:
        Tuple of (owner, repo_name)
    """
    from pathlib import Path
    
    is_url = source.startswith(("https://", "http://", "github.com"))
    has_slash = "/" in source
    
    if is_url or has_slash:
        return parse_github_url(source)
    else:
        # Just repo name - need authenticated user
        if not token:
            raise ValueError("No GitHub token configured. Use owner/repo format or set GITHUB_TOKEN.")
        user_info = get_authenticated_user(token)
        return user_info["login"], source


def build_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def get_authenticated_user(token: str) -> dict:
    """Get info about the authenticated user."""
    resp = httpx.get(
        f"{GITHUB_API}/user",
        headers=build_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def resolve_username(username: str, token: str | None) -> tuple[str, bool]:
    """Resolve 'me' to actual username.
    
    Returns:
        (actual_username, is_me) tuple
    """
    is_me = username.lower() == "me"
    if is_me:
        if not token:
            raise ValueError("GitHub token required to use 'me'. Set GITHUB_TOKEN.")
        user_info = get_authenticated_user(token)
        return user_info["login"], True
    return username, False


def fetch_user_repos(
    username: str,
    token: str | None,
    *,
    exclude: set[str] | None = None,
    min_size: int = 5,
    limit: int = 10,
    include_forks: bool = False,
) -> list[dict]:
    """Fetch, filter, and sort repos for a user.
    
    Handles 'me' resolution, excludes forks, applies size/exclusion filters.
    
    Returns:
        List of repo dicts, sorted by recent activity
    """
    log = get_logger()
    
    actual_username, is_me = resolve_username(username, token)
    
    if is_me:
        log.info(f"Fetching your repos (as {actual_username})")
    else:
        log.info(f"Fetching repos for user: {username}")
    
    # Fetch repos
    user_arg = None if is_me else username
    repos = list_user_repos(user_arg, token)
    print("AZEAZEAZ",len(repos))
    # Filter to owned repos when using 'me'
    if is_me:
        repos = [r for r in repos if r["owner"]["login"] == actual_username]

    # Filter forks, size
    if not include_forks:
        repos = [r for r in repos if not r.get("fork")]
    repos = [r for r in repos if r.get("size", 0) >= min_size]
    print("AZEAZEAZ",len(repos),min_size)

    # Exclusions
    if exclude:
        before_count = len(repos)
        repos = [r for r in repos if r["name"] not in exclude]
        if before_count > len(repos):
            log.info(f"Excluded {before_count - len(repos)} repos by blacklist")
    
    # Sort by recent activity and limit
    repos = sorted(repos, key=lambda r: r.get("pushed_at", ""), reverse=True)
    return repos[:limit]


def get_repo_info(owner: str, repo: str, token: str | None = None) -> dict:
    """Fetch repository metadata from GitHub API."""
    log = get_logger()
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    
    log.debug(f"Fetching repo info: {url}")
    resp = httpx.get(url, headers=build_headers(token), timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_languages(owner: str, repo: str, token: str | None = None) -> dict[str, int]:
    """Fetch language breakdown for a repository."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/languages"
    resp = httpx.get(url, headers=build_headers(token), timeout=30)
    resp.raise_for_status()
    
    # Convert bytes to percentages
    data = resp.json()
    total = sum(data.values()) or 1
    return {lang: round(bytes_count / total * 100) for lang, bytes_count in data.items()}


def get_commits(owner: str, repo: str, token: str | None = None, limit: int = 50) -> list[CommitInfo]:
    """Fetch recent commits from a repository."""
    log = get_logger()
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    
    resp = httpx.get(
        url,
        headers=build_headers(token),
        params={"per_page": limit},
        timeout=30,
    )
    resp.raise_for_status()
    
    commits = []
    for item in resp.json():
        commit_data = item["commit"]
        commits.append(CommitInfo(
            hash=item["sha"][:8],
            author=commit_data["author"]["name"],
            date=datetime.fromisoformat(commit_data["author"]["date"].replace("Z", "+00:00")),
            message=commit_data["message"].split("\n")[0],  # First line only
        ))
    
    log.debug(f"Fetched {len(commits)} commits")
    return commits


def get_contributors(owner: str, repo: str, token: str | None = None) -> list[dict]:
    """Fetch contributors for a repository.
    
    Returns list of {login, contributions, avatar_url} sorted by contributions desc.
    """
    log = get_logger()
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contributors"
    
    resp = httpx.get(
        url,
        headers=build_headers(token),
        params={"per_page": 100},
        timeout=30,
    )
    
    # Some repos may have no contributors (empty or errors)
    if resp.status_code == 204:
        return []
    resp.raise_for_status()
    
    contributors = [
        {"login": c["login"], "contributions": c["contributions"]}
        for c in resp.json()
    ]
    log.debug(f"Fetched {len(contributors)} contributors")
    return contributors


def fetch_repo_metadata(owner: str, repo: str, token: str | None = None) -> RepoMetadata:
    """Fetch complete repository metadata."""
    log = get_logger()
    log.info(f"Fetching metadata for {owner}/{repo}")
    
    info = get_repo_info(owner, repo, token)
    languages = get_languages(owner, repo, token)
    commits = get_commits(owner, repo, token)
    
    return RepoMetadata(
        name=info["name"],
        owner=info["owner"]["login"],
        description=info.get("description"),
        languages=languages,
        commits_count=len(commits),  # Approximation from fetched commits
        first_commit=commits[-1].date if commits else None,
        last_commit=commits[0].date if commits else None,
        stars=info.get("stargazers_count", 0),
        recent_commits=commits[:10],
    )


def download_tarball(owner: str, repo: str, token: str | None = None) -> Path:
    """Download repository as tarball and extract to temp directory.
    
    Returns path to extracted directory.
    """
    log = get_logger()
    url = f"{GITHUB_API}/repos/{owner}/{repo}/tarball"
    
    log.info(f"Downloading tarball for {owner}/{repo}")
    headers = build_headers(token)
    headers["Accept"] = "application/vnd.github.v3.raw"
    
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        content = resp.read()
    
    log.debug(f"Downloaded {len(content)} bytes")
    
    # Extract to temp directory
    temp_dir = Path(tempfile.mkdtemp(prefix="repo_rating_"))
    
    def safe_filter(member, path):
        """Skip symlinks and files that would extract outside destination."""
        # Skip symlinks entirely - they often cause issues and aren't needed for analysis
        if member.issym() or member.islnk():
            return None
        # Use data filter for everything else (security checks)
        return tarfile.data_filter(member, path)
    
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        tar.extractall(temp_dir, filter=safe_filter)
    
    # GitHub tarballs have a single root directory like "owner-repo-sha"
    subdirs = list(temp_dir.iterdir())
    if len(subdirs) == 1 and subdirs[0].is_dir():
        return subdirs[0]
    
    return temp_dir


def list_user_repos(username: str | None = None, token: str | None = None) -> list[dict]:
    """List repositories for a user.
    
    If username is None or "me", uses /user/repos (authenticated user, includes private).
    Otherwise uses /users/{username}/repos (public repos only).
    """
    log = get_logger()
    
    # Determine which endpoint to use
    if username is None or username.lower() == "me":
        if not token:
            raise ValueError("Token required to list your own repos. Use a username for public repos.")
        url_base = f"{GITHUB_API}/user/repos"
        log.info("Listing authenticated user's repos (including private)")
    else:
        url_base = f"{GITHUB_API}/users/{username}/repos"
        log.info(f"Listing repos for user: {username}")
    
    repos = []
    page = 1
    
    while True:
        resp = httpx.get(
            url_base,
            headers=build_headers(token),
            params={"per_page": 100, "page": page, "sort": "updated"},
            timeout=30,
        )
        
        # Handle rate limiting
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset_time = resp.headers.get("X-RateLimit-Reset", "unknown")
            raise RuntimeError(f"GitHub rate limit exceeded. Resets at {reset_time}. Use a GitHub token for higher limits.")
        
        resp.raise_for_status()
        
        batch = resp.json()
        if not batch:
            break
        
        repos.extend(batch)
        page += 1
        
        if len(batch) < 100:
            break
    
    log.info(f"Found {len(repos)} repositories")
    return repos


def fetch_full_repo_info(owner: str, repo: str, token: str | None = None) -> dict:
    """Fetch complete repo info including all data points.
    
    Returns dict with: info, languages, commits, contributors
    """
    log = get_logger()
    log.info(f"Fetching full info for {owner}/{repo}")
    
    info = get_repo_info(owner, repo, token)
    languages = get_languages(owner, repo, token)
    commits = get_commits(owner, repo, token, limit=20)
    contributors = get_contributors(owner, repo, token)
    
    return {
        "info": info,
        "languages": languages,
        "commits": commits,
        "contributors": contributors,
    }
