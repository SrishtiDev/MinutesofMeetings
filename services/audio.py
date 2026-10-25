"""
services/audio.py — Prepare audio files for transcription.

Converts any supported audio/video file to a small mono mp3 using ffmpeg.
If the result is over 24 MB, splits it into 10-minute segments.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Groq supports these extensions for audio input
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".flac"}

# Groq free tier limit: ~25 MB per file. We use 24 MB to leave a margin.
MAX_FILE_BYTES = 24 * 1024 * 1024  # 24 MB

# Each segment is 10 minutes (600 seconds)
SEGMENT_SECONDS = 600


class AudioError(Exception):
    """Raised when audio validation or conversion fails."""
    pass


def _check_ffmpeg() -> None:
    """Make sure ffmpeg is installed. Raise AudioError if not."""
    if shutil.which("ffmpeg") is None:
        raise AudioError(
            "ffmpeg is not installed. Install it with:\n"
            "  sudo apt install ffmpeg"
        )


def _validate_file(audio_path: str) -> Path:
    """Check that the file exists, is not empty, and has a supported extension."""
    path = Path(audio_path)

    if not path.exists():
        raise AudioError(f"File not found: {audio_path}")

    if path.stat().st_size == 0:
        raise AudioError(f"File is empty: {audio_path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise AudioError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    return path


def prepare_audio(audio_path: str) -> tuple[list[str], str]:
    """
    Convert an audio/video file to mono 16 kHz 32 kbps mp3 segments.

    Args:
        audio_path: Path to the input audio/video file.

    Returns:
        (segment_paths, temp_dir) — a list of mp3 file paths and the temp
        directory that holds them. Call cleanup(temp_dir) when done.

    Raises:
        AudioError: If validation or ffmpeg conversion fails.
    """
    _check_ffmpeg()
    source = _validate_file(audio_path)

    # Create a temp directory to hold the converted file(s)
    temp_dir = tempfile.mkdtemp(prefix="meetminutes_")
    converted = os.path.join(temp_dir, "converted.mp3")

    # Step 1: Convert to mono, 16 kHz, 32 kbps mp3
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",          # overwrite without asking
                "-i", str(source),       # input file
                "-ac", "1",              # mono (1 channel)
                "-ar", "16000",          # 16 kHz sample rate
                "-b:a", "32k",           # 32 kbps bitrate
                converted,
            ],
            check=True,                  # raise on non-zero exit
            stdout=subprocess.DEVNULL,   # suppress ffmpeg output
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        cleanup(temp_dir)
        raise AudioError(
            f"ffmpeg conversion failed (exit code {exc.returncode}). "
            f"Is the file a valid audio/video file?"
        )

    # Step 2: Check file size. If under 24 MB, return as single segment.
    file_size = os.path.getsize(converted)
    if file_size <= MAX_FILE_BYTES:
        return [converted], temp_dir

    # Step 3: File is too large — split into 10-minute segments
    segment_pattern = os.path.join(temp_dir, "segment_%03d.mp3")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", converted,
                "-f", "segment",                    # segment muxer
                "-segment_time", str(SEGMENT_SECONDS),  # 10 minutes each
                "-c", "copy",                        # no re-encoding needed
                segment_pattern,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        cleanup(temp_dir)
        raise AudioError(f"ffmpeg splitting failed (exit code {exc.returncode}).")

    # Collect the segment files in order (segment_000.mp3, segment_001.mp3, …)
    segments = sorted(
        [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
         if f.startswith("segment_") and f.endswith(".mp3")]
    )

    if not segments:
        cleanup(temp_dir)
        raise AudioError("ffmpeg produced no segments — something went wrong.")

    # Remove the big converted.mp3 to free disk space
    os.remove(converted)

    return segments, temp_dir


def cleanup(temp_dir: str) -> None:
    """Remove the temporary directory and all files inside it."""
    shutil.rmtree(temp_dir, ignore_errors=True)
