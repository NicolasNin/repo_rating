"""Local repository handling using git."""

from pathlib import Path
from datetime import datetime

from git import Repo, InvalidGitRepositoryError

from .models import RepoMetadata, CommitInfo
from .log import get_logger


def is_git_repo(path: Path) -> bool:
    """Check if path is a git repository."""
    try:
        Repo(path)
        return True
    except InvalidGitRepositoryError:
        return False


def analyze_local_repo(path: Path) -> RepoMetadata:
    """Extract metadata from a local git repository or folder.
    
    Works with git repos (extracts commits) or plain folders.
    """
    log = get_logger()
    path = path.resolve()
    
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    
    log.info(f"Analyzing local path: {path}")
    
    # Get name from folder
    name = path.name
    
    # Try git metadata
    commits: list[CommitInfo] = []
    first_commit = None
    last_commit = None
    
    if is_git_repo(path):
        log.debug("Detected git repository")
        repo = Repo(path)
        
        try:
            for i, commit in enumerate(repo.iter_commits(max_count=50)):
                commits.append(CommitInfo(
                    hash=commit.hexsha[:8],
                    author=str(commit.author),
                    date=datetime.fromtimestamp(commit.committed_date),
                    message=commit.message.split("\n")[0],
                ))
                if i == 0:
                    last_commit = commits[0].date
            
            if commits:
                first_commit = commits[-1].date
        except Exception as e:
            log.warning(f"Could not read git history: {e}")
    else:
        log.debug("Not a git repository, using folder metadata")
    
    # Detect languages by file extension
    languages = _detect_languages(path)
    
    return RepoMetadata(
        name=name,
        owner=None,
        description=None,
        languages=languages,
        commits_count=len(commits),
        first_commit=first_commit,
        last_commit=last_commit,
        stars=0,
        recent_commits=commits[:10],
    )


def _detect_languages(path: Path) -> dict[str, int]:
    """Detect programming languages by file extension."""
    extension_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".jsx": "JavaScript",
        ".tsx": "TypeScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".c": "C",
        ".cpp": "C++",
        ".h": "C",
        ".hpp": "C++",
        ".rb": "Ruby",
        ".php": "PHP",
        ".swift": "Swift",
        ".kt": "Kotlin",
        ".scala": "Scala",
        ".sh": "Shell",
        ".bash": "Shell",
    }
    
    counts: dict[str, int] = {}
    
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if lang := extension_map.get(suffix):
            try:
                size = file_path.stat().st_size
                counts[lang] = counts.get(lang, 0) + size
            except OSError:
                continue
    
    # Convert to percentages
    total = sum(counts.values()) or 1
    return {lang: round(size / total * 100) for lang, size in counts.items()}
