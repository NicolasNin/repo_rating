# Portfolio Synthesis Prompt

You are creating a professional developer portfolio summary from analyzed GitHub repositories.

## Important Context

These repositories span multiple years. Pay attention to:
- **Timeline**: Older projects reflect earlier skills; recent projects show current expertise
- **Context**: Early projects may lack modern practices - this is normal, not a weakness
- **Recency**: Weight recent complex projects more heavily than old simple ones
- **Focus**: Design decisions and domain expertise matter more than SWE hygiene (tests, types)

## Repository Analyses

$analyses

## Task

Create a portfolio that synthesizes the above analyses. Structure your response as follows:

### 1. Professional Summary
A 2-3 sentence overview of the developer's experience and strengths.

### 2. Technical Skills

Group by category:
- **Languages**: List with proficiency indicators
- **Frameworks & Libraries**: Web frameworks, data tools, etc.
- **Platforms & Tools**: Cloud, databases, DevOps, etc.
- **Specialized Domains**: Blockchain, ML, game dev, etc.

### 3. Key Projects
Highlight 3-5 most impressive projects with:
- Project name and one-line description
- Key technical/design achievements
- Domain expertise demonstrated

### 4. Design & Problem-Solving Strengths
Based on the design_assessment and domain_assessment from the analyses:
- What architectural patterns does this developer favor?
- What hard problems have they solved?
- What domain expertise is evident?

### 5. Suggested Resume Bullets
5-8 concrete, achievement-focused bullet points.

### 6. Complete Skill Inventory (ATS Keywords)

List ALL technologies/skills with honest context levels:

```
**Strong (extensive use):**
- Python: 10+ projects, complex async and data pipelines

**Moderate (solid familiarity):**
- Django: 2 web applications

**Light (POC/experimental):**
- FastAPI: one small API project
```

Include everything that could match an ATS keyword. Be honest about depth.

### 7. Honest Assessment
- Strongest areas (focus on design/domain, not SWE hygiene)
- Areas for growth
- Overall experience level

Be specific. Avoid generic statements about "lacking tests" - focus on what they CAN do.
