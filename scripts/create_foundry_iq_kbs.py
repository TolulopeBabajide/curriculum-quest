"""Create the Foundry IQ knowledge sources + knowledge bases over the seeded indexes.

This finishes Block 3: it turns the two Azure AI Search indexes produced by
`seed_foundry_iq.py` into queryable Foundry IQ knowledge bases (agentic retrieval +
cited synthesis), each exposing an MCP endpoint the game consumes.

For each (index -> knowledge source -> knowledge base) it:
  1. Adds a semantic configuration to the index (agentic retrieval needs semantic reranking).
  2. Creates a `searchIndex` knowledge source over the index.
  3. Creates a knowledge base that pairs the source with the Azure OpenAI chat model
     (answer synthesis with citations).

Names match .env (KB_CURRICULUM, KB_WORLD) so the game's MCP endpoints resolve.

Run:  python scripts/create_foundry_iq_kbs.py
Prereqs:  filled .env (SEARCH_ENDPOINT, SEARCH_ADMIN_KEY, AOAI_ENDPOINT, AZURE_AI_MODEL_DEPLOYMENT)
          + indexes already seeded (run seed_foundry_iq.py first).
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings, KB_MCP_API_VERSION  # noqa: E402

API = KB_MCP_API_VERSION  # 2025-11-01-preview — matches the MCP url the game uses
SEMANTIC_CONFIG = "semantic-config"

# (index, knowledge source, knowledge base, description)
TARGETS = [
    (
        "jss1-basic-science-index",
        "jss1-basic-science-source",
        settings.kb_curriculum,
        "NERDC JSS1 Basic Science curriculum (cited).",
    ),
    (
        "lumenor-lore-index",
        "lumenor-lore-source",
        settings.kb_world,
        "Oke-Ola world pack (synthetic community lore).",
    ),
]


def _headers() -> dict:
    return {"api-key": settings.search_admin_key, "Content-Type": "application/json"}


def _url(path: str) -> str:
    return f"{settings.search_endpoint}/{path}?api-version={API}"


def ensure_semantic_config(index_name: str) -> None:
    """Add a semantic configuration to the index if it doesn't have one (non-destructive)."""
    r = requests.get(
        f"{settings.search_endpoint}/indexes/{index_name}?api-version=2024-07-01",
        headers=_headers(),
    )
    r.raise_for_status()
    index = r.json()

    existing = (index.get("semantic") or {}).get("configurations") or []
    if any(c.get("name") == SEMANTIC_CONFIG for c in existing):
        print(f"  · semantic config already present on '{index_name}'")
        return

    index["semantic"] = {
        "configurations": [
            {
                "name": SEMANTIC_CONFIG,
                "prioritizedFields": {
                    "titleField": {"fieldName": "title"},
                    "prioritizedContentFields": [{"fieldName": "content"}],
                    "prioritizedKeywordsFields": [{"fieldName": "citation"}],
                },
            }
        ]
    }
    # PUT the full definition back (adding a semantic config does not require reindexing).
    r = requests.put(
        f"{settings.search_endpoint}/indexes/{index_name}?api-version=2024-07-01",
        headers=_headers(),
        json=index,
    )
    r.raise_for_status()
    print(f"  ✓ added semantic config to '{index_name}'")


def create_knowledge_source(source: str, index_name: str, description: str) -> None:
    body = {
        "name": source,
        "kind": "searchIndex",
        "description": description,
        "searchIndexParameters": {
            "searchIndexName": index_name,
            "semanticConfigurationName": SEMANTIC_CONFIG,
            "sourceDataFields": [
                {"name": "id"},
                {"name": "title"},
                {"name": "citation"},
                {"name": "source_file"},
            ],
        },
    }
    r = requests.put(_url(f"knowledgeSources/{source}"), headers=_headers(), json=body)
    r.raise_for_status()
    print(f"  ✓ knowledge source '{source}' -> index '{index_name}'")


def create_knowledge_base(kb: str, source: str, description: str) -> None:
    aoai = settings.aoai_endpoint.rstrip("/")
    model = settings.model_deployment
    body = {
        "name": kb,
        "description": description,
        "answerInstructions": (
            "Answer ONLY from the retrieved curriculum passages and always keep the source "
            "reference so the caller can cite it. Be concise and practical."
        ),
        "outputMode": "answerSynthesis",
        "knowledgeSources": [{"name": source}],
        "models": [
            {
                "kind": "azureOpenAI",
                "azureOpenAIParameters": {
                    "resourceUri": aoai,
                    "deploymentId": model,
                    "modelName": model,
                },
            }
        ],
    }
    r = requests.put(_url(f"knowledgeBases/{kb}"), headers=_headers(), json=body)
    r.raise_for_status()
    print(f"  ✓ knowledge base '{kb}' (model: {model})")


def main() -> None:
    if not settings.search_admin_key or not settings.aoai_endpoint:
        sys.exit("Fill SEARCH_ENDPOINT, SEARCH_ADMIN_KEY, AOAI_ENDPOINT in .env first.")

    print(f"Creating Foundry IQ knowledge bases (api-version {API})...\n")
    for index_name, source, kb, description in TARGETS:
        print(f"• {kb}")
        ensure_semantic_config(index_name)
        create_knowledge_source(source, index_name, description)
        create_knowledge_base(kb, source, description)
        print()

    print("Done. MCP endpoints (the game reads these from .env):")
    for _, _, kb, _ in TARGETS:
        print(f"  {settings.search_endpoint}/knowledgebases/{kb}/mcp?api-version={API}")
    print("\nNext: set USE_LOCAL_FALLBACK=false in .env, then `python -m src.game_loop`.")


if __name__ == "__main__":
    main()
