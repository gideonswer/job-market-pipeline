"""Database layer (Load step). Works on PostgreSQL and SQLite via SQLAlchemy 2.0."""
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from pipeline import config
from pipeline.schemas import JobExtraction, RawJob


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # --- raw fields from the scraper ---
    source: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)  # catches cross-source duplicates
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    location_raw: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    salary_raw: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # --- fields filled by the LLM ---
    role_category: Mapped[Optional[str]] = mapped_column(String(60), index=True)
    seniority: Mapped[Optional[str]] = mapped_column(String(20))
    salary_min_lpa: Mapped[Optional[float]] = mapped_column(Float)
    salary_max_lpa: Mapped[Optional[float]] = mapped_column(Float)
    city: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    work_mode: Mapped[Optional[str]] = mapped_column(String(20))
    min_experience_years: Mapped[Optional[float]] = mapped_column(Float)
    extraction_method: Mapped[Optional[str]] = mapped_column(String(20))  # groq | gemini | heuristic
    extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    extraction_error: Mapped[Optional[str]] = mapped_column(Text)

    skills: Mapped[list["JobSkill"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobSkill(Base):
    """One row per (job, skill) so 'top skills' is a simple GROUP BY."""

    __tablename__ = "job_skills"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    skill: Mapped[str] = mapped_column(String(60), primary_key=True, index=True)
    job: Mapped[Job] = relationship(back_populates="skills")


class PipelineRun(Base):
    """Audit log of every run, shown on the dashboard."""

    __tablename__ = "pipeline_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sources: Mapped[str] = mapped_column(String(200), default="")
    scraped: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    extracted: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    notes: Mapped[str] = mapped_column(Text, default="")


def get_engine(url: Optional[str] = None):
    url = url or config.DATABASE_URL
    if url.startswith("postgres://"):  # Heroku/Neon style URLs
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("sqlite:///"):
        from pathlib import Path

        path = url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, pool_pre_ping=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def make_dedupe_key(job: RawJob) -> str:
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    city = norm(job.location_raw.split(",")[0]) if job.location_raw else ""
    raw = f"{norm(job.title)}|{norm(job.company)}|{city}"
    return hashlib.sha256(raw.encode()).hexdigest()


def upsert_jobs(session: Session, jobs: list[RawJob]) -> int:
    """Insert new jobs, skip ones we already have. Returns the number inserted."""
    inserted = 0
    seen_keys: set[str] = set()
    for rj in jobs:
        key = make_dedupe_key(rj)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        exists = session.scalar(
            select(Job.id).where(
                (Job.dedupe_key == key)
                | ((Job.source == rj.source) & (Job.external_id == rj.external_id))
            )
        )
        if exists:
            continue
        session.add(Job(dedupe_key=key, **rj.model_dump()))
        inserted += 1
    session.commit()
    return inserted


def pending_jobs(session: Session, limit: int) -> list[Job]:
    stmt = (
        select(Job)
        .where(Job.extracted_at.is_(None))
        .order_by(Job.posted_at.desc().nulls_last(), Job.id)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def save_extraction(session: Session, job: Job, ext: JobExtraction, method: str) -> None:
    job.role_category = ext.role_category
    job.seniority = ext.seniority
    job.salary_min_lpa = ext.salary_min_lpa
    job.salary_max_lpa = ext.salary_max_lpa
    job.city = ext.city
    job.work_mode = ext.work_mode
    job.min_experience_years = ext.min_experience_years
    job.extraction_method = method
    job.extracted_at = utcnow()
    job.extraction_error = None
    job.skills = [JobSkill(skill=s) for s in ext.skills]
    session.commit()


def save_failure(session: Session, job: Job, error: str) -> None:
    job.extraction_error = error[:2000]
    session.commit()
