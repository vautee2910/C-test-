#!/usr/bin/env python3
"""Minimal env-driven client for the remote LLM over an OpenAI-compatible
OpenWebUI gateway.

Configuration is read from the environment (loaded from a gitignored `.env`):

    OI_API_KEY    API key for the gateway.
    OI_BASE_URL   Gateway base URL. Normalised so it ends with /v1.
    OI_MODEL      Model identifier to target.

No secrets are hardcoded. Run directly for a one-line "ping" smoke test:

    python scripts/llm_client.py
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI


def _normalise_base_url(url: str) -> str:
    """Ensure the OpenAI base_url ends with a single `/v1` path segment."""
    url = url.rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def get_client() -> tuple[OpenAI, str]:
    """Build an OpenAI client pointed at the OpenWebUI gateway.

    Returns the client and the configured model id.
    """
    load_dotenv()

    api_key = os.environ.get("OI_API_KEY")
    base_url = os.environ.get("OI_BASE_URL")
    model = os.environ.get("OI_MODEL")

    missing = [
        name
        for name, value in (
            ("OI_API_KEY", api_key),
            ("OI_BASE_URL", base_url),
            ("OI_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Set them in a .env file (see .env.example)."
        )

    client = OpenAI(api_key=api_key, base_url=_normalise_base_url(base_url))
    return client, model


def chat(prompt: str) -> str:
    """Send a single user message and return the model's reply text."""
    client, model = get_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


def main() -> int:
    load_dotenv()
    prompt = " ".join(sys.argv[1:]) or "ping"
    print(f"==> Model: {os.environ.get('OI_MODEL', '(unset)')}")
    print(f"==> Prompt: {prompt!r}")
    reply = chat(prompt)
    print("==> Reply:")
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
