"""
services/transcriber.py — Send audio segments to Groq's Whisper API for transcription.

Uses the same OpenAI-compatible client as the extractor (via services.client).
Config from .env: STT_MODEL (default "whisper-large-v3").
"""

import os
import re
import sys
import time

from openai import RateLimitError

from services.client import get_client

# Default speech-to-text model on Groq
_DEFAULT_STT = "whisper-large-v3"

# How many times to retry on 429 rate limits
_RATE_LIMIT_MAX_TRIES = 3


class TranscriptionError(Exception):
    """Raised when transcription fails after all retries."""
    pass


def _log(msg: str) -> None:
    """Print to stderr so stdout stays clean for piped output."""
    print(msg, file=sys.stderr)


def _parse_retry_after(error_text: str) -> float | None:
    """
    Extract the wait time from a Groq 429 error message.
    Example: "Please try again in 1m14.647s" or "in 6.5s".
    Returns seconds, or None if unparseable.
    """
    match = re.search(r"try again in\s+((?:\d+m)?[\d.]+s)", error_text, re.IGNORECASE)
    if not match:
        return None
    time_str = match.group(1)
    seconds = 0.0
    m = re.search(r"(\d+)m", time_str)
    if m:
        seconds += int(m.group(1)) * 60
    s = re.search(r"([\d.]+)s", time_str)
    if s:
        seconds += float(s.group(1))
    return seconds if seconds > 0 else None


def _classify_limit(error_text: str) -> str:
    """Return a friendly label for the type of rate limit hit."""
    lower = error_text.lower()
    if "per day" in lower or "daily" in lower or "tpd" in lower or "rpd" in lower:
        return "daily"
    if "per hour" in lower or "hourly" in lower:
        return "hourly"
    # Default: per-minute (most common for audio)
    return "per-minute"


def language_code(label: str) -> str | None:
    """
    Convert a UI-friendly language label to a Whisper language code.

    "Auto-detect" → None (let Whisper detect)
    "Hindi"       → "hi"
    "English"     → "en"
    "Hinglish"    → None (auto-detect works best for code-mixed speech)
    """
    mapping = {
        "hindi": "hi",
        "english": "en",
    }
    # Return None for auto-detect and hinglish
    return mapping.get(label.lower())


def transcribe(
    audio_paths: list[str],
    language: str | None = None,
    glossary: str | None = None,
) -> str:
    """
    Transcribe one or more audio segment files using Groq's Whisper API.

    Args:
        audio_paths: List of mp3 file paths (from audio.prepare_audio).
        language:    ISO 639-1 code ("hi", "en") or None for auto-detect.
        glossary:    Optional "prompt" hint with names/terms to help Whisper
                     spell them correctly (e.g. "CampusConnect, PostgreSQL").

    Returns:
        The full transcript text (all segments joined with a space).

    Raises:
        TranscriptionError: If all retries fail on any segment.
    """
    client = get_client()
    stt_model = os.getenv("STT_MODEL", _DEFAULT_STT)

    _log(f"[transcriber] Model    : {stt_model}")
    _log(f"[transcriber] Segments : {len(audio_paths)}")
    _log(f"[transcriber] Language : {language or 'auto-detect'}")

    texts = []              # transcribed text from each segment
    total_seconds = 0.0     # running total of audio duration

    for i, path in enumerate(audio_paths):
        _log(f"[transcriber] Transcribing segment {i + 1}/{len(audio_paths)}: {path}")

        # Get the file duration for logging (best effort)
        try:
            file_size = os.path.getsize(path)
            # Rough estimate: 32 kbps ≈ 4 KB/s
            total_seconds += file_size / 4000
        except OSError:
            pass

        # Retry loop for rate limits
        for attempt in range(_RATE_LIMIT_MAX_TRIES):
            try:
                with open(path, "rb") as audio_file:
                    # Build the kwargs; only include optional params if set
                    kwargs = {
                        "model": stt_model,
                        "file": audio_file,
                        "response_format": "text",
                    }
                    if language:
                        kwargs["language"] = language
                    if glossary:
                        kwargs["prompt"] = glossary

                    text = client.audio.transcriptions.create(**kwargs)

                texts.append(text.strip() if isinstance(text, str) else str(text).strip())
                break  # success — move to next segment

            except RateLimitError as exc:
                body = str(exc)
                limit_type = _classify_limit(body)

                # Daily/hourly limits — nothing we can do
                if limit_type in ("daily", "hourly"):
                    raise TranscriptionError(
                        f"Groq {limit_type} audio limit reached. "
                        f"Wait and try again later, or upgrade your plan."
                    )

                # Per-minute limit — wait and retry
                wait = _parse_retry_after(body)
                if wait is None:
                    wait = 15  # safe default

                if attempt < _RATE_LIMIT_MAX_TRIES - 1:
                    _log(f"[transcriber] {limit_type} rate limit (429). "
                         f"Waiting {wait + 1:.0f}s before retry "
                         f"{attempt + 2}/{_RATE_LIMIT_MAX_TRIES}...")
                    time.sleep(wait + 1)
                    continue

                # All retries exhausted
                raise TranscriptionError(
                    f"Groq {limit_type} audio rate limit — "
                    f"all {_RATE_LIMIT_MAX_TRIES} retries failed. "
                    f"Try again in a minute or two."
                )

    _log(f"[transcriber] Done. ~{total_seconds:.0f}s of audio processed.")

    # Join all segment texts with a space
    return " ".join(texts)
