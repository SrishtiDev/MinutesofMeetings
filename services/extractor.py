"""
services/extractor.py — Calls the OpenAI API and returns validated Minutes.

Key Python concepts used here (for TypeScript developers):
  - pathlib.Path  : cross-platform file paths (like Node's path.join but nicer)
  - os.getenv     : reads environment variables (like process.env in Node)
  - json.loads    : parses a JSON string into a Python dict (like JSON.parse)
  - argparse      : standard library for building CLI argument parsers
"""

import json
import os
import argparse
from pathlib import Path  # Path objects are easier than string concatenation

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

# We import from the top-level models.py. Python resolves this relative to the
# project root when the module is run as  python -m services.extractor
from models import Minutes

# ---------------------------------------------------------------------------
# Configuration constants — change these to switch prompt versions or models
# ---------------------------------------------------------------------------

# __file__ is the absolute path of this file itself.
# .parent goes up one directory (to services/), .parent again goes to project root.
_PROJECT_ROOT = Path(__file__).parent.parent
PROMPT_FILE = _PROJECT_ROOT / "prompts" / "system_v1.txt"  # ← switch to v2 here

# Read the model name from the environment; fall back to gpt-4o-mini.
# We do NOT hardcode a default that costs more than necessary.
_DEFAULT_MODEL = "gpt-4o-mini"

# Maximum number of times we try to repair a bad JSON response before giving up.
_MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """Raised when the model keeps returning invalid JSON after all retries."""
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_system_prompt() -> str:
    """Read the system prompt text file from disk."""
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")
    return PROMPT_FILE.read_text(encoding="utf-8")


def _build_user_message(transcript: str, meeting_date: str, output_language: str) -> str:
    """
    Compose the user-turn message that the model will see alongside the system prompt.
    Keeping this in one place makes it easy to tweak the format later.
    """
    return (
        f"meeting_date: {meeting_date}\n"
        f"output_language: {output_language}\n\n"
        f"Transcript:\n---\n{transcript}\n---"
    )


def _log_token_usage(response) -> None:
    """Print token counts so we can track API cost per call."""
    usage = response.usage
    # These attribute names come from the OpenAI API response object.
    print(
        f"[token usage]  prompt={usage.prompt_tokens} | "
        f"completion={usage.completion_tokens} | "
        f"total={usage.total_tokens}"
    )


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def extract_minutes(
    transcript: str,
    meeting_date: str,
    output_language: str = "English",
    model: str | None = None,
) -> Minutes:
    """
    Send the transcript to OpenAI and return a validated Minutes object.

    Args:
        transcript:      The raw meeting transcript text.
        meeting_date:    Date of the meeting in YYYY-MM-DD format.
        output_language: Language for the output. Default is "English".
                         Pass "same as meeting" to keep the source language.
        model:           Override the OpenAI model name. If None, uses the
                         OPENAI_MODEL env variable or falls back to gpt-4o-mini.

    Returns:
        A validated Minutes instance.

    Raises:
        ExtractionError: If JSON parsing or Pydantic validation fails after
                         all retries.
        ValueError:      If OPENAI_API_KEY is not set.
    """
    # load_dotenv reads the .env file and puts its values into os.environ.
    # It does nothing if the variables are already set (safe to call multiple times).
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key.strip() == "your-key-here":
        raise ValueError(
            "OPENAI_API_KEY is not set or is still the placeholder value. "
            "Add your real key to the .env file. Never hardcode it in source code."
        )

    # Resolve the model name: caller arg > env variable > hardcoded default
    resolved_model = model or os.getenv("OPENAI_MODEL", _DEFAULT_MODEL)

    # Create the OpenAI client. It automatically picks up OPENAI_API_KEY from
    # the environment — we never pass the key as a string in our code.
    client = OpenAI()

    system_prompt = _load_system_prompt()
    user_message = _build_user_message(transcript, meeting_date, output_language)

    # messages is a list of dicts, each with "role" and "content".
    # This is the "chat history" format the API expects.
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    last_error: str = ""      # Last validation error message, used in repair prompts
    last_bad_json: str = ""   # Last raw response from the model that failed validation

    # We attempt up to (1 + _MAX_RETRIES) calls total.
    # range(n) in Python is 0, 1, 2, … n-1 — so range(3) gives 3 iterations.
    for attempt in range(1 + _MAX_RETRIES):
        if attempt > 0:
            # On a retry, append the model's bad answer and a repair instruction
            # to the conversation. The model sees the full history and self-corrects.
            print(f"[extractor] Retry {attempt}/{_MAX_RETRIES} — sending repair prompt...")
            messages.append({"role": "assistant", "content": last_bad_json})
            messages.append({
                "role": "user",
                "content": (
                    f"Your previous response failed validation with this error:\n"
                    f"{last_error}\n\n"
                    "Please return ONLY valid JSON that strictly matches the schema. "
                    "No extra text, no markdown fences, no explanations."
                ),
            })

        print(f"[extractor] Calling {resolved_model} (attempt {attempt + 1})...")

        response = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=0,               # 0 = deterministic, no creativity needed
            response_format={"type": "json_object"},  # forces JSON-only output
        )

        _log_token_usage(response)

        raw_json: str = response.choices[0].message.content

        try:
            # model_validate_json is a Pydantic v2 method that parses a JSON
            # string and validates it against the model's schema in one step.
            minutes = Minutes.model_validate_json(raw_json)
            print("[extractor] Validation successful.")
            return minutes

        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            last_bad_json = raw_json
            print(f"[extractor] Validation failed on attempt {attempt + 1}: {last_error}")

    # If we reach here, all attempts failed.
    raise ExtractionError(
        f"Failed to extract valid Minutes after {1 + _MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
# In Python, `if __name__ == "__main__"` is the equivalent of checking whether
# this file was invoked directly (not imported by another module).
# Running `python -m services.extractor` sets __name__ to "__main__".

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract structured meeting minutes from a transcript file."
    )
    parser.add_argument(
        "transcript_file",
        type=str,
        help="Path to a plain-text transcript file (e.g. data/hinglish_01.txt)",
    )
    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Meeting date used to resolve relative dates (e.g. 2026-10-20)",
    )
    parser.add_argument(
        "--language",
        default="English",
        metavar="LANG",
        help='Output language. Default: "English". Use "same as meeting" to keep source language.',
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="OpenAI model name override (e.g. gpt-4o). Defaults to OPENAI_MODEL env var.",
    )

    args = parser.parse_args()

    # Read the transcript file
    transcript_path = Path(args.transcript_file)
    if not transcript_path.exists():
        print(f"Error: file not found — {transcript_path}")
        raise SystemExit(1)  # SystemExit(1) is the Python equivalent of process.exit(1)

    transcript_text = transcript_path.read_text(encoding="utf-8")

    # Call the extractor
    minutes = extract_minutes(
        transcript=transcript_text,
        meeting_date=args.date,
        output_language=args.language,
        model=args.model,
    )

    # model_dump() converts the Pydantic model to a plain Python dict.
    # json.dumps with indent=2 pretty-prints it, like JSON.stringify(obj, null, 2).
    print(json.dumps(minutes.model_dump(), indent=2, ensure_ascii=False))
