from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

from .models import ContentValidationError


_GENERIC_TITLE_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "german",
    "in",
    "lesson",
    "of",
    "short",
    "the",
    "to",
    "video",
    "vocabulary",
    "word",
    "words",
}


def content_titles(pack: dict[str, Any]) -> list[str]:
    """Return the four audience-facing titles in stable pack order."""
    return [
        str(asset.get("title", "")).strip()
        for collection in (pack.get("shorts", []), pack.get("long_videos", []))
        for asset in collection
        if isinstance(asset, dict) and str(asset.get("title", "")).strip()
    ]


def title_signature(title: str) -> tuple[str, ...]:
    """Normalize cosmetic title differences such as punctuation and plural `directions`."""
    text = title.split(":", 1)[-1]
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    result: list[str] = []
    for token in re.findall(r"[a-z0-9]+", text):
        if token in _GENERIC_TITLE_WORDS:
            continue
        if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
            token = token[:-1]
        result.append(token)
    return tuple(result)


def titles_are_confusingly_similar(left: str, right: str) -> bool:
    """Use a deliberately narrow near-duplicate test for audience-facing headings."""
    left_signature = title_signature(left)
    right_signature = title_signature(right)
    if not left_signature or not right_signature:
        return left.strip().casefold() == right.strip().casefold()
    if left_signature == right_signature:
        return True
    left_tokens, right_tokens = set(left_signature), set(right_signature)
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union)
    sequence = SequenceMatcher(
        None,
        " ".join(left_signature),
        " ".join(right_signature),
    ).ratio()
    return jaccard >= 0.80 or sequence >= 0.90


def find_title_collisions(
    candidate_titles: Iterable[str],
    reserved_titles: Iterable[str] = (),
) -> list[tuple[str, str]]:
    candidates = [str(title).strip() for title in candidate_titles if str(title).strip()]
    reserved = [str(title).strip() for title in reserved_titles if str(title).strip()]
    collisions: list[tuple[str, str]] = []
    for index, candidate in enumerate(candidates):
        comparisons = [*candidates[:index], *reserved]
        for existing in comparisons:
            if titles_are_confusingly_similar(candidate, existing):
                collisions.append((candidate, existing))
                break
    return collisions


def validate_unique_titles(
    pack: dict[str, Any],
    *,
    reserved_titles: Iterable[str] = (),
) -> None:
    collisions = find_title_collisions(content_titles(pack), reserved_titles)
    if not collisions:
        return
    details = "; ".join(
        f"{candidate!r} conflicts with {existing!r}"
        for candidate, existing in collisions
    )
    raise ContentValidationError(
        "Audience-facing titles must be distinct from all uploaded titles, including minor "
        f"singular/plural or generic-prefix variations: {details}"
    )
