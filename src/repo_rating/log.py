"""Logging setup for repo_rating."""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logging(log_dir: Path | None = None, console_level: str = "INFO", file_level: str = "DEBUG") -> logging.Logger:
    """Configure logging with console and optional file output.
    
    Args:
        log_dir: Directory for log files. If None, file logging is disabled.
        console_level: Log level for console output.
        file_level: Log level for file output.
    
    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("repo_rating")
    logger.setLevel(logging.DEBUG)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(getattr(logging, console_level.upper()))
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console)
    
    # File handler
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "repo_rating.log")
        file_handler.setLevel(getattr(logging, file_level.upper()))
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)
    
    # Setup prompt logger (separate file for verbose prompt content)
    prompt_logger = logging.getLogger("repo_rating.prompts")
    prompt_logger.handlers.clear()
    prompt_logger.setLevel(logging.DEBUG)
    prompt_logger.propagate = False  # Don't bubble up to main logger
    
    if log_dir:
        prompt_handler = logging.FileHandler(log_dir / "prompts.md")
        prompt_handler.setLevel(logging.DEBUG)
        prompt_handler.setFormatter(
            logging.Formatter("%(message)s\n")
        )
        prompt_logger.addHandler(prompt_handler)
    
    return logger


def get_logger() -> logging.Logger:
    """Get the repo_rating logger."""
    return logging.getLogger("repo_rating")


def get_prompt_logger() -> logging.Logger:
    """Get the prompt logger for verbose prompt content."""
    return logging.getLogger("repo_rating.prompts")


def log_prompt(repo_id: str, model: str, prompt: str, response: str | None = None) -> None:
    """Log a prompt and optional response to the prompts log file.
    
    Args:
        repo_id: Repository identifier
        model: Model name being called
        prompt: The full prompt text
        response: Optional response from the model
    """
    plog = get_prompt_logger()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"""## {repo_id} | {model} | {timestamp}

<details>
<summary>Prompt ({len(prompt)} chars)</summary>

```
{prompt}
```

</details>
"""
    
    if response:
        log_entry += f"""
<details>
<summary>Response ({len(response)} chars)</summary>

```json
{response}
```

</details>
"""
    
    plog.debug(log_entry)
