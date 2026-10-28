"""
services/pipeline.py — End-to-end pipeline: audio/text → transcript → Minutes.

Two routes:
  1. Audio: audio.py (convert + split) → transcriber.py (Whisper) → extractor.py
  2. Text:  use the text as-is → extractor.py

This module does NOT know about Streamlit or any UI framework.

CLI usage:
  python -m services.pipeline --audio meeting.mp3 --date 2026-10-20
  python -m services.pipeline --transcript-file data/english_01.txt --date 2026-10-20
"""

import json
import sys
import argparse
from pathlib import Path

from models import Minutes
from services.audio import prepare_audio, cleanup, AudioError
from services.transcriber import transcribe, language_code, TranscriptionError
from services.extractor import extract_minutes


def _log(msg: str) -> None:
    """Print to stderr so stdout stays clean for JSON."""
    print(msg, file=sys.stderr)


def process_meeting(
    audio_path: str | None = None,
    transcript_text: str | None = None,
    meeting_date: str = "",
    meeting_language: str = "Auto-detect",
    output_language: str = "English",
    glossary: str | None = None,
) -> tuple[Minutes, str]:
    """
    Run the full pipeline: audio or text → transcript → structured minutes.

    Exactly one of audio_path or transcript_text must be given.

    Args:
        audio_path:       Path to an audio/video file (mp3, wav, m4a, mp4, …).
        transcript_text:  Raw transcript text (use this instead of audio).
        meeting_date:     ISO date string, e.g. "2026-10-20".
        meeting_language: Language of the meeting for Whisper (e.g. "Hindi",
                          "English", "Auto-detect"). Ignored for text route.
        output_language:  Language for the output fields (default "English").
        glossary:         Optional comma-separated names/terms to help Whisper
                          spell them correctly.

    Returns:
        (minutes, transcript) — the validated Minutes object and the transcript
        text (either from Whisper or as provided).

    Raises:
        ValueError:          If both or neither audio_path/transcript_text given.
        AudioError:          If audio validation/conversion fails.
        TranscriptionError:  If Whisper API fails.
        ExtractionError:     If LLM extraction fails.
    """
    # ── Validate inputs ──────────────────────────────────────────────────
    has_audio = audio_path is not None
    has_text  = transcript_text is not None

    if has_audio == has_text:
        raise ValueError(
            "Provide exactly one of audio_path or transcript_text, not both."
        )

    if not meeting_date:
        raise ValueError("meeting_date is required (e.g. '2026-10-20').")

    # ── Route 1: Audio → Transcript ──────────────────────────────────────
    if has_audio:
        _log(f"[pipeline] Audio route: {audio_path}")

        # Convert and split audio
        segments, temp_dir = prepare_audio(audio_path)
        try:
            # Transcribe all segments
            lang = language_code(meeting_language)
            transcript_text = transcribe(
                audio_paths=segments,
                language=lang,
                glossary=glossary,
            )
        finally:
            # Always clean up temp files, even if transcription fails
            cleanup(temp_dir)

        _log(f"[pipeline] Transcript length: {len(transcript_text)} chars")

    # ── Route 2: Text (already have it) ──────────────────────────────────
    else:
        _log(f"[pipeline] Text route (transcript provided directly)")

    # ── Extract structured minutes ───────────────────────────────────────
    _log(f"[pipeline] Extracting minutes for date={meeting_date}...")

    minutes = extract_minutes(
        transcript=transcript_text,
        meeting_date=meeting_date,
        output_language=output_language,
        glossary=glossary,
    )

    return minutes, transcript_text


# ---------------------------------------------------------------------------
# CLI entry point: python -m services.pipeline
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline: audio or text → structured meeting minutes."
    )

    # Input: exactly one of --audio or --transcript-file
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--audio",
        metavar="FILE",
        help="Path to an audio/video file (mp3, wav, m4a, mp4, webm, ogg, flac).",
    )
    input_group.add_argument(
        "--transcript-file",
        metavar="FILE",
        help="Path to a plain-text transcript file.",
    )

    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Meeting date (e.g. 2026-10-20).",
    )
    parser.add_argument(
        "--language",
        default="Auto-detect",
        metavar="LANG",
        help='Meeting language for Whisper: "English", "Hindi", "Auto-detect" (default).',
    )
    parser.add_argument(
        "--output-language",
        default="English",
        metavar="LANG",
        help='Language for output fields. Default: "English".',
    )
    parser.add_argument(
        "--glossary",
        default=None,
        metavar="TERMS",
        help='Comma-separated names/terms to help Whisper (e.g. "CampusConnect, PostgreSQL").',
    )

    args = parser.parse_args()

    # Read the transcript file if provided
    transcript_text = None
    if args.transcript_file:
        path = Path(args.transcript_file)
        if not path.exists():
            print(f"Error: file not found — {path}", file=sys.stderr)
            raise SystemExit(1)
        transcript_text = path.read_text(encoding="utf-8")

    # Run the pipeline
    minutes, transcript = process_meeting(
        audio_path=args.audio,
        transcript_text=transcript_text,
        meeting_date=args.date,
        meeting_language=args.language,
        output_language=args.output_language,
        glossary=args.glossary,
    )

    # Print transcript to stderr, JSON to stdout
    _log("\n─── TRANSCRIPT ───")
    _log(transcript)
    _log("─── END TRANSCRIPT ───\n")

    print(json.dumps(minutes.model_dump(), indent=2, ensure_ascii=False))
