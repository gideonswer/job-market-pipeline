"""Remotive public API (remote jobs). Keeps only listings open to candidates in India.
Remotive asks for attribution and only a few requests per day, which a daily schedule respects."""
import logging
from datetime import datetime, timezone

from pipeline.schemas import RawJob
from pipeline.scrapers.base import BaseScraper

log = logging.getLogger(__name__)

API = "https://remotive.com/api/remote-jobs"
AI_WORDS = ("ai", "machine learning", "ml", "llm", "data scien", "nlp", "deep learning", "genai", "mlops")
INDIA_OK = ("india", "worldwide", "anywhere", "asia", "apac", "global")


class RemotiveScraper(BaseScraper):
    name = "remotive"

    def fetch(self) -> list[RawJob]:
        data = self.get_json(API, params={"category": "software-dev"})
        data_ds = self.get_json(API, params={"category": "data"})
        listings = data.get("jobs", []) + data_ds.get("jobs", [])
        jobs = []
        for r in listings:
            title = r.get("title", "")
            loc = (r.get("candidate_required_location") or "").lower()
            if not any(w in f" {title.lower()} " for w in AI_WORDS):
                continue
            if loc and not any(w in loc for w in INDIA_OK):
                continue
            jobs.append(self._parse(r))
        log.info("remotive: kept %d of %d listings", len(jobs), len(listings))
        return jobs

    def _parse(self, r: dict) -> RawJob:
        posted = r.get("publication_date")
        dt = datetime.fromisoformat(posted) if posted else None
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return RawJob(
            source="remotive",
            external_id=str(r["id"]),
            title=r.get("title", "").strip(),
            company=r.get("company_name", "Unknown"),
            location_raw=f"Remote ({r.get('candidate_required_location') or 'Worldwide'})",
            description=self.html_to_text(r.get("description", "")),
            salary_raw=r.get("salary", "") or "",
            url=r.get("url", ""),
            posted_at=dt,
        )
