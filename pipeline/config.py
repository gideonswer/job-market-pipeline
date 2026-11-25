"""Central configuration. Everything is read from environment variables (or a .env file)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

# Postgres in production, e.g. postgresql+psycopg://user:pass@host:5432/jobs
# Falls back to a local SQLite file so the project runs with zero setup.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'jobs.db'}")

# LLM providers: Groq is primary, Gemini is the backup.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LLM_DELAY_SECONDS = float(os.getenv("LLM_DELAY_SECONDS", "2"))  # stay inside free-tier rate limits
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))

# Job sources
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
SEARCH_TERMS = [
    t.strip()
    for t in os.getenv(
        "SEARCH_TERMS",
        "AI engineer,machine learning engineer,data scientist,generative AI,LLM engineer",
    ).split(",")
    if t.strip()
]
MAX_PAGES_PER_TERM = int(os.getenv("MAX_PAGES_PER_TERM", "2"))

# How many unprocessed jobs to send to the LLM per run (protects free quotas).
EXTRACT_LIMIT = int(os.getenv("EXTRACT_LIMIT", "100"))
