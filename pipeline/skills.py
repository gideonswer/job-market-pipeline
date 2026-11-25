"""Skill vocabulary and normalisation.

LLMs return the same skill in many spellings ("pytorch", "PyTorch", "Py-Torch").
Normalising them here keeps the dashboard counts honest.
"""
import re

# canonical name -> lowercase aliases (the canonical name itself is always matched)
SKILL_ALIASES: dict[str, list[str]] = {
    "Python": ["python3"],
    "SQL": ["sql", "mysql", "postgresql", "postgres"],
    "PyTorch": ["torch", "py-torch"],
    "TensorFlow": ["tensorflow", "tf", "keras"],
    "scikit-learn": ["sklearn", "scikit learn"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "LLMs": ["llm", "large language models", "large language model"],
    "LangChain": ["langchain"],
    "LlamaIndex": ["llama index", "llama-index"],
    "RAG": ["retrieval augmented generation", "retrieval-augmented generation"],
    "Prompt Engineering": ["prompting"],
    "Hugging Face": ["huggingface", "transformers", "hugging face transformers"],
    "NLP": ["natural language processing"],
    "Computer Vision": ["cv", "opencv"],
    "Deep Learning": ["dl"],
    "Machine Learning": ["ml"],
    "Vector Databases": ["vector db", "pinecone", "faiss", "chromadb", "chroma", "weaviate", "qdrant"],
    "AI Agents": ["agents", "agentic ai", "langgraph", "crewai", "autogen"],
    "Fine-tuning": ["finetuning", "fine tuning", "lora", "qlora", "peft"],
    "MLOps": ["mlflow", "kubeflow"],
    "Docker": ["docker"],
    "Kubernetes": ["k8s"],
    "AWS": ["amazon web services", "sagemaker", "aws sagemaker"],
    "GCP": ["google cloud", "vertex ai"],
    "Azure": ["azure ml", "azure openai"],
    "Spark": ["pyspark", "apache spark"],
    "Airflow": ["apache airflow"],
    "FastAPI": ["fastapi"],
    "Flask": ["flask"],
    "Git": ["github", "gitlab"],
    "Statistics": ["statistical modeling", "statistical modelling"],
    "Power BI": ["powerbi"],
    "Tableau": ["tableau"],
    "OpenAI API": ["openai", "gpt-4", "gpt"],
}

_LOOKUP: dict[str, str] = {}
for canonical, aliases in SKILL_ALIASES.items():
    _LOOKUP[canonical.lower()] = canonical
    for a in aliases:
        _LOOKUP[a.lower()] = canonical


def normalize_skill(skill: str) -> str:
    key = re.sub(r"\s+", " ", skill.strip().strip(".").lower())
    return _LOOKUP.get(key, skill.strip())


def normalize_skills(skills: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for s in skills:
        if s and s.strip() and len(s) <= 40:
            seen.setdefault(normalize_skill(s), None)
    return list(seen)


def find_skills_in_text(text: str) -> list[str]:
    """Keyword matcher used by the offline (no-LLM) extractor."""
    lowered = f" {text.lower()} "
    found = []
    for key, canonical in _LOOKUP.items():
        if len(key) <= 2:  # skip ambiguous short aliases like "ml", "cv", "tf"
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lowered):
            found.append(canonical)
    return normalize_skills(found)
