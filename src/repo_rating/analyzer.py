"""Main analyzer - orchestrates the analysis pipeline."""

import shutil
from pathlib import Path
from datetime import datetime

from .config import Config
from .models import RepoMetadata, Assessment, AnalysisResult, FileContent
from .github_client import parse_github_url, fetch_repo_metadata, download_tarball
from .local_repo import analyze_local_repo
from .file_filter import filter_repo_files
from .llm_client import call_llm, parse_json_response
from .cache import get_cache_key, hash_prompt, load_cached, save_to_cache
from .log import get_logger


PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "analyze_repo.md"


def get_selection_api_key(config: Config) -> tuple[str | None, str | None]:
    """Get selection model and API key from config.
    
    Returns:
        (selection_model, api_key) tuple. Both None if selection disabled.
    """
    if not config.selection.enabled:
        return None, None
    
    model = config.selection.model
    if model.startswith("mammouth/"):
        return model, config.mammouth_api_key
    else:
        return model, config.openrouter_api_key


def prepare_repo_prompt(
    repo_path: Path,
    metadata: RepoMetadata,
    config: Config,
) -> str:
    """Build analysis prompt for a repo.
    
    Handles file filtering (including LLM selection if enabled) and prompt building.
    
    Args:
        repo_path: Path to extracted repo
        metadata: Repository metadata
        config: Configuration object
        
    Returns:
        Complete prompt string ready for LLM
        
    Raises:
        ValueError: If no analyzable files found after filtering
    """
    log = get_logger()
    
    # Load prompt template
    prompt_template = PROMPT_TEMPLATE_PATH.read_text()
    
    # Get selection model/key
    selection_model, selection_api_key = get_selection_api_key(config)
    
    # Filter files
    filter_result = filter_repo_files(
        repo_path,
        config.filtering,
        selection_model=selection_model,
        api_key=selection_api_key,
    )
    log.info(f"Filtered to {len(filter_result.files)} files ({filter_result.total_size} bytes)")
    
    if not filter_result.files:
        raise ValueError("No analyzable code files found in repository")
    
    # Build and return prompt
    return _build_prompt(prompt_template, metadata, filter_result.files)


from dataclasses import dataclass
from typing import Iterator


@dataclass
class PreparedRepo:
    """A repo prepared for analysis."""
    name: str
    owner: str
    full_name: str
    metadata: RepoMetadata
    prompt: str
    repo_path: Path  # Temp path, caller should clean up

class RepoPromptIterator:
    """Iterator over user repos that exposes the repos list.
    
    Allows upfront display of repos before iteration.
    """
    
    def __init__(
        self,
        username: str,
        config: Config,
        *,
        exclude: tuple[str, ...] = (),
        min_size: int = 5,
        limit: int = 10,
    ):
        from .github_client import fetch_user_repos, resolve_username
        
        # Resolve 'me' to actual username
        self.username, _ = resolve_username(username, config.github_token)
        
        # Build exclusion set and fetch repos
        exclude_set = set(exclude)
        exclude_set.update(config.exclude_repos)
        self.repos = fetch_user_repos(username, config.github_token, exclude=exclude_set, min_size=min_size, limit=limit)
        self.config = config
    
    def __len__(self) -> int:
        return len(self.repos)
    
    def __iter__(self) -> Iterator[PreparedRepo]:
        from .github_client import fetch_repo_metadata, download_tarball
        
        log = get_logger()
    
        for repo in self.repos:
            repo_name = repo["name"]
            owner = repo["owner"]["login"]
            full_name = f"{owner}/{repo_name}"
            
            try:
                # Fetch metadata
                metadata = fetch_repo_metadata(owner, repo_name, self.config.github_token)
                
                # Download repo
                repo_path = download_tarball(owner, repo_name, self.config.github_token)
                
                # Build prompt
                prompt = prepare_repo_prompt(repo_path, metadata, self.config)
                
                yield PreparedRepo(
                    name=repo_name,
                    owner=owner,
                    full_name=full_name,
                    metadata=metadata,
                    prompt=prompt,
                    repo_path=repo_path,
                )
                
            except Exception as e:
                log.warning(f"Failed to prepare {full_name}: {e}")
                continue


def analyze_prepared(
    prepared: PreparedRepo,
    config: Config,
    use_cache: bool = True,
) -> AnalysisResult:
    """Analyze a prepared repo (prompt already built).
    
    This is the main entry point when using iter_repo_prompts.
    Handles caching, LLM calls, and result building.
    """
    log = get_logger()
    
    # Hash prompt for cache key
    prompt_hash = hash_prompt(prepared.prompt)
    last_commit_hash = prepared.metadata.recent_commits[0].hash if prepared.metadata.recent_commits else None
    cache_key = get_cache_key(prepared.full_name, last_commit_hash, prompt_hash, config.model)
    
    # Check cache
    if use_cache:
        cached = load_cached(config.cache_dir, cache_key)
        if cached:
            return cached
    
    # Estimate tokens and cost
    estimated_tokens = len(prepared.prompt) // 3
    from .llm_client import estimate_cost
    cost = estimate_cost(config.model, estimated_tokens, output_tokens=800)
    
    if cost is not None:
        log.info(f"Prompt: {len(prepared.prompt)} chars (~{estimated_tokens:,} tokens, est. ${cost:.4f})")
    else:
        log.info(f"Prompt: {len(prepared.prompt)} chars (~{estimated_tokens:,} tokens)")
    
    # Log prompt for debugging
    from .log import log_prompt
    log_prompt(prepared.full_name, config.model, prepared.prompt)
    
    # Select API key based on provider
    if config.model.startswith("mammouth/"):
        api_key = config.mammouth_api_key
    else:
        api_key = config.openrouter_api_key
    
    # Call LLM
    response = call_llm(prepared.prompt, config.model, api_key)
    assessment_data = parse_json_response(response)
    
    # Build result
    assessment = Assessment.model_validate(assessment_data)
    result = AnalysisResult(
        repo=prepared.full_name,
        analyzed_at=datetime.now(),
        model_used=config.model,
        metadata=prepared.metadata,
        assessment=assessment,
    )
    
    # Cache result
    save_to_cache(config.cache_dir, cache_key, result)
    
    return result


