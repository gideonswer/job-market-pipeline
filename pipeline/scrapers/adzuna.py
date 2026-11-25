"""Adzuna official API, India endpoint. Free key: https://developer.adzuna.com/"""
import logging
from datetime import datetime

from pipeline import config
from pipeline.schemas import RawJob
from pipeline.scrapers.base import BaseScraper

log = logging.getLogger(__name__)

API = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"


class AdzunaScraper(BaseScraper):
    name = "adzuna"

    def fetch(self) -> list[RawJob]:
        if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
            log.warning("adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set, skipping")
            return []
        jobs: list[RawJob] = []
        for term in config.SEARCH_TERMS:
            for page in range(1, config.MAX_PAGES_PER_TERM + 1):
                data = self.get_json(
                    API.format(page=page),
                    params={
                        "app_id": config.ADZUNA_APP_ID,
                        "app_key": config.ADZUNA_APP_KEY,
                        "what": term,
                        "results_per_page": 50,
                        "max_days_old": 30,
                        "content-type": "application/json",
                    },
                )
                results = data.get("results", [])
                jobs.extend(self._parse(r) for r in results)
                if len(results) < 50:
                    break
        log.info("adzuna: fetched %d listings", len(jobs))
        return jobs

    @staticmethod
    def _parse(r: dict) -> RawJob:
        lo, hi = r.get("salary_min"), r.get("salary_max")
        salary = f"INR {int(lo)} - {int(hi)} per year" if lo and hi else ""
        posted = r.get("created")
        return RawJob(
            source="adzuna",
            external_id=str(r["id"]),
            title=r.get("title", "").strip(),
            company=(r.get("company") or {}).get("display_name", "Unknown"),
            location_raw=(r.get("location") or {}).get("display_name", ""),
            description=r.get("description", ""),
            salary_raw=salary,
            url=r.get("redirect_url", ""),
            posted_at=datetime.fromisoformat(posted.replace("Z", "+00:00")) if posted else None,
        )
