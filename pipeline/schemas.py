"""Pydantic models: the contract between scrapers, the LLM and the database."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from pipeline.skills import normalize_skills


class RawJob(BaseModel):
    """A job listing exactly as a scraper found it (Extract step)."""

    source: str
    external_id: str
    title: str
    company: str = "Unknown"
    location_raw: str = ""
    description: str = ""
    salary_raw: str = ""
    url: str = ""
    posted_at: Optional[datetime] = None


Seniority = Literal["intern", "junior", "mid", "senior", "lead", "unknown"]
WorkMode = Literal["onsite", "hybrid", "remote", "unknown"]


class JobExtraction(BaseModel):
    """Structured fields the LLM must return for every job (Transform step)."""

    role_category: str = Field(
        description="One of: ML Engineer, Data Scientist, GenAI/LLM Engineer, "
        "Data Engineer, MLOps Engineer, AI Research, Data Analyst, Other"
    )
    seniority: Seniority = "unknown"
    skills: list[str] = Field(default_factory=list, description="Technical skills and tools only")
    salary_min_lpa: Optional[float] = Field(None, ge=0, le=500, description="Annual, in lakhs INR")
    salary_max_lpa: Optional[float] = Field(None, ge=0, le=500, description="Annual, in lakhs INR")
    city: Optional[str] = Field(None, description="Indian city name, or null if remote/unclear")
    work_mode: WorkMode = "unknown"
    min_experience_years: Optional[float] = Field(None, ge=0, le=40)

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, v: list[str]) -> list[str]:
        return normalize_skills(v)

    @field_validator("city")
    @classmethod
    def _clean_city(cls, v: Optional[str]) -> Optional[str]:
        if not v or v.strip().lower() in {"remote", "india", "unknown", "n/a", "null"}:
            return None
        aliases = {"bangalore": "Bengaluru", "gurgaon": "Gurugram", "bombay": "Mumbai"}
        v = v.strip().split(",")[0].strip()
        return aliases.get(v.lower(), v.title())

    def model_post_init(self, __context) -> None:
        # If the model swapped min and max, fix it instead of failing.
        if (
            self.salary_min_lpa is not None
            and self.salary_max_lpa is not None
            and self.salary_min_lpa > self.salary_max_lpa
        ):
            self.salary_min_lpa, self.salary_max_lpa = self.salary_max_lpa, self.salary_min_lpa
