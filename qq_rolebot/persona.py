from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PersonaSource:
    name: str
    url: str
    purpose: str = ""


@dataclass(frozen=True)
class Persona:
    name: str
    style: str
    relationship: str
    likes: list[str]
    dislikes: list[str]
    boundaries: list[str]
    user_name: str = ""
    language: str = ""
    profile: str = ""
    background: str = ""
    rules: str = ""
    prologue: str = ""
    examples: list[str] = field(default_factory=list)
    sources: list[PersonaSource] = field(default_factory=list)


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return [str(item) for item in value]


def _text(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def _string_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _block_lines(value: str) -> list[str]:
    return [line.strip().removeprefix("-").strip() for line in value.splitlines() if line.strip()]


def _sources(value: Any) -> list[PersonaSource]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Sources must be a list")

    sources: list[PersonaSource] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each source must be a mapping")
        name = _text(item, "name")
        url = _text(item, "url")
        if not name or not url:
            raise ValueError("each source must include name and url")
        sources.append(PersonaSource(name=name, url=url, purpose=_text(item, "purpose")))
    return sources


def _load_roleplay_persona(data: dict[str, Any]) -> Persona:
    rules = _text(data, "Rules")
    background = _text(data, "Background")
    return Persona(
        name=_text(data, "assistant_name"),
        style=_text(data, "Skills"),
        relationship=background,
        likes=[],
        dislikes=[],
        boundaries=_block_lines(rules),
        user_name=_text(data, "user_name"),
        language=_text(data, "language"),
        profile=_text(data, "Profile"),
        background=background,
        rules=rules,
        prologue=_text(data, "Prologue"),
        examples=_string_items(data.get("Examples")),
        sources=_sources(data.get("Sources")),
    )


def load_persona(path: Path) -> Persona:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("persona file must contain a mapping")
    if "assistant_name" in data:
        return _load_roleplay_persona(data)
    return Persona(
        name=str(data["name"]),
        style=str(data["style"]),
        relationship=str(data["relationship"]),
        likes=_string_list(data, "likes"),
        dislikes=_string_list(data, "dislikes"),
        boundaries=_string_list(data, "boundaries"),
        sources=_sources(data.get("Sources")),
    )
