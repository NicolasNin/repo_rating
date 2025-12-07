"""CLI interface for repo-rating."""

from pathlib import Path

import click

from .config import load_config
from .log import setup_logging, get_logger
from .analyzer import analyze_repo, RepoPromptIterator, analyze_prepared
from .github_client import list_user_repos


@click.group()
@click.option("--config-dir", type=click.Path(exists=True, path_type=Path), default=None,
              help="Directory containing config files")
@click.pass_context
def main(ctx: click.Context, config_dir: Path | None) -> None:
    """Analyze code repositories to extract developer skills."""
    ctx.ensure_object(dict)
    
    if config_dir is None:
        config_dir = Path.cwd()
    
    config = load_config(config_dir)
    ctx.obj["config"] = config
    
    # Setup logging
    log_dir = config_dir / "logs"
    setup_logging(log_dir, config.logging.console_level, config.logging.file_level)


@main.command()
@click.pass_context
def whoami(ctx: click.Context) -> None:
    """Show the GitHub user associated with configured token."""
    from .github_client import get_authenticated_user
    
    config = ctx.obj["config"]
    
    if not config.github_token:
        click.echo("No GitHub token configured.")
        return
    
    try:
        user = get_authenticated_user(config.github_token)
        click.echo(f"Logged in as: {user['login']}")
        click.echo(f"Name: {user.get('name', 'N/A')}")
        click.echo(f"Email: {user.get('email', 'N/A')}")
        click.echo(f"Public repos: {user.get('public_repos', 0)}")
        click.echo(f"Private repos: {user.get('total_private_repos', 0)}")
    except Exception as e:
        click.echo(f"Failed to authenticate: {e}")


@main.command()
@click.argument("source")
@click.option("--no-cache", is_flag=True, help="Skip cache and force re-analysis")
@click.option("--model", default=None, help="Override model from config")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Write JSON output to file")
@click.pass_context
def analyze(ctx: click.Context, source: str, no_cache: bool, model: str | None, output: Path | None) -> None:
    """Analyze a single repository.
    
    SOURCE can be:
      - GitHub URL: https://github.com/owner/repo
      - GitHub shorthand: owner/repo
      - Local path: /path/to/repo
    """
    log = get_logger()
    config = ctx.obj["config"]
    
    if model:
        config.model = model
    
    log.info(f"Analyzing: {source}")
    
    try:
        result = analyze_repo(source, config, use_cache=not no_cache)
        
        json_output = result.model_dump_json(indent=2)
        
        if output:
            output.write_text(json_output)
            log.info(f"Output written to: {output}")
        else:
            click.echo(json_output)
            
    except Exception as e:
        log.error(f"Analysis failed: {e}")
        raise click.ClickException(str(e))


@main.command("repo-info")
@click.argument("repo")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def repo_info(ctx: click.Context, repo: str, as_json: bool) -> None:
    """Show detailed info for a single repository.
    
    REPO can be:
      - Just repo name (assumes your username): myrepo
      - Owner/repo format: owner/repo  
      - Full URL: https://github.com/owner/repo
    """
    from .github_client import parse_repo_source, fetch_full_repo_info
    from .display import display_repo_info, repo_info_to_json
    import json
    
    log = get_logger()
    config = ctx.obj["config"]
    
    try:
        owner, repo_name = parse_repo_source(repo, config.github_token)
        data = fetch_full_repo_info(owner, repo_name, config.github_token)
        
        if as_json:
            click.echo(json.dumps(repo_info_to_json(data), indent=2))
        else:
            display_repo_info(data)
            
    except Exception as e:
        log.error(f"Failed to fetch repo info: {e}")
        raise click.ClickException(str(e))

@main.command("analyze-user")
@click.argument("username")
@click.option("--limit", default=10, help="Maximum number of repos to analyze")
@click.option("--no-cache", is_flag=True, help="Skip cache and force re-analysis")
@click.option("--model", default=None, help="Override model from config")
@click.option("--min-size", default=5, help="Minimum repo size in KB (skip empty repos)")
@click.option("--exclude", "-x", multiple=True, help="Repo names to exclude (can be repeated)")
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None,
              help="Write JSON outputs to directory")
