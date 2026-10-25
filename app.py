"""
app.py — Streamlit frontend for MeetMinutes AI.

Run with:  streamlit run app.py

Streamlit re-runs this whole script on every click, so anything we want to
keep (the generated minutes, checkbox ticks) lives in st.session_state.
"""

import html
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from services.audio import AudioError, SUPPORTED_EXTENSIONS
from services.exporter import to_markdown
from services.extractor import ExtractionError
from services.pipeline import process_meeting
from services.transcriber import TranscriptionError

load_dotenv()

st.set_page_config(
    page_title="MeetMinutes AI",
    page_icon=":material/description:",
    initial_sidebar_state="collapsed",
)

# Load the design: style.css (fonts + rules) and tokens.css (colour variables)
ASSETS = Path(__file__).parent / "assets"


def read_css(name: str) -> str:
    """Read a CSS file and drop blank lines (a blank line would end the <style> block in st.markdown)."""
    text = (ASSETS / name).read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if line.strip())


# One call per file, with the tags on their own lines so markdown leaves the CSS alone
for css_file in ("style.css", "tokens.css"):
    st.markdown(f"<style>\n{read_css(css_file)}\n</style>", unsafe_allow_html=True)

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mixed": "Hinglish (mixed)"}


# ---------------------------------------------------------------------------
# Small HTML helpers (all user/LLM text goes through html.escape first)
# ---------------------------------------------------------------------------

def eyebrow(text: str) -> None:
    """Small uppercase mono label with a teal dot."""
    st.markdown(f'<div class="eyebrow">{html.escape(text)}</div>', unsafe_allow_html=True)


def chip(text: str, css_class: str) -> str:
    """Return the HTML for one small pill."""
    return f'<span class="chip {css_class}">{html.escape(text)}</span>'


def format_deadline(deadline: str | None) -> str:
    """'2026-10-21' -> 'Wed, 21 Oct'. Falls back to the raw text if not a date."""
    if not deadline:
        return ""
    try:
        d = date.fromisoformat(deadline)
        return f"{d:%a}, {d.day} {d:%b}"
    except ValueError:
        return deadline


def run_pipeline(audio_bytes: bytes | None, suffix: str, transcript_text: str | None) -> None:
    """Run the pipeline and store the result in session_state (or show an error)."""
    # "Same as meeting" -> ask for output in the meeting language
    if output_choice == "English":
        output_language = "English"
    elif meeting_language == "Auto-detect":
        output_language = "the same language as the transcript"
    else:
        output_language = meeting_language

    audio_path = None
    try:
        with st.spinner("Generating minutes... this can take a minute for audio."):
            if audio_bytes is not None:
                # The pipeline wants a file path, so save the upload to a temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(audio_bytes)
                    audio_path = tmp.name

            minutes, transcript = process_meeting(
                audio_path=audio_path,
                transcript_text=transcript_text,
                meeting_date=meeting_date.isoformat(),
                meeting_language=meeting_language,
                output_language=output_language,
                glossary=glossary.strip() or None,
            )
    except (AudioError, TranscriptionError, ExtractionError) as exc:
        st.error(str(exc), icon=":material/error:")
        return
    except ValueError as exc:
        # Missing API key and bad input both end up here
        st.error(f"Problem with your input or setup: {exc}", icon=":material/error:")
        return
    except Exception:
        # Anything unexpected: friendly message, no stack trace in the UI
        st.error(
            "Something went wrong while generating the minutes. "
            "Please try again; if it keeps happening, check the terminal logs.",
            icon=":material/error:",
        )
        return
    finally:
        # Always delete the temp audio file
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)

    # A title typed by the user replaces the generated one
    if meeting_title.strip():
        minutes = minutes.model_copy(update={"title": meeting_title.strip()})

    st.session_state.minutes = minutes
    st.session_state.transcript = transcript
    st.session_state.result_date = meeting_date.isoformat()
    # Forget checkbox ticks from any previous result
    for key in [k for k in st.session_state if str(k).startswith("done_")]:
        del st.session_state[key]




