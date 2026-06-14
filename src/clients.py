"""Chat client factory for the Microsoft Agent Framework.

Uses the Foundry project client (AzureAIAgentClient) with DefaultAzureCredential, matching the
challenge's recommended .env (AZURE_AI_PROJECT_ENDPOINT + AZURE_AI_MODEL_DEPLOYMENT).
Run `az login` once so DefaultAzureCredential can authenticate.

Preview SDK note: if the import path differs, check `pip show agent-framework` and
https://learn.microsoft.com/agent-framework/ — this is the only file that builds the client.
"""
from __future__ import annotations

from azure.identity import DefaultAzureCredential

from .config import settings


def get_chat_client():
    """Return a Foundry-backed chat client for all agents to share."""
    from agent_framework.azure import AzureAIAgentClient

    return AzureAIAgentClient(
        project_endpoint=settings.project_endpoint,
        model_deployment_name=settings.model_deployment,
        credential=DefaultAzureCredential(),
    )
