"""Configuration loading from TOML files."""

import os
import tomllib
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class FilteringConfig:
    small_threshold: int = 50000
    medium_threshold: int = 500000
    exclude_patterns: list[str] = field(default_factory=list)
    include_extensions: list[str] = field(default_factory=list)


@dataclass
class SelectionConfig:
    """LLM-based file selection config."""
    enabled: bool = False
    model: str = "qwen/qwen3-coder:free"


@dataclass
class LoggingConfig:
    console_level: str = "INFO"
    file_level: str = "DEBUG"


@dataclass
class Config:
    model: str = "anthropic/claude-sonnet-4-20250514"
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".repo_rating" / "cache")
    openrouter_api_key: str = ""
    mammouth_api_key: str = ""
    github_token: str = ""
    exclude_repos: list[str] = field(default_factory=list)  # Repo names to skip
    filtering: FilteringConfig = field(default_factory=FilteringConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)


def load_config(config_dir: Path | None = None) -> Config:
    """Load config from TOML files, merging generic and secret configs.
    
    Looks for config.toml and config_secret.toml in config_dir.
    Environment variables override file values:
        - OPENROUTER_API_KEY
        - GITHUB_TOKEN
    """
    if config_dir is None:
        config_dir = Path.cwd()
    
    config = Config()
    
    # Load generic config
    generic_path = config_dir / "config.toml"
    if generic_path.exists():
        with open(generic_path, "rb") as f:
            data = tomllib.load(f)
        _apply_config(config, data)
    
    # Load secret config
    secret_path = config_dir / "config_secret.toml"
    if secret_path.exists():
        with open(secret_path, "rb") as f:
            data = tomllib.load(f)
        _apply_config(config, data)
    
    # Environment overrides
    if env_key := os.environ.get("OPENROUTER_API_KEY"):
        config.openrouter_api_key = env_key
    if env_key := os.environ.get("MAMMOUTH_API_KEY"):
        config.mammouth_api_key = env_key
    if env_token := os.environ.get("GITHUB_TOKEN"):
        config.github_token = env_token
    
    return config


def _apply_config(config: Config, data: dict) -> None:
    """Apply parsed TOML data to config object."""
    if defaults := data.get("defaults"):
        if "model" in defaults:
            config.model = defaults["model"]
        if "cache_dir" in defaults:
            config.cache_dir = Path(defaults["cache_dir"]).expanduser()
        if "exclude_repos" in defaults:
            config.exclude_repos = defaults["exclude_repos"]
    
    if filtering := data.get("filtering"):
        if "small_threshold" in filtering:
            config.filtering.small_threshold = filtering["small_threshold"]
        if "medium_threshold" in filtering:
            config.filtering.medium_threshold = filtering["medium_threshold"]
        if "exclude_patterns" in filtering:
            config.filtering.exclude_patterns = filtering["exclude_patterns"]
        if "include_extensions" in filtering:
            config.filtering.include_extensions = filtering["include_extensions"]
    
    if logging := data.get("logging"):
        if "console_level" in logging:
            config.logging.console_level = logging["console_level"]
        if "file_level" in logging:
            config.logging.file_level = logging["file_level"]
    
    if selection := data.get("selection"):
        if "enabled" in selection:
            config.selection.enabled = selection["enabled"]
        if "model" in selection:
            config.selection.model = selection["model"]
    
    # Direct secret keys
    if "openrouter_api_key" in data:
        config.openrouter_api_key = data["openrouter_api_key"]
    if "mammouth_api_key" in data:
        config.mammouth_api_key = data["mammouth_api_key"]
    if "github_token" in data:
        config.github_token = data["github_token"]
