"""
services/extractor.py — Calls an OpenAI-compatible LLM API and returns validated Minutes.

Provider is configured via .env:
  GROQ_API_KEY       – your Groq API key (also checked as LLM_API_KEY / OPENAI_API_KEY)
  LLM_BASE_URL       – default "https://api.groq.com/openai/v1"
  LLM_MODEL          – default "openai/gpt-oss-120b"
  LLM_FALLBACK_MODEL – model to try if rate limits exhaust retries (default "llama-3.3-70b-versatile")
  STT_MODEL          – default "whisper-large-v3" (for transcriber.py)
"""

import json
import os
import re
import sys
import time
import argparse
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APIStatusError
from pydantic import ValidationError

from models import Minutes
from services.config import get_setting

# ---------------------------------------------------------------------------
# Paths and defaults
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent

# Default prompt is v3; override with --prompt flag on the CLI.
_DEFAULT_PROMPT = _PROJECT_ROOT / "prompts" / "system_v4.txt"

_DEFAULT_BASE_URL      = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL         = "openai/gpt-oss-120b"
_DEFAULT_FALLBACK      = "llama-3.3-70b-versatile"
_DEFAULT_STT           = "whisper-large-v3"  # used by transcriber.py

_MAX_RETRIES           = 2   # extra repair attempts after the first LLM call
_RATE_LIMIT_MAX_TRIES  = 3   # how many times to retry on per-minute 429


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class ExtractionError(Exception):
    """Raised when the model returns invalid JSON after all retries."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_system_prompt(prompt_file: Path) -> str:
    """Read the system prompt from disk."""
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    return prompt_file.read_text(encoding="utf-8")


def build_date_reference(meeting_date: str) -> str:
    """
    Build a DATE REFERENCE block with unambiguous labels.

    Labels used:
      - "This coming <weekday>" = the nearest upcoming <weekday> after meeting_date.
      - "Next week <weekday>"   = that weekday in the calendar week AFTER meeting_date's week.
      - "Friday of next week"   = end of next week (never labelled "next Friday").
    """
    d = date.fromisoformat(meeting_date)
    day_name = d.strftime("%A")

    # Helper: ISO string for meeting_date + offset days
    def iso(offset: int) -> str:
        return (d + timedelta(days=offset)).isoformat()

    # Return the nearest future date landing on a given weekday (0=Mon … 6=Sun)
    def next_weekday(target_wd: int) -> date:
        days_ahead = (target_wd - d.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # "next Monday" when today IS Monday → skip to next week
        return d + timedelta(days=days_ahead)

    # ── "This coming <weekday>" lines: nearest upcoming occurrence ────────
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"]
    coming_lines = []
    for wd_idx, wd_name in enumerate(weekday_names):
        dt = next_weekday(wd_idx)
        # Add Hindi/Hinglish aliases for the most-used days
        if wd_name == "Friday":
            label = (f"This coming Friday "
                     f"(agle Friday / next Friday / is Friday / end of this week) = "
                     f"{dt.isoformat()}")
        elif wd_name == "Monday":
            label = (f"This coming Monday "
                     f"(agle Monday / next Monday) = {dt.isoformat()}")
        elif wd_name in ("Wednesday", "Thursday"):
            label = (f"This coming {wd_name} "
                     f"(agle {wd_name} / next {wd_name}) = {dt.isoformat()}")
        else:
            label = f"This coming {wd_name} = {dt.isoformat()}"
        coming_lines.append(label)

    # ── "Next week" list: Mon–Fri of the ISO week after meeting_date's week ──
    # ISO weekday: Monday=1. Find next week's Monday.
    days_to_next_monday = 7 - d.weekday()  # always jumps to the FOLLOWING Monday
    next_mon = d + timedelta(days=days_to_next_monday)
    next_week_entries = []
    for offset in range(5):  # Mon–Fri
        nw_date = next_mon + timedelta(days=offset)
        next_week_entries.append(f"{nw_date.strftime('%A')} = {nw_date.isoformat()}")
    next_week_line = "Next week: " + ", ".join(next_week_entries)

    # Friday of next week (never called "next Friday")
    next_week_friday = next_mon + timedelta(days=4)

    return (
        f"DATE REFERENCE\n"
        f"Meeting date: {day_name}, {meeting_date}\n"
        f"Tomorrow (kal) = {iso(1)}, Day after tomorrow (parso) = {iso(2)}\n"
        + "\n".join(coming_lines) + "\n"
        + next_week_line + "\n"
        + f"Friday of next week (end of next week / agle hafte ke end tak) = "
          f"{next_week_friday.isoformat()}"
    )


def _build_user_message(
    transcript: str,
    meeting_date: str,
    output_language: str,
) -> str:
    """
    Compose the full user-turn message sent to the model.
    Includes the DATE REFERENCE block so the model never calculates dates.
    """
    date_ref = build_date_reference(meeting_date)
    return (
        f"meeting_date: {meeting_date}\n"
        f"output_language: {output_language}\n\n"
        f"{date_ref}\n\n"
        f"Transcript:\n---\n{transcript}\n---"
    )


def _log(msg: str) -> None:
    """Print a log line to stderr (keeps stdout clean for JSON output)."""
    print(msg, file=sys.stderr)


def _log_token_usage(response) -> None:
    """Print token counts to stderr so we can track API cost."""
    u = response.usage
    _log(
        f"[token usage]  prompt={u.prompt_tokens} | "
        f"completion={u.completion_tokens} | total={u.total_tokens}"
    )


def _parse_retry_after(error_text: str) -> float | None:
    """
    Try to extract a wait time from a Groq 429 error message.
    Typical format: "Please try again in 1m14.647s" or "... in 6.5s".
    Returns seconds (float), or None if we can't parse it.
    """
    # Look for patterns like "in 1m14.647s" or "in 6.5s"
    match = re.search(r"try again in\s+((?:\d+m)?[\d.]+s)", error_text, re.IGNORECASE)
    if not match:
        return None
    time_str = match.group(1)
    seconds = 0.0
    # Parse optional minutes part (e.g. "1m")
    m_match = re.search(r"(\d+)m", time_str)
    if m_match:
        seconds += int(m_match.group(1)) * 60
    # Parse seconds part (e.g. "14.647s")
    s_match = re.search(r"([\d.]+)s", time_str)
    if s_match:
        seconds += float(s_match.group(1))
    return seconds if seconds > 0 else None


def _is_daily_limit(error_text: str) -> bool:
    """Return True if the 429 error is a daily limit (TPD/RPD), not per-minute."""
    lower = error_text.lower()
    # Groq labels: TPD = tokens per day, RPD = requests per day
    return ("per day" in lower or "tpd" in lower or "rpd" in lower
            or "daily" in lower)


def _is_per_minute_limit(error_text: str) -> bool:
    """Return True if the 429 is a per-minute limit (TPM/RPM/OTPM)."""
    lower = error_text.lower()
    return ("per minute" in lower or "tpm" in lower or "rpm" in lower
            or "otpm" in lower)


def _call_with_rate_limit_retry(
    client: OpenAI, *, use_json_mode: bool, **kwargs
) -> object:
    """
    Wrap client.chat.completions.create with rate-limit retry logic.

    On a per-minute 429: read the "try again in X s" value from the error,
    wait that long + 1s, and retry up to _RATE_LIMIT_MAX_TRIES times.

    On a daily 429: print a friendly message and re-raise immediately.

    If all per-minute retries are exhausted, try once with LLM_FALLBACK_MODEL.
    """
    if use_json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    original_model = kwargs.get("model", "")

    for attempt in range(_RATE_LIMIT_MAX_TRIES):
        try:
            return client.chat.completions.create(**kwargs)

        except RateLimitError as exc:
            body = str(exc)

            # ── Daily limit → give up immediately ──────────────────────
            if _is_daily_limit(body):
                _log("\n⚠️  Daily token/request limit reached (TPD/RPD). "
                     "Wait until midnight UTC or upgrade your plan.\n")
                raise

            # ── Per-minute limit → wait and retry ──────────────────────
            wait = _parse_retry_after(body)
            if wait is None:
                wait = 15  # safe default if we can't parse

            limit_type = "per-minute"
            if _is_per_minute_limit(body):
                limit_type = "per-minute (TPM/RPM)"

            if attempt < _RATE_LIMIT_MAX_TRIES - 1:
                _log(f"[extractor] {limit_type} rate limit hit (429). "
                     f"Waiting {wait + 1:.0f}s before retry "
                     f"{attempt + 2}/{_RATE_LIMIT_MAX_TRIES}...")
                time.sleep(wait + 1)
                continue

            # All retries exhausted — try fallback model once
            fallback = os.getenv("LLM_FALLBACK_MODEL", _DEFAULT_FALLBACK)
            if fallback and fallback != original_model:
                _log(f"[extractor] {limit_type} retries exhausted for {original_model}. "
                     f"Switching to fallback model: {fallback}")
                kwargs["model"] = fallback
                try:
                    return client.chat.completions.create(**kwargs)
                except Exception:
                    _log(f"[extractor] Fallback model {fallback} also failed.")
                    raise exc  # re-raise the original 429

            raise  # no fallback available

        except APIStatusError as exc:
            # Re-raise 400 "json_object not supported" so caller handles it.
            if exc.status_code == 400 and use_json_mode and "json" in str(exc).lower():
                raise
            raise


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def extract_minutes(
    transcript: str,
    meeting_date: str,
    output_language: str = "English",
    model: str | None = None,
    prompt_file: Path | None = None,
) -> Minutes:
    """
    Send the transcript to an OpenAI-compatible LLM and return a Minutes object.

    Args:
        transcript:      Raw meeting transcript text.
        meeting_date:    Date in YYYY-MM-DD format.
        output_language: Language for output fields. Default "English".
        model:           Override the LLM model name (else uses LLM_MODEL env var).
        prompt_file:     Override the system prompt file (else uses _DEFAULT_PROMPT).

    Returns:
        Validated Minutes instance.

    Raises:
        ExtractionError: If all retries fail.
        ValueError:      If no API key is set.
    """
    # API key: try LLM_API_KEY → GROQ_API_KEY → OPENAI_API_KEY
    api_key = get_setting("LLM_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")
    if not api_key or api_key.strip() in ("", "your-key-here", "your-groq-api-key-here"):
        raise ValueError(
            "No LLM API key found. Set GROQ_API_KEY in your .env file."
        )

    base_url       = get_setting("LLM_BASE_URL", default=_DEFAULT_BASE_URL)
    resolved_model = model or get_setting("LLM_MODEL", default=_DEFAULT_MODEL)
    resolved_prompt = prompt_file or _DEFAULT_PROMPT

    _log(f"[extractor] Prompt file      : {resolved_prompt.name}")
    _log(f"[extractor] Provider base URL: {base_url}")
    _log(f"[extractor] Model            : {resolved_model}")

    client = OpenAI(api_key=api_key, base_url=base_url)

    system_prompt = _load_system_prompt(resolved_prompt)
    user_message  = _build_user_message(transcript, meeting_date, output_language)

    # The conversation history we send to the model.
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]

    use_json_mode = True   # try json_object mode first; fall back if rejected
    last_error    = ""     # last validation error (used in repair prompts)
    last_bad_json = ""     # last raw response that failed

    for attempt in range(1 + _MAX_RETRIES):
        if attempt > 0:
            # Append the bad response and a repair instruction so the model
            # can see what it got wrong and self-correct.
            _log(f"[extractor] Retry {attempt}/{_MAX_RETRIES} — sending repair prompt...")
            messages.append({"role": "assistant", "content": last_bad_json})
            messages.append({
                "role": "user",
                "content": (
                    f"Your previous response failed validation:\n{last_error}\n\n"
                    "Return ONLY valid JSON matching the schema. "
                    "No markdown, no extra text."
                ),
            })

        _log(f"[extractor] Calling {resolved_model} (attempt {attempt + 1})...")

        try:
            response = _call_with_rate_limit_retry(
                client,
                use_json_mode=use_json_mode,
                model=resolved_model,
                messages=messages,
                temperature=0,  # deterministic output
            )
        except APIStatusError as exc:
            # Model rejected json_object mode → retry without it
            if exc.status_code == 400 and use_json_mode and "json" in str(exc).lower():
                _log("[extractor] json_object mode rejected — retrying without it.")
                use_json_mode = False
                response = _call_with_rate_limit_retry(
                    client,
                    use_json_mode=False,
                    model=resolved_model,
                    messages=messages,
                    temperature=0,
                )
            else:
                raise

        _log_token_usage(response)

        # Log which model actually answered (may differ if fallback was used)
        actual_model = response.model or resolved_model
        if actual_model != resolved_model:
            _log(f"[extractor] Response from fallback model: {actual_model}")

        raw_json: str = response.choices[0].message.content

        try:
            minutes = Minutes.model_validate_json(raw_json)
            minutes.action_items = merge_duplicate_actions(minutes.action_items)
            _log("[extractor] Validation successful.")
            return minutes

        except (json.JSONDecodeError, ValidationError) as exc:
            last_error    = str(exc)
            last_bad_json = raw_json
            _log(f"[extractor] Validation failed (attempt {attempt + 1}): {last_error}")

    raise ExtractionError(
        f"Failed after {1 + _MAX_RETRIES} attempts. Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract structured meeting minutes from a transcript file."
    )
    parser.add_argument(
        "transcript_file",
        help="Path to a plain-text transcript file (e.g. data/hinglish_01.txt)",
    )
    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Meeting date (e.g. 2026-10-20)",
    )
    parser.add_argument(
        "--language",
        default="English",
        metavar="LANG",
        help='Output language. Default: "English".',
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="LLM model override. Defaults to LLM_MODEL env var.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        metavar="FILE",
        help="System prompt file. Default: prompts/system_v4.txt",
    )

    args = parser.parse_args()

    transcript_path = Path(args.transcript_file)
    if not transcript_path.exists():
        print(f"Error: file not found — {transcript_path}", file=sys.stderr)
        raise SystemExit(1)

    # Resolve prompt path: CLI arg → default
    prompt_path = Path(args.prompt) if args.prompt else _DEFAULT_PROMPT

    transcript_text = transcript_path.read_text(encoding="utf-8")

    minutes = extract_minutes(
        transcript=transcript_text,
        meeting_date=args.date,
        output_language=args.language,
        model=args.model,
        prompt_file=prompt_path,
    )

    # Print the JSON to stdout (clean, no log noise).
    print(json.dumps(minutes.model_dump(), indent=2, ensure_ascii=False))