def show_results() -> None:
    """Render the minutes stored in session_state, one flat card per section."""
    minutes = st.session_state.minutes
    language = LANGUAGE_NAMES.get(minutes.detected_language, minutes.detected_language)

    # Card 1: title, language chip and date chip
    with st.container(key="card_head"):
        eyebrow("Meeting minutes")
        st.markdown(f'<div class="card-title">{html.escape(minutes.title)}</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="chip-row">'
            + chip(language, "chip-foam")
            + chip(format_deadline(st.session_state.result_date), "chip-date")
            + "</div>",
            unsafe_allow_html=True,
        )

    # Card 2: summary
    with st.container(key="card_summary"):
        eyebrow("Summary")
        st.markdown(f'<p class="card-text">{html.escape(minutes.summary)}</p>', unsafe_allow_html=True)

    # Card 3: key points | decisions side by side (they stack on phones)
    with st.container(key="card_points"):
        col_points, col_decisions = st.columns(2, gap="large")
        for column, label, items in (
            (col_points, "Key points", minutes.key_points),
            (col_decisions, "Decisions", minutes.decisions),
        ):
            with column:
                eyebrow(label)
                if items:
                    li = "".join(f"<li>{html.escape(t)}</li>" for t in items)
                    st.markdown(f'<ul class="card-list">{li}</ul>', unsafe_allow_html=True)
                else:
                    st.markdown('<p class="card-empty">None</p>', unsafe_allow_html=True)

    # Card 4: action items, one row each: checkbox + task | owner chip | deadline chip
    with st.container(key="card_actions"):
        eyebrow("Action items")
        if not minutes.action_items:
            st.markdown('<p class="card-empty">None</p>', unsafe_allow_html=True)
        for i, item in enumerate(minutes.action_items):
            col_task, col_chips = st.columns([5, 4], vertical_alignment="center")
            # The checkbox keeps its state in session_state via its key
            col_task.checkbox(item.task, key=f"done_{i}")
            owner_chip = (
                chip(item.owner, "chip-owner") if item.owner else chip("⚠ Unassigned", "chip-rose")
            )
            deadline_chip = (
                chip(format_deadline(item.deadline), "chip-date")
                if item.deadline
                else chip("No deadline", "chip-muted")
            )
            # Both chips share one row, so on a phone they sit together under the task
            col_chips.markdown(
                f'<div class="chip-row">{owner_chip}{deadline_chip}</div>', unsafe_allow_html=True
            )

    with st.expander("Original transcript"):
        st.text(st.session_state.transcript)

    # Downloads: two outlined buttons
    markdown = to_markdown(
        minutes,
        transcript=st.session_state.transcript,
        meeting_date=st.session_state.result_date,
    )
    json_text = json.dumps(minutes.model_dump(), indent=2, ensure_ascii=False)
    col1, col2 = st.columns(2)
    col1.download_button(
        "Download Markdown", markdown, file_name="minutes.md",
        mime="text/markdown", icon=":material/download:", width="stretch",
    )
    col2.download_button(
        "Download JSON", json_text, file_name="minutes.json",
        mime="application/json", icon=":material/download:", width="stretch",
    )


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
<div class="hero">
<div class="eyebrow">Hindi · English · Hinglish</div>
<div class="hero-title" role="heading" aria-level="1">
Meetings that write their <span class="accent">own minutes.</span>
</div>
<p class="hero-sub">Upload a recording or paste a transcript and get clear,
structured minutes with decisions and action items.</p>
<div class="hero-chips">
<span class="chip chip-foam">Hindi</span>
<span class="chip chip-sand">English</span>
<span class="chip chip-mint">Hinglish</span>
</div>
</div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Input card: settings, three input tabs, one Generate button
# ---------------------------------------------------------------------------

with st.container(key="card_input"):
    meeting_title = st.text_input("Meeting title (optional)")

    col_date, col_lang, col_out = st.columns(3)
    meeting_date = col_date.date_input("Meeting date", value=date.today())
    meeting_language = col_lang.selectbox(
        "Meeting language", ["Auto-detect", "Hindi", "English", "Hinglish"]
    )
    output_choice = col_out.selectbox("Output language", ["English", "Same as meeting"])

    with st.expander("Glossary (optional)"):
        glossary = st.text_input(
            "Names and technical terms, comma separated",
            placeholder="Arjun, Priya, CampusConnect",
            help="Helps speech recognition spell names correctly. Used for audio only.",
        )

    # on_change="rerun" lets us ask each tab "are you the selected one?" (.open)
    tab_upload, tab_record, tab_paste = st.tabs(
        ["Upload file", "Record", "Paste transcript"], on_change="rerun"
    )

    uploaded = None
    recording = None
    pasted = ""

    with tab_upload:
        if tab_upload.open:
            extensions = sorted(e.lstrip(".") for e in SUPPORTED_EXTENSIONS)
            uploaded = st.file_uploader("Audio or video file", type=extensions)

    with tab_record:
        if tab_record.open:
            recording = st.audio_input("Record from your microphone")

    with tab_paste:
        if tab_paste.open:
            pasted = st.text_area(
                "Transcript", height=250, placeholder="Paste the meeting transcript here"
            )

    # One button for all tabs: use whichever tab is currently selected
    if st.button("Generate minutes", type="primary", width="stretch"):
        if tab_upload.open:
            if uploaded is None:
                st.error("Please upload a file first.", icon=":material/error:")
            else:
                run_pipeline(uploaded.getvalue(), os.path.splitext(uploaded.name)[1], None)
        elif tab_record.open:
            if recording is None:
                st.error("Please record something first.", icon=":material/error:")
            else:
                run_pipeline(recording.getvalue(), ".wav", None)
        else:
            if not pasted.strip():
                st.error("Please paste a transcript first.", icon=":material/error:")
            else:
                run_pipeline(None, "", pasted)

    st.markdown(
        '<p class="privacy-note">Free-tier APIs: please avoid uploading confidential meetings.</p>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Results (shown whenever session_state has them)
# ---------------------------------------------------------------------------

if "minutes" in st.session_state:
    show_results()

st.markdown('<div class="footer">Built with Whisper and an LLM via Groq</div>', unsafe_allow_html=True)
