"""Report generator - creates markdown reports from analysis results."""

from datetime import datetime


def generate_report_markdown(results: list[dict]) -> str:
    """Generate markdown report from analysis results.
    
    Args:
        results: List of analysis result dicts (loaded from JSON)
        
    Returns:
        Complete markdown report as string
    """
    lines = [
        "# Repository Analysis Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Repositories analyzed: {len(results)}",
        "",
        "---",
        "",
    ]
    
    for r in results:
        repo = r.get("repo", "Unknown")
        model = r.get("model_used", "Unknown")
        assessment = r.get("assessment", {})
        metadata = r.get("metadata", {})
        
        # Header
        lines.append(f"## {repo}")
        lines.append("")
        
        # Quick info
        langs = metadata.get("languages", {})
        lang_str = ", ".join(f"{k} ({v}%)" for k, v in list(langs.items())[:3]) if langs else "Unknown"
        lines.append(f"**Languages:** {lang_str}")
        lines.append(f"**Model:** `{model}`")
        lines.append(f"**Complexity:** {assessment.get('complexity', 'Unknown')}")
        lines.append(f"**Type:** {assessment.get('project_type', 'Unknown')}")
        lines.append("")
        
        # Summary
        lines.append("### Summary")
        lines.append(assessment.get("summary", "No summary available."))
        lines.append("")
        
        # Tech stack
        tech = assessment.get("tech_stack", [])
        if tech:
            lines.append("### Tech Stack")
            lines.append(", ".join(tech))
            lines.append("")
        
        # Notable for resume
        notable = assessment.get("notable_for_resume", [])
        if notable:
            lines.append("### Notable Skills")
            for skill in notable:
                lines.append(f"- {skill}")
            lines.append("")
        
        # Honest assessment
        honest = assessment.get("honest_assessment", "")
        if honest:
            lines.append("### Assessment")
            lines.append(f"> {honest}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    return "\n".join(lines)
