"""File filtering based on size and patterns."""

import fnmatch
from pathlib import Path
from dataclasses import dataclass

from .models import FileContent
from .config import FilteringConfig
from .log import get_logger


@dataclass
class FilterResult:
    """Result of filtering a repository."""
    files: list[FileContent]
    total_size: int
    strategy: str  # "small", "medium", "large"
    excluded_count: int


def filter_repo_files(
    repo_path: Path,
    config: FilteringConfig,
    selection_model: str | None = None,
    api_key: str | None = None,
) -> FilterResult:
    """Filter repository files based on size heuristics and exclude patterns.
    
    Strategy:
        - small (<50KB): include everything except excluded patterns
        - medium (<500KB): filter to code files only
        - large (>500KB): use LLM selection if enabled, else prioritize key files
    
    Args:
        selection_model: If provided, use LLM selection for large repos
        api_key: Required if selection_model is provided
    """
    log = get_logger()
    
    # First pass: calculate total size and collect all files
    all_files: list[tuple[Path, int]] = []
    for path in repo_path.rglob("*"):
        if path.is_file() and not _is_excluded(path, repo_path, config.exclude_patterns):
            try:
                size = path.stat().st_size
                all_files.append((path, size))
            except OSError:
                continue
    
    total_size = sum(size for _, size in all_files)
    log.debug(f"Total size after basic exclusions: {total_size} bytes, {len(all_files)} files")
    
    # Determine strategy
    if total_size < config.small_threshold:
        strategy = "small"
        selected = all_files
    elif total_size < config.medium_threshold:
        strategy = "medium"
        selected = [(p, s) for p, s in all_files if _is_code_file(p, config.include_extensions)]
    else:
        strategy = "large"
        # Try LLM selection if enabled
        if selection_model and api_key:
            llm_selected = llm_select_files(repo_path, all_files, selection_model, api_key)
            if llm_selected is not None:
                strategy = "large+llm"
                selected = llm_selected
            else:
                selected = _select_priority_files(all_files, config)
        else:
            selected = _select_priority_files(all_files, config)
    
    log.info(f"Using '{strategy}' strategy: {len(selected)} files selected")
    
    # Log selected files in debug
    log.debug(f"Selected {len(selected)} files:")
    for p, s in selected:
        rel = p.relative_to(repo_path) if repo_path in p.parents or repo_path == p.parent else p.name
        log.debug(f"  + {rel} ({s} bytes)")
    
    # Log skipped files in debug
    if strategy in ("medium", "large"):
        selected_paths = {p for p, _ in selected}
        skipped = [(p, s) for p, s in all_files if p not in selected_paths]
        if skipped:
            log.debug(f"Skipped {len(skipped)} files:")
            for p, s in skipped[:200]:  # Show first 200
                rel = p.relative_to(repo_path) if repo_path in p.parents or repo_path == p.parent else p.name
                log.debug(f"  - {rel} ({s} bytes)")
            if len(skipped) > 200:
                log.debug(f"  ... and {len(skipped) - 200} more")
    
    # Read file contents
    files = []
    for path, size in selected:
        try:
            content = path.read_text(errors="replace")
            rel_path = str(path.relative_to(repo_path))
            files.append(FileContent(path=rel_path, content=content, size=size))
        except Exception as e:
            log.debug(f"Could not read {path}: {e}")
    
    return FilterResult(
        files=files,
        total_size=sum(f.size for f in files),
        strategy=strategy,
        excluded_count=len(all_files) - len(selected),
    )


def _is_excluded(path: Path, repo_root: Path, patterns: list[str]) -> bool:
    """Check if path matches any exclusion pattern."""
    rel_path = path.relative_to(repo_root)
    
    for pattern in patterns:
        # Check against full path and each part
        if fnmatch.fnmatch(str(rel_path), pattern):
            return True
        if fnmatch.fnmatch(path.name, pattern):
            return True
        for part in rel_path.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _is_code_file(path: Path, include_extensions: list[str]) -> bool:
    """Check if file is a code/text file worth analyzing."""
    suffix = path.suffix.lower()
    # Handle Dockerfile specially
    if path.name.lower() in ("dockerfile", "makefile", "rakefile"):
        return True
    return suffix in include_extensions or suffix.lstrip(".") in [e.lstrip(".") for e in include_extensions]