def analyze_repo(
    source: str,
    config: Config,
    use_cache: bool = True,
) -> AnalysisResult:
    """Analyze a repository from GitHub URL, owner/repo, repo name, or local path.
    
    Args:
        source: One of:
            - Just repo name (uses authenticated user): myrepo
            - Owner/repo format: owner/repo
            - Full URL: https://github.com/owner/repo
            - Local path: /path/to/repo
        config: Configuration object
        use_cache: Whether to use cached results
    
    Returns:
        AnalysisResult with metadata and LLM assessment
    """
    from .github_client import parse_repo_source
    
    log = get_logger()
    
    # Check if it's a local path first
    if Path(source).exists():
        repo_path = Path(source).resolve()
        repo_id = str(repo_path)
        metadata = analyze_local_repo(repo_path)
        cleanup_path = None
    else:
        # GitHub source - parse and fetch
        owner, repo = parse_repo_source(source, config.github_token)
        repo_id = f"{owner}/{repo}"
        log.info(f"Fetching {repo_id}")
        metadata = fetch_repo_metadata(owner, repo, config.github_token)
        repo_path = download_tarball(owner, repo, config.github_token)
        cleanup_path = repo_path.parent
    
    try:
        return _run_analysis(repo_id, repo_path, metadata, config, use_cache)
    finally:
        if cleanup_path and cleanup_path.exists():
            log.debug(f"Cleaning up temp dir: {cleanup_path}")
            shutil.rmtree(cleanup_path, ignore_errors=True)


def _run_analysis(
    repo_id: str,
    repo_path: Path,
    metadata: RepoMetadata,
    config: Config,
    use_cache: bool,
) -> AnalysisResult:
    """Run the analysis pipeline."""
    log = get_logger()
    
    # Build prompt (handles filtering, selection, template)
    prompt = prepare_repo_prompt(repo_path, metadata, config)
    
    # Hash the ACTUAL prompt (includes filtered files) for cache key
    prompt_hash = hash_prompt(prompt)
    last_commit_hash = metadata.recent_commits[0].hash if metadata.recent_commits else None
    cache_key = get_cache_key(repo_id, last_commit_hash, prompt_hash, config.model)
    
    # Check cache (after building prompt so filter changes invalidate cache)
    if use_cache:
        cached = load_cached(config.cache_dir, cache_key)
        if cached:
            return cached
    
    # Estimate tokens and cost (~3 chars = 1 token for code)
    estimated_tokens = len(prompt) // 3
    from .llm_client import estimate_cost
    cost = estimate_cost(config.model, estimated_tokens, output_tokens=800)
    
    if cost is not None:
        log.info(f"Prompt: {len(prompt)} chars (~{estimated_tokens:,} tokens, est. ${cost:.4f})")
    else:
        log.info(f"Prompt: {len(prompt)} chars (~{estimated_tokens:,} tokens)")
    
    # Log prompt for debugging (goes to prompts.md)
    from .log import log_prompt
    log_prompt(repo_id, config.model, prompt)
    
    # Select API key based on provider
    if config.model.startswith("mammouth/"):
        api_key = config.mammouth_api_key
    else:
        api_key = config.openrouter_api_key
    
    # Call LLM
    response = call_llm(prompt, config.model, api_key)
    assessment_data = parse_json_response(response)
    
    # Build result
    assessment = Assessment.model_validate(assessment_data)
    result = AnalysisResult(
        repo=repo_id,
        analyzed_at=datetime.now(),
        model_used=config.model,
        metadata=metadata,
        assessment=assessment,
    )
    
    # Cache result
    save_to_cache(config.cache_dir, cache_key, result)
    
    return result


def _build_prompt(template: str, metadata: RepoMetadata, files: list[FileContent]) -> str:
    """Build the analysis prompt from template and data.
    
    Uses string.Template ($var syntax) to avoid conflicts with braces in code.
    """
    from string import Template
    
    # Format commits
    commits_text = "\n".join(
        f"- {c.hash} ({c.date.strftime('%Y-%m-%d')}): {c.message}"
        for c in metadata.recent_commits[:10]
    ) or "No commit history available"
    
    # Format files
    files_text = ""
    for f in files:
        files_text += f"\n### {f.path}\n```\n{f.content}\n```\n"
    
    # Format languages (sorted by percentage for deterministic output)
    languages_text = ", ".join(
        f"{lang} ({pct}%)" 
        for lang, pct in sorted(metadata.languages.items(), key=lambda x: (-x[1], x[0]))
    )
    
    return Template(template).safe_substitute(
        today=datetime.now().strftime("%Y-%m-%d"),
        repo_name=f"{metadata.owner}/{metadata.name}" if metadata.owner else metadata.name,
        first_commit=metadata.first_commit.strftime("%Y-%m-%d") if metadata.first_commit else "Unknown",
        last_commit=metadata.last_commit.strftime("%Y-%m-%d") if metadata.last_commit else "Unknown",
        languages=languages_text or "Unknown",
        files_content=files_text or "No files available",
        commits=commits_text,
    )
