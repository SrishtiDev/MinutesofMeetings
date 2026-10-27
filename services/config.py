"""Configuration lookup for local development and Streamlit Cloud."""

import os

from dotenv import load_dotenv


def get_setting(*names: str, default: str | None = None) -> str | None:
    """Return the first non-empty environment variable or Streamlit secret."""
    load_dotenv()

    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()

    # Keep Streamlit lazy so command-line evaluation scripts still work.
    try:
        import streamlit as st

        for name in names:
            value = st.secrets.get(name) or st.secrets.get(name.lower())
            if value is not None and str(value).strip():
                return str(value).strip()
    except Exception:
        # No secrets file exists when this module is used outside Streamlit.
        pass

    return default
