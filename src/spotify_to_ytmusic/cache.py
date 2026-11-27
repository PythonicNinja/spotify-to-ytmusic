"""Local JSON caches keyed by Spotify track ID for O(1) lookups."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def load_model_cache(path: Path, model_cls: type[T]) -> dict[str, T]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {key: model_cls.model_validate(value) for key, value in raw.items()}


def save_model_cache(path: Path, data: dict[str, BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value.model_dump() for key, value in data.items()}
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)
