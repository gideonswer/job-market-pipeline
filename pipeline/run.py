"""Pipeline entry point.

    python -m pipeline.run                         # sample data, LLM if keys are set
    python -m pipeline.run --sources adzuna,remotive
    python -m pipeline.run --no-llm                # offline, heuristic extraction only
"""
import argparse
import logging
import sys

from sqlalchemy.orm import Session

from pipeline import config
from pipeline.db import (
    PipelineRun,
    get_engine,
    init_db,
    pending_jobs,
    save_extraction,
    save_failure,
    upsert_jobs,
    utcnow,
)
from pipeline.extract import available_providers, extract_job
from pipeline.scrapers import SCRAPERS

log = logging.getLogger("pipeline")


def run(sources: list[str], extract_limit: int, use_llm: bool, db_url: str | None = None) -> PipelineRun:
    engine = get_engine(db_url)
    init_db(engine)

    with Session(engine, expire_on_commit=False) as session:
        run_row = PipelineRun(sources=",".join(sources))
        session.add(run_row)
        session.commit()
        notes: list[str] = []

        # 1. EXTRACT: scrape every source; one broken source must not kill the run
        all_jobs = []
        for name in sources:
            try:
                jobs = SCRAPERS[name]().fetch()
                all_jobs.extend(jobs)
                log.info("%-9s %4d listings", name, len(jobs))
            except Exception as e:
                log.exception("scraper %s failed", name)
                notes.append(f"{name} failed: {e}")
        run_row.scraped = len(all_jobs)

        # 2. LOAD raw rows (deduplicated)
        run_row.inserted = upsert_jobs(session, all_jobs)
        log.info("inserted %d new jobs (%d duplicates skipped)", run_row.inserted, len(all_jobs) - run_row.inserted)

        # 3. TRANSFORM: LLM extraction for anything not processed yet
        if use_llm and not available_providers():
            log.warning("no GROQ_API_KEY / GEMINI_API_KEY set: using heuristic extractor")
        todo = pending_jobs(session, extract_limit)
        methods: dict[str, int] = {}
        for i, job in enumerate(todo, 1):
            try:
                ext, method = extract_job(
                    job.title, job.company, job.location_raw, job.salary_raw, job.description, use_llm
                )
                save_extraction(session, job, ext, method)
                methods[method] = methods.get(method, 0) + 1
                run_row.extracted += 1
            except Exception as e:
                session.rollback()
                save_failure(session, job, str(e))
                run_row.failed += 1
                log.warning("extraction failed for job %s: %s", job.id, e)
            if i % 25 == 0:
                log.info("extracted %d/%d", i, len(todo))

        if methods:
            notes.append("methods: " + ", ".join(f"{k}={v}" for k, v in methods.items()))
        run_row.notes = "; ".join(notes)
        run_row.status = "success" if not notes or all(n.startswith("methods") for n in notes) else "partial"
        run_row.finished_at = utcnow()
        session.commit()
        return run_row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Job Market Intelligence Pipeline")
    p.add_argument("--sources", default="sample", help=f"comma list from: {', '.join(SCRAPERS)}")
    p.add_argument("--extract-limit", type=int, default=config.EXTRACT_LIMIT)
    p.add_argument("--no-llm", action="store_true", help="skip LLM calls, use rule-based extraction")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in SCRAPERS]
    if unknown:
        p.error(f"unknown source(s): {unknown}")

    r = run(sources, args.extract_limit, use_llm=not args.no_llm)
    print(
        f"\nRun #{r.id} {r.status}: scraped={r.scraped} inserted={r.inserted} "
        f"extracted={r.extracted} failed={r.failed} {r.notes}"
    )
    return 0 if r.status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
