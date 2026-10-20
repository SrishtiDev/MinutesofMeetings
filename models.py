"""
models.py — Pydantic v2 data models for MeetMinutes AI.

In Python, 'dataclasses' and Pydantic models are both ways to define structured
data objects. Pydantic adds automatic type validation and JSON serialisation,
which is why we use it here instead of plain Python dataclasses.
"""

from typing import Literal  # Literal restricts a field to a fixed set of values
from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    """A single task that someone committed to doing in the meeting."""

    task: str
    # 'str | None' means the value can be a string OR the Python equivalent of
    # null (which is None). Field(default=None) means "use None if not provided".
    owner: str | None = Field(default=None)
    deadline: str | None = Field(
        default=None,
        description="ISO date YYYY-MM-DD when resolvable, otherwise null.",
    )


class Minutes(BaseModel):
    """Structured meeting minutes extracted from a transcript."""

    title: str
    # Literal["en", "hi", "mixed"] means only those three string values are valid.
    detected_language: Literal["en", "hi", "mixed"]
    summary: str
    # Field(default_factory=list) creates a fresh empty list for each instance.
    # This is the correct Python pattern — never use `default=[]` with mutable
    # types because all instances would share the same list object.
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
