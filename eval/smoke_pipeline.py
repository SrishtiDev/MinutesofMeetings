"""
eval/smoke_pipeline.py — Quick smoke test for the text route of the pipeline.

Runs process_meeting on data/english_01.txt and prints basic stats.
No audio needed, no external API call recording — just checks that the
text route still works end to end.

Usage:
    python eval/smoke_pipeline.py
"""

import sys
from pathlib import Path

# Add the project root to Python's path so imports work
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.pipeline import process_meeting


def main() -> None:
    # Read the sample transcript
    sample = PROJECT_ROOT / "data" / "english_01.txt"
    if not sample.exists():
        print(f"ERROR: Sample file not found: {sample}", file=sys.stderr)
        raise SystemExit(1)

    transcript_text = sample.read_text(encoding="utf-8")

    print("Running pipeline (text route) on data/english_01.txt...", file=sys.stderr)

    # Run the text route
    minutes, transcript = process_meeting(
        transcript_text=transcript_text,
        meeting_date="2026-10-20",
        output_language="English",
    )

    # Print simple stats to confirm it works
    print(f"\n✅ Pipeline smoke test passed!", file=sys.stderr)
    print(f"   Title        : {minutes.title}", file=sys.stderr)
    print(f"   Language      : {minutes.detected_language}", file=sys.stderr)
    print(f"   Key points   : {len(minutes.key_points)}", file=sys.stderr)
    print(f"   Decisions     : {len(minutes.decisions)}", file=sys.stderr)
    print(f"   Action items  : {len(minutes.action_items)}", file=sys.stderr)
    print(f"   Transcript len: {len(transcript)} chars", file=sys.stderr)

    # Quick sanity: we expect at least 1 action item
    if len(minutes.action_items) == 0:
        print("⚠️  WARNING: No action items found — that's unexpected!", file=sys.stderr)
        raise SystemExit(1)

    print(f"   All good. 🎉", file=sys.stderr)


if __name__ == "__main__":
    main()
