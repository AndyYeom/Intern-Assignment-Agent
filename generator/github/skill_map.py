"""Map GitHub evidence onto canonical taxonomy skill ids.

Deterministic on purpose. This layer *finds* evidence; the evidence agent later
*judges* it. Keeping the finding in code makes every claim traceable to a file,
a dependency or a byte count, which is what "evidence strength + repo links"
in C's deliverable requires.

Sources, ordered by how much they are worth trusting:
  language  - bytes reported by GitHub. Hard to fake.
  manifest  - a declared dependency. Hard to fake, and reaches most of the taxonomy.
  file      - a path in the tree (Dockerfile, .github/workflows/). Fairly hard to fake.
  topic     - self-declared repo topic. Weak.
  repo_name - a word in the repo name. Weakest; never sufficient alone.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from generator.config import TAXONOMY_PATH

SOURCE_STRENGTH = {
    "language": 1.0,
    "manifest": 0.9,
    "file": 0.6,
    "topic": 0.3,
    "repo_name": 0.2,
}


@dataclass(frozen=True)
class SkillSignal:
    skill_id: str
    source: str
    detail: str
    strength: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def taxonomy() -> dict[str, Any]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def skill_ids() -> frozenset[str]:
    return frozenset(s["id"] for s in taxonomy()["skills"])


@lru_cache(maxsize=1)
def alias_index() -> dict[str, str]:
    """Lowercased alias/name -> skill id, straight from taxonomy.json."""
    index: dict[str, str] = {}
    for skill in taxonomy()["skills"]:
        index[skill["id"].lower()] = skill["id"]
        index[skill["name"].lower()] = skill["id"]
        for alias in skill.get("aliases", []):
            index[alias.lower()] = skill["id"]
    return index


# GitHub's linguist language names -> taxonomy ids.
LANGUAGE_TO_SKILL = {
    "python": "python",
    "jupyter notebook": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "java": "java",
    "c": "c-cpp",
    "c++": "c-cpp",
    "c#": "csharp",
    "go": "go",
    "html": "html-css",
    "css": "html-css",
    "scss": "html-css",
    "sass": "html-css",
    "less": "html-css",
    "shell": "shell",
    "powershell": "shell",
    "dockerfile": "docker",
    "plpgsql": "postgresql",
    "sql": "sql",
    "tsql": "sql",
    "vue": "vue",
    "svelte": "javascript",
    "dart": "flutter",
    "swift": "native-mobile",
    "kotlin": "native-mobile",
    "objective-c": "native-mobile",
    "makefile": "shell",
    "hcl": "gcp-azure",
}

# Dependency name (substring-matched against declared deps) -> taxonomy id.
DEPENDENCY_TO_SKILL = {
    # python backend / data / ml
    "django": "django", "djangorestframework": "django",
    "flask": "flask-fastapi", "fastapi": "flask-fastapi", "uvicorn": "flask-fastapi",
    "sqlalchemy": "data-modeling", "alembic": "data-modeling",
    "psycopg": "postgresql", "asyncpg": "postgresql",
    "pymysql": "mysql", "mysqlclient": "mysql",
    "pymongo": "mongodb", "motor": "mongodb", "mongoengine": "mongodb",
    "redis": "redis",
    "celery": "etl", "airflow": "etl", "dbt-core": "etl", "prefect": "etl", "luigi": "etl",
    "pandas": "pandas", "numpy": "pandas", "polars": "pandas",
    "matplotlib": "data-viz", "seaborn": "data-viz", "plotly": "data-viz", "bokeh": "data-viz",
    "beautifulsoup4": "web-scraping", "bs4": "web-scraping", "scrapy": "web-scraping",
    "selenium": "web-scraping", "playwright": "web-scraping", "requests-html": "web-scraping",
    "scikit-learn": "machine-learning", "sklearn": "machine-learning",
    "xgboost": "machine-learning", "lightgbm": "machine-learning", "catboost": "machine-learning",
    "torch": "deep-learning", "pytorch": "deep-learning", "tensorflow": "deep-learning",
    "keras": "deep-learning", "pytorch-lightning": "deep-learning", "jax": "deep-learning",
    "transformers": "nlp", "spacy": "nlp", "nltk": "nlp", "gensim": "nlp", "datasets": "nlp",
    "opencv-python": "computer-vision", "cv2": "computer-vision", "pillow": "computer-vision",
    "torchvision": "computer-vision", "ultralytics": "computer-vision", "albumentations": "computer-vision",
    "langchain": "llm-apps", "llama-index": "llm-apps", "llama_index": "llm-apps",
    "openai": "llm-apps", "anthropic": "llm-apps", "litellm": "llm-apps",
    "instructor": "llm-apps", "guidance": "llm-apps", "ollama": "llm-apps",
    "chromadb": "rag", "faiss-cpu": "rag", "faiss": "rag", "pinecone": "rag",
    "qdrant-client": "rag", "weaviate-client": "rag", "sentence-transformers": "rag",
    "pgvector": "rag", "lancedb": "rag",
    "surprise": "recsys", "implicit": "recsys", "lightfm": "recsys",
    "pytest": "unit-testing", "unittest2": "unit-testing", "nose": "unit-testing",
    "hypothesis": "unit-testing", "tox": "unit-testing",
    "boto3": "aws", "awscli": "aws", "aws-cdk-lib": "aws",
    "google-cloud-storage": "gcp-azure", "firebase-admin": "gcp-azure", "azure-identity": "gcp-azure",
    "prometheus-client": "monitoring", "sentry-sdk": "monitoring", "opentelemetry-api": "monitoring",
    "authlib": "auth", "pyjwt": "auth", "python-jose": "auth", "passlib": "auth",
    "graphene": "graphql", "strawberry-graphql": "graphql", "ariadne": "graphql",
    "websockets": "websockets", "channels": "websockets", "socketio": "websockets",
    "streamlit": "data-viz", "gradio": "llm-apps", "dash": "data-viz",
    # js / ts
    "react": "react", "react-dom": "react",
    "vue": "vue", "nuxt": "vue",
    "next": "nextjs",
    "tailwindcss": "tailwind",
    "redux": "state-management", "@reduxjs/toolkit": "state-management",
    "zustand": "state-management", "pinia": "state-management", "mobx": "state-management",
    "express": "nodejs", "fastify": "nodejs", "koa": "nodejs", "nestjs": "nodejs",
    "@nestjs/core": "nodejs", "hapi": "nodejs",
    "mongoose": "mongodb",
    "pg": "postgresql", "postgres": "postgresql",
    "mysql2": "mysql",
    "ioredis": "redis",
    "prisma": "data-modeling", "typeorm": "data-modeling", "sequelize": "data-modeling",
    "drizzle-orm": "data-modeling", "knex": "data-modeling",
    "graphql": "graphql", "@apollo/client": "graphql", "apollo-server": "graphql",
    "socket.io": "websockets", "ws": "websockets",
    "jsonwebtoken": "auth", "passport": "auth", "next-auth": "auth", "@auth0/auth0-react": "auth",
    "jest": "unit-testing", "vitest": "unit-testing", "mocha": "unit-testing", "chai": "unit-testing",
    "cypress": "integration-testing", "@playwright/test": "integration-testing",
    "puppeteer": "web-scraping", "cheerio": "web-scraping",
    "d3": "data-viz", "chart.js": "data-viz", "recharts": "data-viz",
    "react-native": "react-native", "expo": "react-native",
    "eslint": "code-review", "prettier": "code-review",
    "firebase": "gcp-azure", "aws-sdk": "aws", "@aws-sdk/client-s3": "aws",
    "langchainjs": "llm-apps",
    # java
    "spring-boot-starter": "spring", "spring-boot": "spring", "springframework": "spring",
    "junit": "unit-testing", "mockito": "unit-testing",
    "hibernate": "data-modeling",
}

# Path patterns -> taxonomy id. Matched against the repo's full file tree.
FILE_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^\.github/workflows/.+\.ya?ml$"), "cicd", "GitHub Actions workflow"),
    (re.compile(r"^(\.gitlab-ci\.yml|Jenkinsfile|\.circleci/config\.yml|azure-pipelines\.yml)$"), "cicd", "CI config"),
    (re.compile(r"(^|/)dockerfile(\.[\w-]+)?$", re.IGNORECASE), "docker", "Dockerfile"),
    (re.compile(r"(^|/)docker-compose(\.[\w-]+)?\.ya?ml$", re.IGNORECASE), "docker", "docker-compose"),
    (re.compile(r"(^|/)(k8s|kubernetes|charts|helm)/"), "kubernetes", "kubernetes manifests"),
    (re.compile(r"(^|/)(Chart\.yaml|values\.yaml)$"), "kubernetes", "helm chart"),
    (re.compile(r"(^|/)(tests?|spec)/.+\.(py|js|ts|tsx|java|go)$"), "unit-testing", "test directory"),
    (re.compile(r"(^|/)(test_[\w-]+\.py|[\w-]+_test\.(py|go)|[\w-]+\.(test|spec)\.(js|ts|tsx|jsx))$"), "unit-testing", "test file"),
    (re.compile(r"(^|/)(cypress|e2e|playwright)(\.config\.[jt]s|/)"), "integration-testing", "e2e suite"),
    (re.compile(r"\.(sql)$"), "sql", "SQL file"),
    (re.compile(r"(^|/)migrations?/"), "data-modeling", "database migrations"),
    (re.compile(r"(^|/)(terraform|\.tf)$|\.tf$"), "gcp-azure", "terraform"),
    (re.compile(r"(^|/)(serverless\.yml|template\.yaml|samconfig\.toml)$"), "aws", "AWS IaC"),
    (re.compile(r"(^|/)(firebase\.json|\.firebaserc)$"), "gcp-azure", "firebase config"),
    (re.compile(r"(^|/)(tailwind\.config\.[jt]s)$"), "tailwind", "tailwind config"),
    (re.compile(r"(^|/)(next\.config\.[jmt]s)$"), "nextjs", "next config"),
    (re.compile(r"(^|/)(nginx\.conf|Caddyfile|\.service)$"), "linux", "server config"),
    (re.compile(r"(^|/)(prometheus\.yml|grafana/)"), "monitoring", "monitoring config"),
    (re.compile(r"(^|/)(docs?|documentation)/.+\.mdx?$"), "technical-writing", "docs directory"),
    (re.compile(r"(^|/)(pubspec\.yaml)$"), "flutter", "flutter project"),
    (re.compile(r"(^|/)(Podfile|\.xcodeproj/|build\.gradle(\.kts)?)$"), "native-mobile", "native mobile project"),
    (re.compile(r"(^|/)(schema\.prisma)$"), "data-modeling", "prisma schema"),
    (re.compile(r"\.ipynb$"), "pandas", "jupyter notebook"),
    (re.compile(r"(^|/)(\.env\.example|\.env\.sample)$"), "linux", "env config"),
]

MANIFEST_FILES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile",
    "environment.yml", "setup.py", "package.json", "pom.xml", "build.gradle",
    "build.gradle.kts", "go.mod", "Gemfile", "composer.json", "Cargo.toml",
}

_DEP_LINE = re.compile(r"^\s*([A-Za-z0-9._@/-]+)")


def parse_manifest(path: str, text: str) -> set[str]:
    """Pull declared dependency names out of a manifest. Best-effort by design."""
    name = path.rsplit("/", 1)[-1]
    deps: set[str] = set()

    if name == "package.json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return deps
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            deps.update(k.lower() for k in (data.get(key) or {}))
        return deps

    if name in {"requirements.txt", "requirements-dev.txt", "Pipfile", "environment.yml", "setup.py"}:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-", "//")):
                continue
            match = _DEP_LINE.match(line)
            if match:
                deps.add(match.group(1).lower().strip("\"',"))
        return deps

    if name == "pyproject.toml":
        # Catch both [project].dependencies and poetry's table form without a TOML parse.
        for match in re.finditer(r'["\']([A-Za-z0-9._-]+)\s*(?:[><=~!^\[]|["\'])', text):
            deps.add(match.group(1).lower())
        for match in re.finditer(r"^\s*([A-Za-z0-9._-]+)\s*=\s*[\"{]", text, re.MULTILINE):
            deps.add(match.group(1).lower())
        return deps

    if name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
        for match in re.finditer(r"<artifactId>([^<]+)</artifactId>", text):
            deps.add(match.group(1).lower())
        for match in re.finditer(r"['\"]([a-z0-9.\-]+:[a-z0-9.\-]+)", text):
            deps.update(part for part in match.group(1).split(":"))
        return deps

    if name == "go.mod":
        for match in re.finditer(r"^\s+([\w./-]+)\s+v", text, re.MULTILINE):
            deps.add(match.group(1).lower())
        return deps

    # Cargo.toml / composer.json / Gemfile - generic token sweep.
    for match in re.finditer(r"^\s*['\"]?([A-Za-z0-9._/-]+)['\"]?\s*[=:]", text, re.MULTILINE):
        deps.add(match.group(1).lower())
    return deps


def _dep_skill(dep: str) -> str | None:
    dep = dep.lower().strip()
    if dep in DEPENDENCY_TO_SKILL:
        return DEPENDENCY_TO_SKILL[dep]
    # scoped npm packages: @scope/name
    base = dep.split("/")[-1]
    if base in DEPENDENCY_TO_SKILL:
        return DEPENDENCY_TO_SKILL[base]
    if dep in alias_index():
        return alias_index()[dep]
    return None


def signals_from_languages(languages: dict[str, int]) -> list[SkillSignal]:
    total = sum(languages.values()) or 1
    out: list[SkillSignal] = []
    for language, byte_count in languages.items():
        skill = LANGUAGE_TO_SKILL.get(language.lower())
        if not skill:
            continue
        share = byte_count / total
        # A language that is a rounding error in the repo is not evidence of the skill.
        if byte_count < 1000 and share < 0.05:
            continue
        out.append(
            SkillSignal(
                skill_id=skill,
                source="language",
                detail=f"{language}: {byte_count:,} bytes ({share:.0%} of repo)",
                strength=SOURCE_STRENGTH["language"] * min(1.0, 0.4 + share),
            )
        )
    return out


def signals_from_dependencies(deps: Iterable[str], manifest_path: str) -> list[SkillSignal]:
    seen: dict[str, str] = {}
    for dep in deps:
        skill = _dep_skill(dep)
        if skill and skill not in seen:
            seen[skill] = dep
    return [
        SkillSignal(skill_id=skill, source="manifest", detail=f"{dep} in {manifest_path}",
                    strength=SOURCE_STRENGTH["manifest"])
        for skill, dep in seen.items()
    ]


def signals_from_tree(paths: Iterable[str]) -> list[SkillSignal]:
    seen: dict[str, str] = {}
    for path in paths:
        for pattern, skill, label in FILE_PATTERNS:
            if skill in seen:
                continue
            if pattern.search(path):
                seen[skill] = f"{label} ({path})"
    return [
        SkillSignal(skill_id=skill, source="file", detail=detail, strength=SOURCE_STRENGTH["file"])
        for skill, detail in seen.items()
    ]


def signals_from_topics(topics: Iterable[str]) -> list[SkillSignal]:
    index = alias_index()
    out: list[SkillSignal] = []
    seen: set[str] = set()
    for topic in topics:
        key = topic.lower().replace("-", " ")
        skill = index.get(topic.lower()) or index.get(key)
        if skill and skill not in seen:
            seen.add(skill)
            out.append(SkillSignal(skill, "topic", f"repo topic '{topic}'", SOURCE_STRENGTH["topic"]))
    return out


def signals_from_name(name: str, description: str | None) -> list[SkillSignal]:
    text = f"{name} {description or ''}".lower()
    tokens = set(re.split(r"[^a-z0-9+#.]+", text))
    index = alias_index()
    out: list[SkillSignal] = []
    seen: set[str] = set()
    for token in tokens:
        skill = index.get(token)
        if skill and skill not in seen:
            seen.add(skill)
            out.append(SkillSignal(skill, "repo_name", f"'{token}' in repo name/description",
                                   SOURCE_STRENGTH["repo_name"]))
    return out