@click.pass_context
def analyze_user(ctx: click.Context, username: str, limit: int, no_cache: bool, 
                 model: str | None, min_size: int, exclude: tuple[str, ...], output_dir: Path | None) -> None:
    """Analyze all repositories for a GitHub user.
    
    Use 'me' as USERNAME to analyze your own repos (including private).
    """
    
    log = get_logger()
    config = ctx.obj["config"]
    
    if model:
        config.model = model
    
    # Create iterator (fetches and filters repos)
    repo_iter = RepoPromptIterator(username, config, exclude=exclude, min_size=min_size, limit=limit)
    
    # Show repos that will be analyzed
    total_size = sum(r.get("size", 0) for r in repo_iter.repos)
    click.echo(click.style(f"\n📦 {len(repo_iter)} repositories to analyze ({total_size}KB total):\n", bold=True))
    for r in repo_iter.repos:
        click.echo(f"  • {r['name']} ({r.get('size', 0)}KB)")
    click.echo()
    
    # Setup output dir: results/{username}/assessments/
    if output_dir is None:
        output_dir = Path(f"results/{repo_iter.username}/assessments")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    failed = []
    
    # Iterate and analyze
    for i, prepared in enumerate(repo_iter, 1):
        click.echo(click.style(f"[{i}/{len(repo_iter)}]", fg="cyan") + f" {prepared.full_name}")
        
        try:
            result = analyze_prepared(prepared, config, use_cache=not no_cache)
            results.append(result)
            
            out_file = output_dir / f"{prepared.name}.json"
            out_file.write_text(result.model_dump_json(indent=2))
            
            # Brief summary
            tech = ", ".join(result.assessment.tech_stack[:3])
            click.echo(click.style(f"    ✓ ", fg="green") + f"{result.assessment.complexity} complexity | {tech}")
            
        except Exception as e:
            log.error(f"Failed: {e}")
            failed.append((prepared.full_name, str(e)))
            click.echo(click.style(f"    ✗ Failed: ", fg="red") + str(e)[:60])
    
    # Summary
    click.echo(f"\n{'='*60}")
    if len(results) == len(repo_iter):
        click.echo(click.style(f"✓ Completed: {len(results)}/{len(repo_iter)} repos analyzed", fg="green", bold=True))
    else:
        click.echo(click.style(f"Completed: {len(results)}/{len(repo_iter)} repos analyzed", fg="yellow", bold=True))
    
    if failed:
        click.echo(click.style(f"Failed ({len(failed)}):", fg="red"))
        for name, err in failed:
            click.echo(f"  - {name}: {err[:50]}")

    if not output_dir and results:
        click.echo(f"\nResults preview (use -o DIR to save all):")
        for result in results[:3]:
            click.echo(f"  {result.repo}: {result.assessment.summary[:60]}...")

@main.command("list-repos")
@click.argument("username")
@click.option("--include-forks", is_flag=True, help="Include forked repositories")
@click.option("--include-collabs", is_flag=True, help="Include repos you collaborate on (not owned by you)")
@click.option("-v", "--verbose", is_flag=True, help="Show extended repo info (topics, size, issues, created date)")
@click.pass_context
def list_repos(ctx: click.Context, username: str, include_forks: bool, include_collabs: bool, verbose: bool) -> None:
    """List repositories for a GitHub user (debug command).
    
    Use 'me' as USERNAME to list your own repos (including private).
    By default only shows repos you own, use --include-collabs for all accessible repos.
    """
    from .github_client import get_authenticated_user
    from .display import display_repo_list
    
    log = get_logger()
    config = ctx.obj["config"]
    
    # Pass None to use authenticated user endpoint
    is_me = username.lower() == "me"
    user_arg = None if is_me else username
    repos = list_user_repos(user_arg, config.github_token)
    
    # Filter to owned repos only (when listing own repos)
    if is_me and not include_collabs:
        user_info = get_authenticated_user(config.github_token)
        my_login = user_info["login"]
        owned_repos = [r for r in repos if r["owner"]["login"] == my_login]
        log.info(f"Filtered to {len(owned_repos)} owned repos (excluded {len(repos) - len(owned_repos)} collabs)")
        repos = owned_repos
    
    if not include_forks:
        repos = [r for r in repos if not r.get("fork")]
    
    repos = sorted(repos, key=lambda r: r.get("pushed_at", ""), reverse=True)
    
    header = "your owned repos" if is_me else username
    display_repo_list(repos, header, verbose)


@main.command()
@click.argument("results_dir", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None,
              help="Output markdown file (default: results_dir/report.md)")
@click.pass_context
def report(ctx: click.Context, results_dir: Path, output: Path | None) -> None:
    """Generate markdown report from analysis results.
    
    Reads JSON files from RESULTS_DIR and generates a human-readable markdown report.
    """
    import json
    from .report_generator import generate_report_markdown
    
    log = get_logger()
    
    # Collect all JSON results
    json_files = sorted(results_dir.glob("*.json"))
    if not json_files:
        click.echo(f"No JSON files found in {results_dir}")
        return
    
    results = []
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text())
            results.append(data)
        except Exception as e:
            log.warning(f"Could not read {json_file}: {e}")
    
    if not results:
        click.echo("No valid results to report")
        return
    
    # Generate and write report
    markdown = generate_report_markdown(results)
    
    if output is None:
        output = results_dir / "report.md"
    
    output.write_text(markdown)
    click.echo(f"Report generated: {output}")
    click.echo(f"  {len(results)} repositories included")


