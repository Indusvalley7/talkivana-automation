from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook

from .models import ContentValidationError


class TopicHistoryError(RuntimeError):
    """Raised when the checked-in Excel topic registry cannot be read safely."""


_GENERIC_TOPIC_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "beginner",
    "daily",
    "essential",
    "for",
    "german",
    "in",
    "learn",
    "learning",
    "lesson",
    "of",
    "short",
    "the",
    "to",
    "useful",
    "video",
    "vocabulary",
    "word",
    "words",
}


_TOPIC_FAMILY_PATTERNS: dict[str, tuple[str, ...]] = {
    "appointments": ("appointment", "consultation", "doctor", "clinic", "schedule"),
    "bakery": ("bakery", "bread", "bread roll", "pastry"),
    "cafe": ("cafe", "coffee", "cake", "refreshment"),
    "directions": ("direction", "navigate", "navigation", "street", "turn", "where is"),
    "greetings": ("greeting", "introduction", "introduce", "meeting", "meet someone"),
    "groceries": ("fresh fruit", "grocer", "grocery", "market", "supermarket"),
    "neighbours": ("apartment", "community", "hallway", "neighbor", "neighbour"),
    "restaurants": ("dining", "meal", "restaurant", "table and water", "waiter"),
    "routines": ("bedtime", "daily routine", "morning routine", "wake up"),
    "school": ("classroom", "homework", "notebook", "school", "study"),
    "transport": ("bus", "platform", "public transport", "station", "ticket", "train", "tram"),
    "weather": ("climate", "jacket", "rain", "umbrella", "weather", "wind"),
    "workplace": ("colleague", "document", "office", "printing", "workplace"),
}


_TOPIC_ACTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "ask_directions": ("ask for directions", "find", "navigate", "where is"),
    "book": ("book", "booking", "make an appointment", "schedule", "scheduling"),
    "buy": ("buy", "buying", "pay", "paying", "purchase"),
    "check_in": ("check in", "checking in", "registration"),
    "introduce": ("introduce", "introducing", "introduction", "meet", "meeting"),
    "order": ("order", "ordering", "would like"),
    "rent": ("rent", "renting"),
    "travel": ("board", "boarding", "catch", "catching", "depart", "departure"),
}


def load_excel_video_history(path: Path) -> list[str]:
    """Read every tracked video/Short heading from the checked-in schedule workbook."""
    if not path.is_file():
        raise TopicHistoryError(f"Topic-history workbook is missing: {path}")
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl exposes several format-specific exception types
        raise TopicHistoryError(f"Topic-history workbook could not be read: {path}") from exc
    try:
        if "Schedule Matrix" not in workbook.sheetnames:
            raise TopicHistoryError("Topic-history workbook has no 'Schedule Matrix' sheet.")
        sheet = workbook["Schedule Matrix"]
        header_row = None
        title_column = None
        for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 20)):
            for cell in row:
                if str(cell.value or "").strip() == "YouTube video / Short":
                    header_row = cell.row
                    title_column = cell.column
                    break
            if header_row is not None:
                break
        if header_row is None or title_column is None:
            raise TopicHistoryError(
                "Topic-history workbook is missing the 'YouTube video / Short' column."
            )
        headings: list[str] = []
        for row_number in range(header_row + 1, sheet.max_row + 1):
            value = str(sheet.cell(row_number, title_column).value or "").strip()
            if value:
                headings.append(value)
        return list(dict.fromkeys(headings))
    finally:
        workbook.close()


def content_topic_entries(pack: dict[str, Any]) -> list[str]:
    """Return one rich topic description for each linked Short/long-video pair."""
    longs = {
        str(asset.get("linked_short_asset_id", "")): asset
        for asset in pack.get("long_videos", [])
        if isinstance(asset, dict)
    }
    entries: list[str] = []
    for short in pack.get("shorts", []):
        if not isinstance(short, dict):
            continue
        long_video = longs.get(str(short.get("asset_id", "")), {})
        fields = [
            short.get("topic", ""),
            short.get("title", ""),
            long_video.get("title", ""),
            long_video.get("scenario", ""),
            long_video.get("learning_objective", ""),
        ]
        entry = " | ".join(str(value).strip() for value in fields if str(value).strip())
        if entry:
            entries.append(entry)
    return entries


def topic_families(text: str) -> set[str]:
    normalized = _normalized_text(text)
    return {
        family
        for family, patterns in _TOPIC_FAMILY_PATTERNS.items()
        if any(_phrase_present(normalized, pattern) for pattern in patterns)
    }


def topic_actions(text: str) -> set[str]:
    normalized = _normalized_text(text)
    return {
        action
        for action, patterns in _TOPIC_ACTION_PATTERNS.items()
        if any(_phrase_present(normalized, pattern) for pattern in patterns)
    }


def topics_are_repeated(candidate: str, existing: str) -> bool:
    """Detect the same practical scenario without banning an entire broad category."""
    candidate_families = topic_families(candidate)
    existing_families = topic_families(existing)
    candidate_actions = topic_actions(candidate)
    existing_actions = topic_actions(existing)
    if candidate_families & existing_families and candidate_actions & existing_actions:
        return True

    left = set(_topic_tokens(candidate))
    right = set(_topic_tokens(existing))
    if not left or not right:
        return False
    shared = left & right
    smaller = min(len(left), len(right))
    return len(shared) >= 2 and len(shared) / smaller >= 0.67


def find_topic_collisions(
    candidate_topics: Iterable[str],
    existing_topics: Iterable[str] = (),
) -> list[tuple[str, str]]:
    candidates = [str(value).strip() for value in candidate_topics if str(value).strip()]
    existing = [str(value).strip() for value in existing_topics if str(value).strip()]
    collisions: list[tuple[str, str]] = []
    for index, candidate in enumerate(candidates):
        for prior in [*candidates[:index], *existing]:
            if topics_are_repeated(candidate, prior):
                collisions.append((candidate, prior))
                break
    return collisions


def validate_unique_topics(
    pack: dict[str, Any],
    *,
    existing_topics: Iterable[str] = (),
) -> None:
    collisions = find_topic_collisions(content_topic_entries(pack), existing_topics)
    if not collisions:
        return
    details = "; ".join(
        f"{_brief(candidate)!r} repeats {_brief(existing)!r}"
        for candidate, existing in collisions
    )
    raise ContentValidationError(
        "Lesson topics must be materially different from every entry in the Excel video history: "
        f"{details}"
    )


def _normalized_text(value: str) -> str:
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _phrase_present(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalized_text(phrase)
    return bool(re.search(rf"\b{re.escape(normalized_phrase)}(?:s|es)?\b", normalized_text))


def _topic_tokens(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for token in _normalized_text(value).split():
        if token in _GENERIC_TOPIC_WORDS:
            continue
        if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
            token = token[:-1]
        result.append(token)
    return tuple(result)


def _brief(value: str, maximum: int = 90) -> str:
    value = " ".join(value.split())
    return value if len(value) <= maximum else value[: maximum - 1] + "…"
