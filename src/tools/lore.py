"""Foundry IQ grounding — the heart of the IQ integration.

PRIMARY PATH (Foundry IQ): a Foundry IQ knowledge base exposes an MCP endpoint. The Microsoft Agent
Framework consumes it directly via MCPStreamableHTTPTool, so the Mentor and Examiner agents get
cited, permission-aware retrieval with zero custom retrieval code.

FALLBACK PATH (local): if Foundry IQ isn't reachable yet (USE_LOCAL_FALLBACK=true), the same agents
use a local keyword retriever over the markdown in `curriculum/` and `worldpack/`. This keeps the
game fully demoable while you finish the Foundry IQ deployment. Swap back by setting the flag false.

Preview SDK note: MCPStreamableHTTPTool's exact constructor (esp. the `headers` kwarg) may differ by
version. If it errors, check https://learn.microsoft.com/agent-framework/ — this is the only file
to fix.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent_framework import ai_function

from ..citations import record_citation
from ..config import ROOT, KB_MCP_API_VERSION, kb_mcp_url, settings

# ─────────────────────────────────────────────────────────────────────────────
# PRIMARY: Foundry IQ via MCP
# ─────────────────────────────────────────────────────────────────────────────


def build_foundry_iq_tools():
    """Return @ai_function tools backed by the Foundry IQ knowledge bases' agentic /retrieve API.

    Returns {"curriculum": <tool>, "world": <tool>}. Each tool calls its knowledge base's
    `retrieve` endpoint — Foundry IQ plans subqueries, semantically reranks, and synthesizes a
    cited answer — then hands the agent the synthesized text plus the references to cite.

    We use the retrieve REST API rather than the KB's MCP session for the in-game path: under the
    nested multi-agent orchestration (GM -> mentor/examiner as tools), a shared streaming MCP
    session trips anyio cancel-scope errors. The KBs still expose MCP endpoints for external
    clients (Copilot/Claude/etc.) — see build_foundry_iq_mcp_tools below.
    """
    import httpx

    async def _retrieve(kb_name: str, ks_name: str, query: str, source_label: str) -> str:
        url = f"{settings.search_endpoint}/knowledgeBases/{kb_name}/retrieve?api-version={KB_MCP_API_VERSION}"
        # includeReferenceSourceData surfaces the knowledge source's configured sourceDataFields
        # (id/title/citation/source_file) in references[].sourceData. Without it, sourceData is null
        # and we can only cite the doc title. See create_foundry_iq_kbs.py for the field config.
        body = {
            "messages": [{"role": "user", "content": [{"type": "text", "text": query}]}],
            "knowledgeSourceParams": [
                {
                    "knowledgeSourceName": ks_name,
                    "kind": "searchIndex",
                    "includeReferences": True,
                    "includeReferenceSourceData": True,
                }
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                headers={"api-key": settings.search_query_key, "Content-Type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        answer = " ".join(
            c.get("text", "")
            for m in data.get("response", [])
            for c in m.get("content", [])
            if c.get("type") == "text"
        )
        references = []
        for ref in data.get("references", []):
            src = ref.get("sourceData") or {}
            # Prefer the real stored citation; fall back to a title-based label if absent.
            citation = src.get("citation") or f"{source_label} — {ref.get('title')}"
            references.append(
                {"ref_id": ref.get("id"), "title": ref.get("title"), "citation": citation}
            )
            # Record the exact citation for the Turn contract — authoritative, independent of how the
            # GM later phrases it in prose (it tends to shorten). See src/citations.py.
            record_citation(citation, title=ref.get("title"), source="foundry-iq")
        return json.dumps({"source": "foundry-iq", "answer": answer, "references": references})

    @ai_function
    async def curriculum_knowledge(query: str) -> str:
        """Retrieve cited NERDC curriculum content via Foundry IQ agentic retrieval.

        Args:
            query: the topic or question to ground, e.g. "environmental pollution".
        Returns:
            JSON with a synthesized answer and the NERDC references to cite.
        """
        return await _retrieve(
            settings.kb_curriculum,
            "jss1-basic-science-source",
            query,
            f"NERDC {settings.grade} {settings.subject}",
        )

    @ai_function
    async def world_lore(query: str) -> str:
        """Retrieve cited world/lore content from the Oke-Ola world pack via Foundry IQ."""
        return await _retrieve(
            settings.kb_world, "lumenor-lore-source", query, "Oke-Ola world pack"
        )

    return {"curriculum": curriculum_knowledge, "world": world_lore}


def build_foundry_iq_mcp_tools():
    """Foundry IQ via the KB MCP endpoints (the multi-client bonus path).

    Each KB auto-exposes an MCP endpoint, so any MCP client (Copilot, Claude, this game) can
    consume the same grounded knowledge. Kept available for the "one knowledge layer, many
    agents" demo; the in-game default is build_foundry_iq_tools (retrieve API) for reliability
    under nested orchestration.
    """
    from agent_framework import MCPStreamableHTTPTool

    headers = {"api-key": settings.search_query_key}
    curriculum = MCPStreamableHTTPTool(
        name="curriculum_knowledge", url=kb_mcp_url(settings.kb_curriculum), headers=headers
    )
    world = MCPStreamableHTTPTool(
        name="world_lore", url=kb_mcp_url(settings.kb_world), headers=headers
    )
    return {"curriculum": curriculum, "world": world}


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK: local cited retrieval (offline-safe)
# ─────────────────────────────────────────────────────────────────────────────

_CURRICULUM_DIR = ROOT / "curriculum"
_WORLD_DIR = ROOT / "worldpack"


def _chunk_markdown(path: Path) -> list[dict]:
    """Split a markdown file into sections by '## ' headings, capturing any 'Citation:' line."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"\n(?=## )", text)
    chunks = []
    for p in parts:
        heading = re.match(r"##\s+(.*)", p)
        if not heading:
            continue
        cite = re.search(r"\*\*Citation:\*\*\s*(.+)", p)
        chunks.append(
            {
                "title": heading.group(1).strip(),
                "text": p.strip(),
                "citation": (cite.group(1).strip() if cite else f"{path.stem} · {heading.group(1).strip()}"),
            }
        )
    return chunks


def _search(dirs: list[Path], query: str, k: int = 2) -> list[dict]:
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    scored = []
    for d in dirs:
        for f in d.glob("*.md"):
            for ch in _chunk_markdown(f):
                hay = ch["text"].lower()
                score = sum(hay.count(t) for t in terms)
                if score:
                    scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


@ai_function
def curriculum_knowledge(query: str) -> str:
    """Retrieve cited curriculum content for a topic (local fallback for Foundry IQ).

    Args:
        query: the topic or question to ground, e.g. "living and non-living things".
    Returns:
        JSON with retrieved passages and their citations.
    """
    hits = _search([_CURRICULUM_DIR], query)
    for ch in hits:
        record_citation(ch["citation"], title=ch.get("title"), source="local-fallback")
    return json.dumps(
        {"source": "local-fallback", "results": hits}
        if hits
        else {"source": "local-fallback", "results": [], "note": "no match — broaden the query"}
    )


@ai_function
def world_lore(query: str) -> str:
    """Retrieve cited world/lore content from the synthetic world pack (local fallback)."""
    hits = _search([_WORLD_DIR], query)
    for ch in hits:
        record_citation(ch["citation"], title=ch.get("title"), source="local-fallback")
    return json.dumps({"source": "local-fallback", "results": hits})


def build_lore_tools():
    """Return {"curriculum": tool, "world": tool}, choosing Foundry IQ or the local fallback."""
    if settings.use_local_fallback:
        return {"curriculum": curriculum_knowledge, "world": world_lore}
    try:
        return build_foundry_iq_tools()
    except Exception as exc:  # pragma: no cover - preview SDK safety net
        print(f"[lore] Foundry IQ MCP unavailable ({exc}); using local fallback. "
              f"Set USE_LOCAL_FALLBACK=true to silence this.")
        return {"curriculum": curriculum_knowledge, "world": world_lore}
