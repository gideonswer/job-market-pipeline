import pytest

from pipeline.extract import _parse_salary_lpa, heuristic_extract, parse_llm_json
from pipeline.schemas import JobExtraction
from pipeline.skills import find_skills_in_text, normalize_skills


@pytest.mark.parametrize(
    "text,expected",
    [
        ("₹12-18 LPA", (12.0, 18.0)),
        ("10 to 18 Lakhs per annum", (10.0, 18.0)),
        ("INR 1,200,000 - 1,800,000 per year", (12.0, 18.0)),
        ("80000 - 120000 per month", (9.6, 14.4)),
        ("Competitive", (None, None)),
    ],
)
def test_salary_parsing(text, expected):
    assert _parse_salary_lpa(text) == expected


def test_skill_normalisation_merges_spellings():
    assert normalize_skills(["pytorch", "PyTorch", "torch", "sklearn", "LLM"]) == [
        "PyTorch",
        "scikit-learn",
        "LLMs",
    ]


def test_find_skills_ignores_short_ambiguous_aliases():
    skills = find_skills_in_text("We use Python, LangChain and RAG. HTML/CSS a plus.")
    assert {"Python", "LangChain", "RAG"} <= set(skills)
    assert "Machine Learning" not in skills  # "ml" inside "HTML" must not match


def test_parse_llm_json_handles_code_fences():
    raw = 'Sure!\n```json\n{"role_category": "ML Engineer", "seniority": "mid", "skills": ["python"], "city": "bangalore", "work_mode": "hybrid"}\n```'
    ext = parse_llm_json(raw)
    assert ext.city == "Bengaluru"
    assert ext.skills == ["Python"]


def test_schema_swaps_inverted_salary_and_rejects_bad_enum():
    ext = JobExtraction(role_category="Other", salary_min_lpa=30, salary_max_lpa=20)
    assert (ext.salary_min_lpa, ext.salary_max_lpa) == (20, 30)
    with pytest.raises(ValueError):
        JobExtraction(role_category="Other", work_mode="sometimes")


def test_heuristic_extract_end_to_end():
    ext = heuristic_extract(
        "Senior GenAI Engineer",
        "Acme",
        "Hyderabad, India",
        "₹25-35 LPA",
        "Hybrid role. 5+ years. Must know Python, LangChain, vector db and Docker.",
    )
    assert ext.role_category == "GenAI/LLM Engineer"
    assert ext.seniority == "senior"
    assert ext.city == "Hyderabad"
    assert ext.work_mode == "hybrid"
    assert (ext.salary_min_lpa, ext.salary_max_lpa) == (25, 35)
    assert {"Python", "LangChain", "Vector Databases", "Docker"} <= set(ext.skills)


def test_llm_retry_then_fallback(monkeypatch):
    """Groq returns invalid JSON twice -> Gemini is tried; Gemini fixes itself on retry."""
    import pipeline.extract as ex

    calls = []

    def bad_groq(system, user):
        calls.append("groq")
        return "not json"

    def flaky_gemini(system, user):
        calls.append("gemini")
        if "previous answer was invalid" not in user:
            return '{"role_category": "ML Engineer", "work_mode": "sometimes"}'
        return '{"role_category": "ML Engineer", "work_mode": "remote", "skills": ["pytorch"]}'

    monkeypatch.setattr(ex, "available_providers", lambda: [("groq", bad_groq), ("gemini", flaky_gemini)])
    monkeypatch.setattr(ex.config, "LLM_DELAY_SECONDS", 0)
    result, method = ex.extract_job("ML Engineer", "Acme", "Remote", "", "PyTorch role")
    assert method == "gemini"
    assert result.work_mode == "remote" and result.skills == ["PyTorch"]
    assert calls == ["groq", "groq", "gemini", "gemini"]


def test_all_llms_down_falls_back_to_heuristic(monkeypatch):
    import pipeline.extract as ex

    def down(system, user):
        raise ConnectionError("offline")

    monkeypatch.setattr(ex, "available_providers", lambda: [("groq", down)])
    _, method = ex.extract_job("Data Scientist", "Acme", "Pune", "", "Python, SQL")
    assert method == "heuristic"