@main.command("generate-prompts")
@click.argument("username")
@click.option("--limit", default=10, help="Maximum number of repos to process")
@click.option("--min-size", default=5, help="Minimum repo size in KB")
@click.option("--exclude", "-x", multiple=True, help="Repo names to exclude (can be repeated)")
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None,
              help="Output directory (default: results/prompts)")
@click.pass_context
def generate_prompts(ctx: click.Context, username: str, limit: int, min_size: int,
                     exclude: tuple[str, ...], output_dir: Path | None) -> None:
    """Generate analysis prompts for manual use in chat interfaces.
    
    Creates .md files with full prompts ready to copy/paste into ChatGPT, Claude, etc.
    Use 'me' as USERNAME to generate prompts for your own repos.
    """
    
    config = ctx.obj["config"]
    
    # Create iterator (fetches and filters repos)
    repo_iter = RepoPromptIterator(username, config, exclude=exclude, min_size=min_size, limit=limit)
    
    # Setup output dir: results/{username}/prompts/
    if output_dir is None:
        output_dir = Path(f"results/{repo_iter.username}/prompts")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    click.echo(f"\n📝 Generating prompts for {len(repo_iter)} repos -> {output_dir}/\n")
    
    # Iterate and save prompts
    for i, prepared in enumerate(repo_iter, 1):
        click.echo(f"[{i}/{len(repo_iter)}] {prepared.full_name}...", nl=False)
        
        output_file = output_dir / f"{prepared.name}.md"
        output_file.write_text(prepared.prompt)
        
        tokens_est = len(prepared.prompt) // 3
        click.echo(f" ✓ ~{tokens_est:,} tokens")
    
    click.echo(f"\n✅ Prompts saved to {output_dir}/")


SYNTHESIZE_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "synthesize.md"


@main.command()
@click.argument("results_dir", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None,
              help="Output markdown file (default: results_dir/portfolio.md)")
@click.option("--model", default=None, help="Override model for synthesis")
@click.pass_context
def synthesize(ctx: click.Context, results_dir: Path, output: Path | None, model: str | None) -> None:
    """Synthesize portfolio summary from analysis results.
    
    Uses LLM to create a professional portfolio from all repository analyses.
    """
    import json
    from string import Template
    from .llm_client import call_llm
    
    config = ctx.obj["config"]
    log = get_logger()
    
    if model:
        config.model = model
    
    # Collect all JSON results
    json_files = sorted(results_dir.glob("*.json"))
    if not json_files:
        click.echo(f"No JSON files found in {results_dir}")
        return
    
    results = []
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text())
            results.append(data)
        except Exception as e:
            log.warning(f"Could not read {json_file}: {e}")
    
    if not results:
        click.echo("No valid results to synthesize")
        return
    
    # Build condensed analyses for prompt
    analyses_parts = []
    for r in results:
        repo = r.get("repo", "Unknown")
        assessment = r.get("assessment", {})
        metadata = r.get("metadata", {})
        
        # Extract date range
        first_commit = metadata.get("first_commit", "")[:10] if metadata.get("first_commit") else "?"
        last_commit = metadata.get("last_commit", "")[:10] if metadata.get("last_commit") else "?"
        
        part = f"""## {repo}
        **Dates:** {first_commit} → {last_commit}
        **Summary:** {assessment.get('summary', 'N/A')}
        **Complexity:** {assessment.get('complexity', 'N/A')}
        **Tech Stack:** {', '.join(assessment.get('tech_stack', []))}
        **Notable Skills:** {', '.join(assessment.get('notable_for_resume', []))}
        **Assessment:** {assessment.get('honest_assessment', 'N/A')}
        """
    analyses_parts.append(part)
    
    analyses = "\n".join(analyses_parts)
    
    # Load and fill prompt template
    if not SYNTHESIZE_PROMPT_PATH.exists():
        click.echo(f"Synthesis prompt not found: {SYNTHESIZE_PROMPT_PATH}")
        return
    
    template = Template(SYNTHESIZE_PROMPT_PATH.read_text())
    prompt = template.safe_substitute(analyses=analyses)
    
    # Estimate tokens
    est_tokens = len(prompt) // 3
    click.echo(f"Synthesizing {len(results)} repos (~{est_tokens:,} tokens)")
    click.echo(f"Using model: {config.model}")
    
    # Select API key based on model
    if config.model.startswith("mammouth/"):
        api_key = config.mammouth_api_key
    else:
        api_key = config.openrouter_api_key
    
    # Call LLM
    try:
        response = call_llm(prompt, config.model, api_key)
    except Exception as e:
        click.echo(f"LLM call failed: {e}")
        return
    
    # Write output
    if output is None:
        output = results_dir / "portfolio.md"
    
    # Add header
    from datetime import datetime
    header = f"""# Developer Portfolio

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
*Based on {len(results)} repositories analyzed with {config.model}*

---

"""
    output.write_text(header + response)
    click.echo(f"\nPortfolio generated: {output}")



if __name__ == "__main__":
    main()
