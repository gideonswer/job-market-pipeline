import logging
import time

import httpx
from bs4 import BeautifulSoup

from pipeline.schemas import RawJob

log = logging.getLogger(__name__)

USER_AGENT = "JobMarketIntelligenceBot/1.0 (portfolio project; github.com/gideonswer)"


class BaseScraper:
    name = "base"
    delay_seconds = 1.0  # be polite to the source

    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
        )

    def get_json(self, url: str, params: dict | None = None, retries: int = 3) -> dict:
        for attempt in range(1, retries + 1):
            try:
                r = self.client.get(url, params=params)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                time.sleep(self.delay_seconds)
                return r.json()
            except httpx.HTTPError as e:
                if attempt == retries:
                    raise
                wait = 2**attempt
                log.warning("%s: %s (attempt %d), retrying in %ds", self.name, e, attempt, wait)
                time.sleep(wait)
        return {}

    @staticmethod
    def html_to_text(html: str) -> str:
        return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)

    def fetch(self) -> list[RawJob]:
        raise NotImplementedError
