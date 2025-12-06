"""Display helpers for pretty-printing repo info."""

import click

from .models import CommitInfo


def display_repo_info(data: dict) -> None:
    """Pretty print full repo info to terminal.
    
    Args:
        data: Dict from fetch_full_repo_info with keys: info, languages, commits, contributors
    """
    info = data["info"]
    languages = data["languages"]
    commits = data["commits"]
    contributors = data["contributors"]
    
    visibility = "private" if info.get("private") else "public"
    click.echo(f"\n{'='*60}")
    click.echo(f"  {info['full_name']} ({visibility})")
    click.echo(f"{'='*60}")
    
    if info.get("description"):
        click.echo(f"\n  {info['description']}")
    
    created = info.get("created_at", "")[:10] if info.get("created_at") else "unknown"
    pushed = info.get("pushed_at", "")[:10] if info.get("pushed_at") else "unknown"
    click.echo(f"\n  Created: {created}  |  Last push: {pushed}")
    click.echo(f"  Size: {info.get('size', 0)}KB  |  Stars: {info.get('stargazers_count', 0)}  |  Forks: {info.get('forks_count', 0)}")
    
    license_name = info.get("license", {}).get("spdx_id") if info.get("license") else "none"
    click.echo(f"  License: {license_name}  |  Open issues: {info.get('open_issues_count', 0)}")
    
    if info.get("topics"):
        click.echo(f"\n  Topics: {', '.join(info['topics'])}")
    
    # Languages
    if languages:
        click.echo(f"\n  Languages:")
        for lang, pct in sorted(languages.items(), key=lambda x: -x[1]):
            bar = "█" * (pct // 5) if pct >= 5 else "▏"
            click.echo(f"    {lang:15} {bar} {pct}%")
    
    # Contributors
    if contributors:
        total_contribs = sum(c["contributions"] for c in contributors)
        click.echo(f"\n  Contributors ({len(contributors)} total, {total_contribs} commits):")
        for c in contributors[:5]:
            pct = (c["contributions"] / total_contribs * 100) if total_contribs else 0
            click.echo(f"    {c['login']:20} {c['contributions']:4} commits ({pct:.0f}%)")
        if len(contributors) > 5:
            click.echo(f"    ... and {len(contributors) - 5} more")
    
    # Recent commits
    if commits:
        click.echo(f"\n  Recent commits:")
        for c in commits[:5]:
            if isinstance(c, CommitInfo):
                date_str = c.date.strftime("%Y-%m-%d")
                msg = c.message[:50] + "..." if len(c.message) > 50 else c.message
                click.echo(f"    {c.hash} {date_str} {msg}")
            else:
                # Dict format
                date_str = c.get("date", "")[:10]
                msg = c.get("message", "")[:50]
                click.echo(f"    {c.get('hash', '')} {date_str} {msg}")
    
    click.echo()


def repo_info_to_json(data: dict) -> dict:
    """Convert full repo info to JSON-serializable dict."""
    info = data["info"]
    commits = data["commits"]
    
    return {
        "full_name": info["full_name"],
        "description": info.get("description"),
        "private": info.get("private"),
        "created_at": info.get("created_at"),
        "pushed_at": info.get("pushed_at"),
        "size_kb": info.get("size"),
        "stars": info.get("stargazers_count"),
        "forks": info.get("forks_count"),
        "open_issues": info.get("open_issues_count"),
        "default_branch": info.get("default_branch"),
        "license": info.get("license", {}).get("spdx_id") if info.get("license") else None,
        "topics": info.get("topics", []),
        "languages": data["languages"],
        "contributors": data["contributors"],
        "recent_commits": [
            {"hash": c.hash, "author": c.author, "date": c.date.isoformat(), "message": c.message}
            if isinstance(c, CommitInfo) else c
            for c in commits
        ],
    }


def display_repo_list(repos: list[dict], header: str, verbose: bool = False) -> None:
    """Display a list of repositories.
    
    Args:
        repos: List of repo dicts from GitHub API
        header: Header text (e.g. "your owned repos" or username)
        verbose: Show extended info (created date, size, issues, license, topics)
    """
    click.echo(f"\nFound {len(repos)} repositories ({header}):\n")
    
    for repo in repos:
        visibility = "private" if repo.get("private") else "public"
        fork_marker = " [fork]" if repo.get("fork") else ""
        stars = repo.get("stargazers_count", 0)
        language = repo.get("language") or "unknown"
        pushed = repo.get("pushed_at", "")[:10] if repo.get("pushed_at") else "never"
        
        click.echo(f"  {repo['full_name']}{fork_marker}")
        click.echo(f"    {visibility} | {language} | ★{stars} | last push: {pushed}")
        
        if verbose:
            created = repo.get("created_at", "")[:10] if repo.get("created_at") else "unknown"
            size_kb = repo.get("size", 0)
            issues = repo.get("open_issues_count", 0)
            topics = repo.get("topics", [])
            license_info = repo.get("license")
            license_name = license_info["spdx_id"] if license_info else "none"
            
            click.echo(f"    created: {created} | size: {size_kb}KB | issues: {issues} | license: {license_name}")
            if topics:
                click.echo(f"    topics: {', '.join(topics)}")
        
        if repo.get("description"):
            desc = repo["description"][:80] + "..." if len(repo.get("description", "")) > 80 else repo["description"]
            click.echo(f"    {desc}")
        click.echo()