def _select_priority_files(
    all_files: list[tuple[Path, int]],
    config: FilteringConfig,
    max_size: int = 300_000,
) -> list[tuple[Path, int]]:
    """Select highest priority files for large repos, up to max_size bytes."""
    # Priority categories
    priority_patterns = [
        # Highest: README and main entry points
        ["readme*", "main.py", "app.py", "index.py", "index.js", "index.ts", "main.go", "main.rs"],
        # High: config and setup
        ["setup.py", "pyproject.toml", "package.json", "cargo.toml", "go.mod", "requirements.txt"],
        # Medium: source files in src/ or lib/
        ["src/*", "lib/*", "app/*"],
    ]
    
    selected = []
    current_size = 0
    used_paths = set()
    
    # First select by priority
    for patterns in priority_patterns:
        for path, size in all_files:
            if path in used_paths:
                continue
            name_lower = path.name.lower()
            rel_lower = str(path).lower()
            
            for pattern in patterns:
                if fnmatch.fnmatch(name_lower, pattern) or fnmatch.fnmatch(rel_lower, pattern):
                    if current_size + size <= max_size:
                        selected.append((path, size))
                        current_size += size
                        used_paths.add(path)
                    break
    
    # Fill remaining space with other code files
    for path, size in all_files:
        if path in used_paths:
            continue
        if not _is_code_file(path, config.include_extensions):
            continue
        if current_size + size <= max_size:
            selected.append((path, size))
            current_size += size
            used_paths.add(path)
    
    return selected


# Path to selection prompt template
SELECTION_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "file_selection.md"


def llm_select_files(
    repo_path: Path,
    all_files: list[tuple[Path, int]],
    model: str,
    api_key: str,
    max_size: int = 300_000,
) -> list[tuple[Path, int]] | None:
    """Use LLM to select important files from repository.
    
    Returns selected files or None if LLM fails (fallback to heuristics).
    """
    from string import Template
    from .llm_client import call_llm
    
    log = get_logger()
    
    if not SELECTION_PROMPT_PATH.exists():
        log.warning("Selection prompt not found, falling back to heuristics")
        return None
    
    # Find README
    readme_content = "No README found."
    for path, _ in all_files:
        if path.name.lower().startswith("readme"):
            try:
                readme_content = path.read_text(errors="replace")[:5000]  # Limit README size
                break
            except Exception:
                pass
    
    # Build file list with IDs
    file_list_lines = []
    id_to_file: dict[int, tuple[Path, int]] = {}
    for i, (path, size) in enumerate(all_files, start=1):
        rel_path = path.relative_to(repo_path)
        file_list_lines.append(f"{i}: {rel_path} ({size} bytes)")
        id_to_file[i] = (path, size)
    
    file_list = "\n".join(file_list_lines)
    
    # Build prompt
    template = Template(SELECTION_PROMPT_PATH.read_text())
    prompt = template.safe_substitute(
        readme_content=readme_content,
        file_list=file_list,
    )
    
    log.info(f"LLM file selection: {len(all_files)} files, prompt ~{len(prompt)//3:,} tokens")
    
    try:
        response = call_llm(prompt, model, api_key)
    except Exception as e:
        log.warning(f"LLM selection failed: {e}, falling back to heuristics")
        return None
    
    # Parse response - expect one ID per line
    selected_ids: set[int] = set()
    for line in response.strip().split("\n"):
        line = line.strip()
        if line.isdigit():
            selected_ids.add(int(line))
    
    if not selected_ids:
        log.warning("LLM returned no valid file IDs, falling back to heuristics")
        return None
    
    # Convert IDs back to files, apply size budget
    selected: list[tuple[Path, int]] = []
    current_size = 0
    for file_id in sorted(selected_ids):
        if file_id not in id_to_file:
            continue
        path, size = id_to_file[file_id]
        if current_size + size <= max_size:
            selected.append((path, size))
            current_size += size
    
    log.info(f"LLM selected {len(selected)} files ({current_size} bytes)")
    return selected
