"""Validate model output against a pydantic output model (ADR-0017 §4)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError

FENCE = re.compile(r"^```(?:json)?[ \t]*\n(.*)\n```$", re.DOTALL)


def schema_of(output: type[BaseModel]) -> dict[str, Any]:
    return output.model_json_schema()


def unfenced(text: str) -> str:
    """The text inside one surrounding Markdown code fence, else the text unchanged."""
    match = FENCE.match(text.strip())
    return match.group(1) if match else text


def validate(output: type[BaseModel], text: str) -> tuple[BaseModel | None, str | None]:
    """(value, None) if `text` is valid, else (None, "<field path>: <message>")."""
    try:
        return output.model_validate_json(unfenced(text)), None
    except ValidationError as error:
        first = error.errors()[0]
        loc = ".".join(str(part) for part in first["loc"])
        return None, f"{loc}: {first['msg']}" if loc else str(first["msg"])
