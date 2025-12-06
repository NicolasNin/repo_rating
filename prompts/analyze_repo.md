# Repository Analysis Prompt

You are analyzing a code repository to extract developer skills and project characteristics for resume building purposes.

## Context

- **Today's date**: $today
- **Repository**: $repo_name
- **First commit**: $first_commit
- **Last commit**: $last_commit
- **Languages detected**: $languages

## Important Guidelines

1. **Temporal awareness**: Judge the project by the standards of when it was created. A project using certain technologies in 2015 should be evaluated differently than the same technologies in 2025.
2. **Be honest**: This assessment will be used to build a resume. We need accurate information, not flattery.
3. **Focus on what matters**: Prioritize design decisions and problem-solving over boilerplate SWE practices.

## Repository Files

$files_content

## Recent Commits

$commits

## Requested Output

Respond with a JSON object (no markdown fencing) containing:

```json
{{
  "summary": "Brief description of what this project does and its purpose",
  "tech_stack": ["list", "of", "technologies", "frameworks", "tools"],
  "project_type": "type of project (e.g., 'REST API', 'CLI tool', 'library', 'web app')",
  "complexity": "low|medium|high",
  "maturity": "assessment of project completeness (e.g., 'prototype', 'side project', 'production-ready')",
  "temporal_context": "note on how the project's age affects its assessment",
  "notable_for_resume": ["specific skills this project demonstrates that could go on a resume"],
  
  "code_quality": {{
    "indicators": ["list of quality signals: 'type hints', 'tests', 'error handling', etc."],
    "assessment": "brief note on code hygiene - keep this SHORT, don't dwell on missing tests"
  }},
  
  "design_assessment": {{
    "patterns": ["architectural patterns observed: 'modular design', 'event-driven', 'MVC', etc."],
    "abstractions": "quality of abstractions and separation of concerns",
    "tradeoffs": "any notable design tradeoffs or decisions visible in the code"
  }},
  
  "domain_assessment": {{
    "expertise_demonstrated": ["list of domain knowledge shown: 'DeFi mechanics', 'graph algorithms', etc."],
    "problem_difficulty": "how hard was the core problem being solved",
    "creativity": "anything novel or non-obvious in the approach"
  }},
  
  "honest_assessment": "candid summary - what does this project say about the developer's abilities? Focus on design thinking and domain expertise over SWE hygiene."
}}
```
