"""Seed Foundry IQ — index the world pack + NERDC curriculum into Azure AI Search.

This prepares the data behind your two Foundry IQ knowledge bases:
  - curriculum  (curriculum/*.md)   -> index `jss1-basic-science-index`
  - world lore  (worldpack/*.md)    -> index `lumenor-lore-index`

WHAT THIS SCRIPT DOES (the reliable part):
  Chunks each markdown file by '## ' section, embeds each chunk with Azure OpenAI
  (text-embedding-3-large), and uploads to an Azure AI Search index with a vector field.

WHAT YOU FINISH IN THE PORTAL / EP1 NOTEBOOK (preview API, ~5 min):
  Create a Foundry IQ *knowledge source* over each index, then a *knowledge base*. The iq-series
  Episode 1 cookbook has the exact cells; or use the Foundry IQ portal. Name the knowledge bases to
  match your .env (KB_CURRICULUM, KB_WORLD) so the game's MCP endpoints resolve.

Run:  python scripts/seed_foundry_iq.py
Prereqs:  filled .env (SEARCH_ENDPOINT, SEARCH_ADMIN_KEY, AOAI_ENDPOINT, AOAI_EMBEDDING_DEPLOYMENT) + az login
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402

CURRICULUM_DIR = ROOT / "curriculum"
WORLD_DIR = ROOT / "worldpack"


def chunk_markdown(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    chunks = []
    for part in re.split(r"\n(?=## )", text):
        h = re.match(r"##\s+(.*)", part)
        if not h:
            continue
        cite = re.search(r"\*\*Citation:\*\*\s*(.+)", part)
        chunks.append(
            {
                "id": re.sub(r"[^a-zA-Z0-9_-]", "-", f"{path.stem}-{h.group(1)}")[:120],
                "title": h.group(1).strip(),
                "content": part.strip(),
                "citation": cite.group(1).strip() if cite else f"{path.stem} · {h.group(1).strip()}",
                "source_file": path.name,
            }
        )
    return chunks


def gather(dirs: list[Path]) -> list[dict]:
    docs: list[dict] = []
    for d in dirs:
        for f in sorted(d.glob("*.md")):
            docs.extend(chunk_markdown(f))
    return docs


def embed(texts: list[str]) -> list[list[float]]:
    """Embed chunks with Azure OpenAI text-embedding-3-large."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_endpoint=settings.aoai_endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-10-21",
    )
    resp = client.embeddings.create(model=settings.embedding_deployment, input=texts)
    return [d.embedding for d in resp.data]


def upload(index_name: str, docs: list[dict]) -> None:
    """Create (if needed) a vector index and upload documents."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    cred = AzureKeyCredential(settings.search_admin_key)
    index_client = SearchIndexClient(settings.search_endpoint, cred)

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="citation", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="source_file", type=SearchFieldDataType.String, filterable=True),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=3072,  # text-embedding-3-large
            vector_search_profile_name="default",
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name="default", algorithm_configuration_name="hnsw")],
    )
    index_client.create_or_update_index(
        SearchIndex(name=index_name, fields=fields, vector_search=vector_search)
    )

    vectors = embed([d["content"] for d in docs])
    for d, v in zip(docs, vectors):
        d["content_vector"] = v

    search_client = SearchClient(settings.search_endpoint, index_name, cred)
    search_client.upload_documents(documents=docs)
    print(f"  ✓ indexed {len(docs)} chunks into '{index_name}'")


def main() -> None:
    if not settings.search_admin_key or not settings.aoai_endpoint:
        sys.exit("Fill SEARCH_ENDPOINT, SEARCH_ADMIN_KEY, AOAI_ENDPOINT in .env first.")

    print("Seeding Foundry IQ source indexes...")
    print("• curriculum")
    upload("jss1-basic-science-index", gather([CURRICULUM_DIR]))
    print("• world lore")
    upload("lumenor-lore-index", gather([WORLD_DIR]))

    print(
        "\nNext (preview API, ~5 min — use the iq-series Ep1 notebook or the Foundry IQ portal):\n"
        "  1. Create a knowledge source over each index above.\n"
        f"  2. Create a knowledge base named '{settings.kb_curriculum}' (curriculum) and "
        f"'{settings.kb_world}' (world).\n"
        "  3. Confirm each KB exposes its MCP endpoint. The game reads them from .env.\n"
        "Done — run `python -m src.game_loop`."
    )


if __name__ == "__main__":
    main()
