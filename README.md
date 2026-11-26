# AI Job Market Intelligence Pipeline (India)

An end-to-end **ETL + LLM** data pipeline. Every day it scrapes AI and data job listings in India, uses an LLM to turn messy job descriptions into clean structured data (skills, salary, city, seniority, work mode), stores the results in **PostgreSQL**, and shows market trends on a **Streamlit** dashboard. **GitHub Actions** runs it on a schedule.

![Dashboard](docs/dashboard.png)
<sub>Screenshot uses the built-in synthetic sample data.</sub>

## What it answers

- Which skills are Indian AI employers asking for most, and which are **rising or falling**?
- What do AI roles pay at each seniority level (in LPA)?
- Which cities are hiring, and how much of the work is remote or hybrid?
- How is listing volume changing week by week?

## Architecture

```mermaid
flowchart LR
    subgraph Extract
        A[Adzuna API<br/>India endpoint]
        R[Remotive API<br/>remote, India-eligible]
        S[Sample generator<br/>offline demo]
    end
    subgraph Transform
        L1[Groq<br/>Llama 3.3 70B]
        L2[Gemini<br/>backup]
        H[Rule-based<br/>fallback]
        P{{Pydantic<br/>validation}}
    end
    subgraph Load
        DB[(PostgreSQL<br/>jobs · job_skills · pipeline_runs)]
    end
    A & R & S --> D[Dedupe] --> DB
    DB -- unprocessed jobs --> L1
    L1 -- fails --> L2 -- fails --> H
    L1 & L2 & H --> P --> DB
    DB --> UI[Streamlit dashboard]
    GH[GitHub Actions<br/>daily 09:00 IST] -. triggers .-> D
```

## Design decisions

| Problem | How it's handled |
|---|---|
| LLMs return messy or invalid JSON | A strict Pydantic schema (`JobExtraction`). Invalid output gets **one self-correction retry** with the validation error sent back to the model |
| Free-tier API limits and outages | Provider chain **Groq → Gemini → rule-based extractor**; per-call delay; `EXTRACT_LIMIT` caps calls per run; the method used is stored per row |
| The same skill spelled 5 ways | Canonical skill dictionary (`pipeline/skills.py`) merges `pytorch` / `torch` / `PyTorch` before storage |
| Duplicate listings | Unique `(source, external_id)` plus a `dedupe_key` hash of title + company + city to catch cross-source duplicates |
| Re-runs and crashes | Runs are **incremental** and idempotent. Only rows with `extracted_at IS NULL` go to the LLM, so a crashed run resumes where it stopped |
| One source breaking | Each scraper is isolated; failures are logged in `pipeline_runs` and the run is marked `partial` |
| Indian salary formats | Prompt and parser normalise "₹12-18 LPA", "INR 1,200,000 per year", and monthly pay into **lakhs per annum** |
| Analytics queries | Skills live in a separate `job_skills` table, so "top skills" is a plain `GROUP BY` (see `sql/analytics.sql`) |

## Quick start (no API keys needed)

```bash
git clone https://github.com/gideonswer/job-market-pipeline.git
cd job-market-pipeline
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m pipeline.run --sources sample --no-llm    # synthetic data, SQLite
streamlit run dashboard/app.py
```

## Real data with PostgreSQL + LLM

1. Get free keys: [Groq](https://console.groq.com/keys), [Gemini](https://aistudio.google.com/apikey), [Adzuna](https://developer.adzuna.com/).
2. `cp .env.example .env` and fill them in.
3. Start Postgres locally:
   ```bash
   docker compose up -d
   # in .env:  DATABASE_URL=postgresql+psycopg://jobs:jobs@localhost:5432/jobs
   ```
4. Run:
   ```bash
   python -m pipeline.run --sources adzuna,remotive
   streamlit run dashboard/app.py
   ```

CLI options: `--sources`, `--extract-limit N`, `--no-llm`, `-v`.

## Scheduling with GitHub Actions

`.github/workflows/pipeline.yml` runs every day at 09:00 IST (and on demand from the **Actions** tab).

1. Create a free hosted Postgres ([Neon](https://neon.tech) or [Supabase](https://supabase.com)) and copy its connection string.
2. In the repo, open **Settings → Secrets and variables → Actions** and add `DATABASE_URL`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.
3. Deploy the dashboard on [Streamlit Community Cloud](https://streamlit.io/cloud) (free) with the same `DATABASE_URL` as a secret.

`tests.yml` runs the test suite on every push.

## Project structure

```
pipeline/
  config.py          env-based settings
  schemas.py         Pydantic models: RawJob, JobExtraction
  skills.py          skill dictionary + normalisation
  scrapers/          adzuna.py, remotive.py, sample.py (base.py = retries, rate limiting)
  extract.py         LLM prompt, Groq/Gemini clients, retry, heuristic fallback
  db.py              SQLAlchemy models, dedupe, upsert
  run.py             orchestrator / CLI
dashboard/app.py     Streamlit dashboard
sql/analytics.sql    example analytical SQL (percentiles, co-occurrence, trends)
tests/               14 pytest tests (parsing, schema, dedupe, LLM fallback with mocks, full run)
.github/workflows/   daily pipeline + CI
```

## Tests

```bash
pip install pytest && pytest -q
```

LLM calls are mocked in tests, so they run offline and cost nothing.

## Adding a source

Subclass `BaseScraper`, implement `fetch() -> list[RawJob]`, and register it in `pipeline/scrapers/__init__.py`. Use official APIs, or check a site's terms and `robots.txt` before scraping its HTML.

## Data notes

- Sample-source data is **synthetic** (seeded random generator) and only for demos. The dashboard flags it.
- Remotive data is used with attribution, per its API terms. Listings link back to the original posting.
- Salary stats only include listings that state a salary.

## Tech stack

Python 3.11 · httpx · BeautifulSoup · Pydantic v2 · SQLAlchemy 2.0 · PostgreSQL 16 · Groq (Llama 3.3) · Google Gemini · pandas · Plotly · Streamlit · GitHub Actions · Docker Compose · pytest

## Live Demo Link
**🔗 Live demo: [ai-job-market-india.streamlit.app](https://ai-job-market-india.streamlit.app)**