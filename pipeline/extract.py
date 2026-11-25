"""Transform step: turn messy job text into a validated JobExtraction.

Order of attempts:  Groq  ->  Gemini  ->  rule-based heuristic.
Every LLM answer is validated with Pydantic; invalid JSON gets one retry
with the validation error fed back to the model.
"""
import json
import logging
import re
import time
from typing import Callable, Optional

import httpx
from pydantic import ValidationError

from pipeline import config
from pipeline.schemas import JobExtraction
from pipeline.skills import find_skills_in_text

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract structured data from Indian job listings for AI/data roles.
Return ONLY a JSON object matching this schema, no prose:

{schema}

Rules:
- skills: technical skills, frameworks and tools only (no soft skills), max 15.
- salary_*_lpa: ANNUAL salary in lakhs of INR. Convert: 1,800,000 INR/yr = 18; 1.5 lakh/month = 18;
  USD amounts -> multiply by 0.85 to get lakhs (e.g. $100,000 = 85). Use null if not stated. Never guess.
- city: the Indian city where the job is based (e.g. "Bengaluru", "Hyderabad"). null if fully remote or not stated.
- work_mode: "remote", "hybrid", "onsite", or "unknown".
- seniority: intern / junior (0-2 yrs) / mid (2-5) / senior (5-8) / lead (8+ or manager) / unknown.
- min_experience_years: the minimum years asked for, or null.
"""

_SCHEMA_JSON = json.dumps(JobExtraction.model_json_schema()["properties"], indent=1)


def build_user_prompt(title: str, company: str, location: str, salary: str, description: str) -> str:
    return (
        f"Title: {title}\nCompany: {company}\nLocation: {location}\n"
        f"Salary (raw): {salary or 'not given'}\n\nDescription:\n{description[:6000]}"
    )


def parse_llm_json(text: str) -> JobExtraction:
    """Accepts raw JSON or JSON wrapped in ```fences``` / surrounding text."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return JobExtraction.model_validate_json(text)


# ---------------------------------------------------------------- providers
def call_groq(system: str, user: str) -> str:
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
        json={
            "model": config.GROQ_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=config.LLM_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def call_gemini(system: str, user: str) -> str:
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": config.GEMINI_API_KEY},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        },
        timeout=config.LLM_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def available_providers() -> list[tuple[str, Callable[[str, str], str]]]:
    providers = []
    if config.GROQ_API_KEY:
        providers.append(("groq", call_groq))
    if config.GEMINI_API_KEY:
        providers.append(("gemini", call_gemini))
    return providers


def _try_provider(fn: Callable[[str, str], str], system: str, user: str) -> JobExtraction:
    raw = fn(system, user)
    try:
        return parse_llm_json(raw)
    except (ValidationError, ValueError) as e:
        # One self-correction retry: show the model what it got wrong.
        retry_user = f"{user}\n\nYour previous answer was invalid:\n{e}\nReturn corrected JSON only."
        return parse_llm_json(fn(system, retry_user))


# ---------------------------------------------------------------- heuristic fallback
_CITIES = [
    "Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Chennai", "Gurugram", "Gurgaon",
    "Noida", "Delhi", "New Delhi", "Kolkata", "Ahmedabad", "Kochi", "Jaipur", "Chandigarh",
    "Indore", "Coimbatore", "Thiruvananthapuram", "Shillong", "Guwahati", "Bhubaneswar",
]


def _parse_salary_lpa(text: str) -> tuple[Optional[float], Optional[float]]:
    t = text.lower().replace(",", "")
    # "12-18 LPA", "₹12 to 18 lakhs"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?)", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    # "1200000 - 1800000" (annual INR) or "80000 - 120000 per month"
    m = re.search(r"(\d{5,8})\s*(?:-|–|to)\s*(\d{5,8})(.{0,20})", t)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if "month" in m.group(3):
            lo, hi = lo * 12, hi * 12
        return round(lo / 1e5, 1), round(hi / 1e5, 1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)", t)
    if m:
        return float(m.group(1)), float(m.group(1))
    return None, None


def _role_category(title: str) -> str:
    t = title.lower()
    rules = [
        (("genai", "generative", "llm", "gen ai", "prompt", "agent"), "GenAI/LLM Engineer"),
        (("mlops", "ml ops", "ml platform"), "MLOps Engineer"),
        (("data engineer",), "Data Engineer"),
        (("research", "scientist - research"), "AI Research"),
        (("data scientist", "data science"), "Data Scientist"),
        (("analyst",), "Data Analyst"),
        (("machine learning", "ml engineer", "ai engineer", "computer vision", "nlp", "deep learning"), "ML Engineer"),
    ]
    for keys, cat in rules:
        if any(k in t for k in keys):
            return cat
    return "Other"


def _seniority(title: str, years: Optional[float]) -> str:
    t = title.lower()
    if "intern" in t:
        return "intern"
    if any(k in t for k in ("lead", "principal", "head", "manager", "architect", "staff")):
        return "lead"
    if any(k in t for k in ("senior", "sr.", "sr ")):
        return "senior"
    if any(k in t for k in ("junior", "jr", "associate", "fresher", "graduate", "trainee")):
        return "junior"
    if years is not None:
        return "junior" if years < 2 else "mid" if years < 5 else "senior" if years < 8 else "lead"
    return "unknown"


def heuristic_extract(title: str, company: str, location: str, salary: str, description: str) -> JobExtraction:
    """No-API extractor: keyword + regex rules. Lower quality, but never fails."""
    text = f"{title}\n{location}\n{salary}\n{description}"
    low = text.lower()

    years = None
    m = re.search(r"(\d+)\s*\+?\s*(?:-|to)?\s*(?:\d+\s*)?(?:years?|yrs?)", low)
    if m:
        years = float(m.group(1))

    city = next((c for c in _CITIES if re.search(rf"\b{c.lower()}\b", f"{location} {description}".lower())), None)

    if "hybrid" in low:
        mode = "hybrid"
    elif re.search(r"\b(remote|work from home|wfh)\b", low):
        mode = "remote"
    elif city:
        mode = "onsite"
    else:
        mode = "unknown"

    lo, hi = _parse_salary_lpa(f"{salary} {description}")
    return JobExtraction(
        role_category=_role_category(title),
        seniority=_seniority(title, years),
        skills=find_skills_in_text(text)[:15],
        salary_min_lpa=lo,
        salary_max_lpa=hi,
        city=city,
        work_mode=mode,
        min_experience_years=years,
    )


# ---------------------------------------------------------------- public API
def extract_job(
    title: str, company: str, location: str, salary: str, description: str, use_llm: bool = True
) -> tuple[JobExtraction, str]:
    """Returns (extraction, method_used)."""
    if use_llm:
        system = SYSTEM_PROMPT.format(schema=_SCHEMA_JSON)
        user = build_user_prompt(title, company, location, salary, description)
        for name, fn in available_providers():
            try:
                result = _try_provider(fn, system, user)
                time.sleep(config.LLM_DELAY_SECONDS)
                return result, name
            except httpx.HTTPStatusError as e:
                log.warning("%s HTTP %s: %s", name, e.response.status_code, e.response.text[:200])
            except Exception as e:  # network error, bad JSON twice, etc.
                log.warning("%s failed: %s", name, e)
    return heuristic_extract(title, company, location, salary, description), "heuristic"
