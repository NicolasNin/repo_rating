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
    
    # Load prompt template
    prompt_template = PROMPT_TEMPLATE_PATH.read_text()
    
    # Filter files first (needed for cache key)
    # Pass LLM selection config if enabled
    selection_model = config.selection.model if config.selection.enabled else None
    if selection_model:
        if selection_model.startswith("mammouth/"):
            selection_api_key = config.mammouth_api_key
        else:
            selection_api_key = config.openrouter_api_key
    else:
        selection_api_key = None
    filter_result = filter_repo_files(
        repo_path, 
        config.filtering,
        selection_model=selection_model,
        api_key=selection_api_key,
    )
    log.info(f"Filtered to {len(filter_result.files)} files ({filter_result.total_size} bytes)")
    
    # Skip if no files after filtering
    if not filter_result.files:
        log.warning("No analyzable files found after filtering - skipping LLM call")
        raise ValueError("No analyzable code files found in repository")
    
    # Build prompt
    prompt = _build_prompt(prompt_template, metadata, filter_result.files)
    
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
    cost = estimate_cost(config.model, estimated_tokens, output_tokens=500)
    
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
    
    # Format languages
    languages_text = ", ".join(f"{lang} ({pct}%)" for lang, pct in metadata.languages.items())
    
    return Template(template).safe_substitute(
        today=datetime.now().strftime("%Y-%m-%d"),
        repo_name=f"{metadata.owner}/{metadata.name}" if metadata.owner else metadata.name,
        first_commit=metadata.first_commit.strftime("%Y-%m-%d") if metadata.first_commit else "Unknown",
        last_commit=metadata.last_commit.strftime("%Y-%m-%d") if metadata.last_commit else "Unknown",
        languages=languages_text or "Unknown",
        files_content=files_text or "No files available",
        commits=commits_text,
    )
