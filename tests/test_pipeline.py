from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pipeline.db import Job, JobSkill, PipelineRun, get_engine, init_db, upsert_jobs
from pipeline.run import run
from pipeline.schemas import RawJob


def _job(i, title="ML Engineer", company="Acme", source="test"):
    return RawJob(source=source, external_id=str(i), title=title, company=company, location_raw="Pune, India")


def test_upsert_deduplicates_within_and_across_sources(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 't.db'}")
    init_db(engine)
    with Session(engine) as s:
        assert upsert_jobs(s, [_job(1), _job(2, title="Data Scientist")]) == 2
        assert upsert_jobs(s, [_job(1)]) == 0  # same source + id
        assert upsert_jobs(s, [_job(99, source="other")]) == 0  # same title/company/city elsewhere
        assert s.scalar(select(func.count(Job.id))) == 2


def test_full_run_on_sample_data_is_incremental(tmp_path):
    url = f"sqlite:///{tmp_path / 'run.db'}"
    first = run(["sample"], extract_limit=50, use_llm=False, db_url=url)
    assert first.status == "success" and first.inserted > 100 and first.extracted == 50

    second = run(["sample"], extract_limit=1000, use_llm=False, db_url=url)
    assert second.inserted == 0  # nothing new
    assert second.extracted == first.inserted - 50  # only the leftovers

    with Session(get_engine(url)) as s:
        assert s.scalar(select(func.count(Job.id)).where(Job.extracted_at.is_(None))) == 0
        assert s.scalar(select(func.count()).select_from(JobSkill)) > 0
        assert s.scalar(select(func.count(PipelineRun.id))) == 2
