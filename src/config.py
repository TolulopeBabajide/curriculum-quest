"""Central config — loads .env once and exposes typed settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)


@dataclass(frozen=True)
class Settings:
    # Foundry (model backend)
    project_endpoint: str = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    model_deployment: str = os.getenv("AZURE_AI_MODEL_DEPLOYMENT", "gpt-4o")

    # Foundry IQ (grounding)
    search_endpoint: str = os.getenv("SEARCH_ENDPOINT", "")
    search_query_key: str = os.getenv("SEARCH_QUERY_KEY", "")
    search_admin_key: str = os.getenv("SEARCH_ADMIN_KEY", "")
    kb_curriculum: str = os.getenv("KB_CURRICULUM", "jss1-basic-science-kb")
    kb_world: str = os.getenv("KB_WORLD", "lumenor-lore-kb")

    # Indexing backends (used only by the seed script)
    aoai_endpoint: str = os.getenv("AOAI_ENDPOINT", "")
    embedding_deployment: str = os.getenv("AOAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")

    # Game
    subject: str = os.getenv("SUBJECT", "Basic Science")
    grade: str = os.getenv("GRADE", "JSS1")

    # If Foundry IQ isn't reachable, fall back to local file retrieval so the game still runs.
    use_local_fallback: bool = os.getenv("USE_LOCAL_FALLBACK", "false").lower() == "true"


settings = Settings()

KB_MCP_API_VERSION = "2025-11-01-preview"


def kb_mcp_url(kb_name: str) -> str:
    """The MCP endpoint a Foundry IQ knowledge base exposes."""
    return (
        f"{settings.search_endpoint}/knowledgebases/{kb_name}/mcp"
        f"?api-version={KB_MCP_API_VERSION}"
    )
