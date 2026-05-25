"""Pydantic schemas for the persistent master profile."""

from typing import Optional
from pydantic import BaseModel, Field


class Experience(BaseModel):
    company: str
    title: str
    start_date: Optional[str] = None        # e.g. "2021-03"
    end_date: Optional[str] = None          # None = current role
    description: str = ""
    achievements: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str
    field: Optional[str] = None
    graduation_year: Optional[str] = None


class MasterProfile(BaseModel):
    created_at: str
    updated_at: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)   # standalone, not tied to a role
    source_count: int = 0                                    # number of resumes merged in

    def to_text(self) -> str:
        """
        Render the profile as plain text for use as LLM context.
        This is what gets passed to AnswerGenerator and JobFitAnalyzer.
        """
        lines: list[str] = []

        if self.name:
            lines.append(f"Name: {self.name}")
        if self.email:
            lines.append(f"Email: {self.email}")
        if self.location:
            lines.append(f"Location: {self.location}")
        if self.summary:
            lines.append(f"\nSummary:\n{self.summary}")

        if self.skills:
            lines.append(f"\nSkills: {', '.join(self.skills)}")

        if self.experiences:
            lines.append("\nExperience:")
            for exp in self.experiences:
                period = f"{exp.start_date or '?'} – {exp.end_date or 'Present'}"
                lines.append(f"  {exp.title} at {exp.company} ({period})")
                if exp.description:
                    lines.append(f"    {exp.description}")
                for ach in exp.achievements:
                    lines.append(f"    • {ach}")
                if exp.technologies:
                    lines.append(f"    Tech: {', '.join(exp.technologies)}")

        if self.education:
            lines.append("\nEducation:")
            for edu in self.education:
                lines.append(
                    f"  {edu.degree}{' in ' + edu.field if edu.field else ''} — "
                    f"{edu.institution}"
                    f"{' (' + edu.graduation_year + ')' if edu.graduation_year else ''}"
                )

        if self.achievements:
            lines.append("\nNotable Achievements:")
            for ach in self.achievements:
                lines.append(f"  • {ach}")

        return "\n".join(lines)
