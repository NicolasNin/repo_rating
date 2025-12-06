"""Pydantic models for repo rating data structures."""

from datetime import datetime
from pydantic import BaseModel


class CommitInfo(BaseModel):
    """Single commit metadata."""
    hash: str
    author: str
    date: datetime
    message: str


class RepoMetadata(BaseModel):
    """Repository metadata from GitHub or local git."""
    name: str
    owner: str | None = None
    description: str | None = None
    languages: dict[str, int]  # language -> percentage
    commits_count: int
    first_commit: datetime | None = None
    last_commit: datetime | None = None
    stars: int = 0
    recent_commits: list[CommitInfo] = []


class CodeQuality(BaseModel):
    """Code quality assessment."""
    indicators: list[str]
    assessment: str


class DesignAssessment(BaseModel):
    """Design and architecture assessment."""
    patterns: list[str]
    abstractions: str
    tradeoffs: str


class DomainAssessment(BaseModel):
    """Domain expertise and problem-solving assessment."""
    expertise_demonstrated: list[str]
    problem_difficulty: str
    creativity: str


class Assessment(BaseModel):
    """LLM-generated assessment of a repository.
    
    Structured into separate categories for code quality, design, and domain expertise.
    """
    summary: str
    tech_stack: list[str]
    project_type: str
    complexity: str  # low, medium, high
    maturity: str
    temporal_context: str
    notable_for_resume: list[str]
    code_quality: CodeQuality
    design_assessment: DesignAssessment
    domain_assessment: DomainAssessment
    honest_assessment: str


class AnalysisResult(BaseModel):
    """Complete analysis result for a repository."""
    repo: str  # owner/name or local path
    analyzed_at: datetime
    model_used: str
    metadata: RepoMetadata
    assessment: Assessment


class FileContent(BaseModel):
    """A file with its content for analysis."""
    path: str
    content: str
    size: int
