"""Synthetic demo listings so the pipeline and dashboard work with no API keys.

The data is generated (seeded, so it's reproducible) and is clearly labelled
as 'sample' in the database and on the dashboard. It is NOT real market data.
"""
import random
from datetime import datetime, timedelta, timezone

from pipeline.schemas import RawJob
from pipeline.scrapers.base import BaseScraper

COMPANIES = [
    "Nimbus Analytics", "Quantiva Labs", "Saffron AI", "Deccan Data Works", "Lotus Cognitive",
    "Brahmaputra Tech", "IndusMind", "Kaveri Systems", "Monsoon Robotics", "Peak Pine Software",
    "Ganga Fintech", "Vistara Health AI", "Neelgiri Cloud", "Chakra Insights", "Arka Vision",
]
CITIES = ["Bengaluru", "Hyderabad", "Pune", "Gurugram", "Mumbai", "Chennai", "Noida", "Kolkata", "Shillong"]
CITY_WEIGHTS = [30, 18, 12, 10, 10, 8, 6, 3, 1]

ROLES = {
    "GenAI Engineer": ["Python", "LLMs", "LangChain", "RAG", "Vector Databases", "Prompt Engineering", "FastAPI", "OpenAI API"],
    "Machine Learning Engineer": ["Python", "PyTorch", "scikit-learn", "Docker", "AWS", "SQL", "MLflow"],
    "Data Scientist": ["Python", "SQL", "Pandas", "Statistics", "scikit-learn", "Tableau", "NumPy"],
    "MLOps Engineer": ["Docker", "Kubernetes", "MLflow", "AWS", "Airflow", "Python", "Git"],
    "Data Engineer": ["Python", "SQL", "Spark", "Airflow", "AWS", "Docker"],
    "AI Agent Developer": ["Python", "LangGraph", "LLMs", "RAG", "FastAPI", "CrewAI"],
    "Computer Vision Engineer": ["Python", "PyTorch", "OpenCV", "Deep Learning", "Docker"],
    "NLP Engineer": ["Python", "Hugging Face", "NLP", "PyTorch", "Fine-tuning"],
}
LEVELS = [("Junior", 0, (4, 9)), ("", 2, (9, 18)), ("Senior", 5, (18, 35)), ("Lead", 8, (32, 60))]
SALARY_FORMATS = [
    "₹{lo}-{hi} LPA",
    "INR {lo_inr} - {hi_inr} per year",
    "{lo} to {hi} Lakhs per annum",
    "",  # many listings hide salary
    "Competitive",
]


class SampleScraper(BaseScraper):
    name = "sample"

    def __init__(self, n: int = 180, seed: int = 42) -> None:
        self.n, self.seed = n, seed  # no HTTP client needed

    def fetch(self) -> list[RawJob]:
        rnd = random.Random(self.seed)
        today = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        jobs = []
        for i in range(self.n):
            days_ago = int(rnd.triangular(0, 90, 10))  # more recent listings than old ones
            role = rnd.choice(list(ROLES))
            # Make "agent" roles grow over time so the trend chart has a story.
            if days_ago < 30 and rnd.random() < 0.25:
                role = "AI Agent Developer"
            level, years, (smin, smax) = rnd.choice(LEVELS)
            city = rnd.choices(CITIES, CITY_WEIGHTS)[0]
            mode = rnd.choices(["Hybrid", "Remote", "On-site"], [45, 20, 35])[0]
            skills = rnd.sample(ROLES[role], k=min(len(ROLES[role]), rnd.randint(4, 6)))
            lo = rnd.randint(smin, (smin + smax) // 2)
            hi = rnd.randint(lo + 2, smax + 2)
            salary = rnd.choice(SALARY_FORMATS).format(lo=lo, hi=hi, lo_inr=lo * 100000, hi_inr=hi * 100000)
            title = f"{level} {role}".strip()
            company = rnd.choice(COMPANIES)
            desc = (
                f"{company} is hiring a {title} in {city} ({mode}). "
                f"You will build and ship AI features used by thousands of customers. "
                f"Requirements: {years}+ years of experience. "
                f"Must have: {', '.join(skills[:3])}. Nice to have: {', '.join(skills[3:]) or 'curiosity'}. "
                f"{'Salary: ' + salary + '.' if salary else ''}"
            )
            jobs.append(
                RawJob(
                    source="sample",
                    external_id=f"sample-{i}",
                    title=title,
                    company=company,
                    location_raw=f"{city}, India",
                    description=desc,
                    salary_raw=salary,
                    url="",
                    posted_at=today - timedelta(days=days_ago),
                )
            )
        return jobs
