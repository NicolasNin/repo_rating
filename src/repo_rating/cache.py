"""Caching layer for analysis results."""

import json
import hashlib
from pathlib import Path
from datetime import datetime

from .models import AnalysisResult
from .log import get_logger


def get_cache_key(
    repo_id: str,
    last_commit: str | None,
    prompt_hash: str,
    model: str,
) -> str:
    """Generate cache key from repo state and analysis config."""
    key_data = f"{repo_id}:{last_commit or 'unknown'}:{prompt_hash}:{model}"
    return hashlib.sha256(key_data.encode()).hexdigest()[:16]


def hash_prompt(prompt_template: str) -> str:
    """Hash the prompt template for cache key."""
    return hashlib.sha256(prompt_template.encode()).hexdigest()[:8]


def load_cached(cache_dir: Path, cache_key: str) -> AnalysisResult | None:
    """Load cached analysis result if it exists."""
    log = get_logger()
    cache_file = cache_dir / f"{cache_key}.json"
    
    if not cache_file.exists():
        return None
    
    try:
        data = json.loads(cache_file.read_text())
        log.info(f"Loaded cached result: {cache_key}")
        return AnalysisResult.model_validate(data)
    except Exception as e:
        log.warning(f"Failed to load cache: {e}")
        return None


def save_to_cache(cache_dir: Path, cache_key: str, result: AnalysisResult) -> None:
    """Save analysis result to cache."""
    log = get_logger()
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    cache_file = cache_dir / f"{cache_key}.json"
    cache_file.write_text(result.model_dump_json(indent=2))
    
    log.debug(f"Saved to cache: {cache_key}")
