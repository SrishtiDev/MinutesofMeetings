"""
services/client.py — Shared OpenAI-compatible client factory.

Every service (extractor, transcriber) needs the same client setup:
  API key:  LLM_API_KEY → GROQ_API_KEY → OPENAI_API_KEY
  Base URL: LLM_BASE_URL (default Groq)

This module provides a single function so we don't repeat that logic.
"""

from openai import OpenAI

from services.config import get_setting

_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


def get_client() -> OpenAI:
    """
    Create and return an OpenAI client configured from .env.

    Raises ValueError if no API key is found.
    """
    # Try keys in priority order
    api_key = get_setting("LLM_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")
    if not api_key or api_key.strip() in ("", "your-key-here", "your-groq-api-key-here"):
        raise ValueError(
            "No API key found. Set GROQ_API_KEY in your .env file."
        )

    base_url = get_setting("LLM_BASE_URL", default=_DEFAULT_BASE_URL)
    return OpenAI(api_key=api_key, base_url=base_url)
