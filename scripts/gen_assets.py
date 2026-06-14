"""Generate original art assets for the web client via Azure OpenAI image models (option B).

The web client (`frontend/index.html`) ships with hand-authored inline SVG art and will use a PNG
automatically if one exists at `frontend/assets/portraits/<key>.png` or `.../scenes/<key>.png`. This
script produces those PNGs so you can upgrade from the SVG look without touching any code.

All prompts describe ORIGINAL, FICTIONAL characters and a generic representative Nigerian community —
consistent with the project's synthetic-frame rule. No real people or places.

Prerequisites
-------------
1. Deploy an image model in your Azure OpenAI resource (e.g. `gpt-image-1` or `dall-e-3`).
2. Set in `.env` (names only; never commit values):
     AOAI_ENDPOINT             = https://<your-openai>.openai.azure.com
     AOAI_IMAGE_DEPLOYMENT     = <your image deployment name>   (e.g. gpt-image-1)
     AOAI_API_KEY              = <key>        # optional; if unset, DefaultAzureCredential is used
3. `pip install openai` (already in requirements) and `az login` (if using AAD).

Usage
-----
    python scripts/gen_assets.py                 # generate any missing assets
    python scripts/gen_assets.py --force         # regenerate all
    python scripts/gen_assets.py --only adaeze market   # just these keys
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import ROOT, settings  # noqa: E402

ASSETS = ROOT / "frontend" / "assets"
API_VERSION = "2024-10-21"

# Shared style anchor for a coherent storybook look across every asset.
STYLE = (
    "warm flat vector storybook illustration, soft earthy palette (terracotta, ochre, green, cream), "
    "gentle lighting, friendly and age-appropriate for children, clean simple shapes, no text, "
    "no watermark, no real-person likeness — an original fictional design"
)

# Keys MUST match the SVG keys in frontend/index.html (portraitSVG / sceneSVG).
PORTRAITS = {
    "narrator": "a warm friendly storyteller narrator, glowing lantern motif, neutral kind face, head-and-shoulders portrait",
    "adaeze": "Teacher Adaeze, a kind Nigerian woman science teacher in her 30s wearing glasses and a teal blouse, holding a book, head-and-shoulders portrait",
    "nkechi": "Mama Nkechi, a cheerful Nigerian market woman wearing a colourful headwrap (gele) and orange blouse, head-and-shoulders portrait",
    "sule": "Baba Sule, a wise elderly Nigerian farmer with a short grey beard wearing a traditional cap (fila), head-and-shoulders portrait",
    "bisi": "Nurse Bisi, a caring Nigerian community nurse wearing a white nurse cap with a small red cross and a blue uniform, head-and-shoulders portrait",
    "tunde": "Tunde, a happy Nigerian boy about 11 years old in a green t-shirt, the learner's friend, head-and-shoulders portrait",
}
SCENES = {
    "home": "a modest Nigerian family home and compound at warm daytime, simple house with a pitched roof",
    "market": "a lively open-air Nigerian community market with colourful stall umbrellas and produce",
    "farm": "a small Nigerian family farm with neat crop rows under a bright sky",
    "kitchen": "a simple Nigerian home kitchen with a cooking pot over a small fire, warm interior light",
    "night": "a Nigerian family compound at night, a glowing lamp and a house silhouette under a deep blue sky",
    "stream": "a clear stream with green banks near a Nigerian village, daytime",
    "sky": "a calm starry night sky over a Nigerian community with a bright moon",
    "health": "a small friendly Nigerian community health post building with a red cross sign, daytime",
}


def _client():
    from openai import AzureOpenAI

    endpoint = settings.aoai_endpoint or os.getenv("AOAI_ENDPOINT", "")
    if not endpoint:
        sys.exit("AOAI_ENDPOINT is not set — see this script's docstring.")
    api_key = os.getenv("AOAI_API_KEY")
    if api_key:
        return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=API_VERSION)
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    return AzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=provider, api_version=API_VERSION)


def _save_png(b64: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(b64))


def _generate(client, deployment: str, prompt: str, size: str) -> str:
    """Return base64 PNG for one prompt (handles b64 or URL responses)."""
    resp = client.images.generate(model=deployment, prompt=f"{prompt}. {STYLE}.", size=size, n=1)
    item = resp.data[0]
    if getattr(item, "b64_json", None):
        return item.b64_json
    import urllib.request  # dall-e-3 may return a URL instead of b64

    with urllib.request.urlopen(item.url) as r:  # noqa: S310 - trusted Azure URL
        return base64.b64encode(r.read()).decode()


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate web-client art via Azure OpenAI images.")
    ap.add_argument("--force", action="store_true", help="regenerate even if the PNG exists")
    ap.add_argument("--only", nargs="*", default=None, help="only these keys (portrait or scene)")
    args = ap.parse_args()

    deployment = os.getenv("AOAI_IMAGE_DEPLOYMENT", "")
    if not deployment:
        sys.exit("AOAI_IMAGE_DEPLOYMENT is not set — deploy an image model and set it. See docstring.")
    client = _client()

    jobs = [("portraits", k, p, "1024x1024") for k, p in PORTRAITS.items()]
    jobs += [("scenes", k, p, "1536x1024") for k, p in SCENES.items()]
    if args.only:
        jobs = [j for j in jobs if j[1] in set(args.only)]

    made = skipped = failed = 0
    for folder, key, prompt, size in jobs:
        out = ASSETS / folder / f"{key}.png"
        if out.exists() and not args.force:
            print(f"  skip   {folder}/{key}.png (exists)"); skipped += 1; continue
        try:
            _save_png(_generate(client, deployment, prompt, size), out)
            print(f"  wrote  {folder}/{key}.png"); made += 1
        except Exception as exc:  # noqa: BLE001 - report and continue so one failure doesn't abort the batch
            print(f"  FAIL   {folder}/{key}.png — {type(exc).__name__}: {exc}"); failed += 1

    print(f"\nDone: {made} written, {skipped} skipped, {failed} failed. Reload the web client to see them.")


if __name__ == "__main__":
    main()
