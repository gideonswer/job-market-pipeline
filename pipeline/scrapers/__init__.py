"""Job sources. Each scraper exposes fetch() -> list[RawJob]."""
from pipeline.scrapers.adzuna import AdzunaScraper
from pipeline.scrapers.remotive import RemotiveScraper
from pipeline.scrapers.sample import SampleScraper

SCRAPERS = {
    "adzuna": AdzunaScraper,
    "remotive": RemotiveScraper,
    "sample": SampleScraper,
}
