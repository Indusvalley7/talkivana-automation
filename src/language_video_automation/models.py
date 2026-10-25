from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable


class ContentValidationError(ValueError):
    pass


VOCABULARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "english": {"type": "string"},
        "german": {"type": "string"},
        "pronunciation": {"type": "string"},
        "part_of_speech": {"type": "string"},
    },
    "required": ["english", "german", "pronunciation", "part_of_speech"],
    "additionalProperties": False,
}

DIALOGUE_TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "speaker": {"type": "string", "enum": ["A", "B"]},
        "english": {"type": "string"},
        "german": {"type": "string"},
        "pronunciation": {"type": "string"},
    },
    "required": ["speaker", "english", "german", "pronunciation"],
    "additionalProperties": False,
}

SHORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asset_id": {"type": "string"},
        "title": {"type": "string"},
        "topic": {"type": "string"},
        "linked_long_asset_id": {"type": "string"},
        "vocabulary": {
            "type": "array",
            "items": VOCABULARY_SCHEMA,
        },
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "asset_id", "title", "topic", "linked_long_asset_id",
        "vocabulary", "description", "tags",
    ],
    "additionalProperties": False,
}

LONG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asset_id": {"type": "string"},
        "title": {"type": "string"},
        "scenario": {"type": "string"},
        "learning_objective": {"type": "string"},
        "linked_short_asset_id": {"type": "string"},
        "focus_vocabulary": {
            "type": "array",
            "items": VOCABULARY_SCHEMA,
        },
        "dialogue": {
            "type": "array",
            "items": DIALOGUE_TURN_SCHEMA,
        },
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "asset_id", "title", "scenario", "learning_objective", "linked_short_asset_id",
        "focus_vocabulary", "dialogue", "description", "tags",
    ],
    "additionalProperties": False,
}

CONTENT_PACK_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pack_title": {"type": "string"},
        "source_language": {"type": "string"},
        "target_language": {"type": "string"},
        "language_variety": {"type": "string"},
        "level": {"type": "string"},
        "shorts": {"type": "array", "items": SHORT_SCHEMA},
        "long_videos": {"type": "array", "items": LONG_SCHEMA},
    },
    "required": [
        "pack_title", "source_language", "target_language", "language_variety",
        "level", "shorts", "long_videos",
    ],
    "additionalProperties": False,
}

QA_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "problems": {"type": "array", "items": {"type": "string"}},
        "corrected_pack": CONTENT_PACK_JSON_SCHEMA,
    },
    "required": ["approved", "problems", "corrected_pack"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ContentPackRecord:
    pack_id: str
    created_date: str
    revision: int
    content: dict[str, Any]
    qa_problems: tuple[str, ...] = ()
    replacement_for: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "created_date": self.created_date,
            "revision": self.revision,
            "content": self.content,
            "qa_problems": list(self.qa_problems),
            "replacement_for": self.replacement_for,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContentPackRecord":
        required = {"pack_id", "created_date", "revision", "content"}
        missing = required - set(data)
        if missing:
            raise ContentValidationError(f"Content-pack record is missing: {', '.join(sorted(missing))}")
        return cls(
            pack_id=str(data["pack_id"]),
            created_date=str(data["created_date"]),
            revision=int(data["revision"]),
            content=dict(data["content"]),
            qa_problems=tuple(str(item) for item in data.get("qa_problems", [])),
            replacement_for=data.get("replacement_for"),
        )


def _nonempty(value: Any, field: str, errors: list[str], *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be non-empty text")
        return ""
    result = value.strip()
    if len(result) > maximum:
        errors.append(f"{field} exceeds {maximum} characters")
    unsafe = re.compile(r"(?:https?://|www\.|@[A-Za-z0-9_.-]+|\b(?:buy now|subscribe now)\b)", re.I)
    if unsafe.search(result):
        errors.append(f"{field} contains a forbidden link or promotion")
    return result


def _validate_vocab(items: Any, expected_count: int, field: str, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(items, list) or len(items) != expected_count:
        errors.append(f"{field} must contain exactly {expected_count} entries")
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = set(VOCABULARY_SCHEMA["required"])
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"{field}[{index}] must be an object")
            continue
        if set(item) != required:
            errors.append(f"{field}[{index}] must contain exactly {sorted(required)}")
        for name in required:
            _nonempty(item.get(name), f"{field}[{index}].{name}", errors, maximum=160)
        term = str(item.get("german", "")).strip().casefold()
        if term in seen:
            errors.append(f"{field} contains duplicate German term {term!r}")
        seen.add(term)
        result.append(item)
    return result


_GERMAN_ARTICLES = {
    "der", "die", "das", "den", "dem", "des",
    "ein", "eine", "einen", "einem", "einer", "eines",
}


def _german_vocabulary_used(term: str, corpus: str) -> bool:
    """Match a taught item without rewarding grammatically artificial verbatim phrasing."""
    word_pattern = r"[a-zäöüß]+"
    term_words = re.findall(word_pattern, term.casefold())
    corpus_words = set(re.findall(word_pattern, corpus.casefold()))
    content_words = [word for word in term_words if word not in _GERMAN_ARTICLES]
    if not content_words:
        content_words = term_words

    for word in content_words:
        if word in corpus_words:
            continue
        if len(word) > 4 and word.endswith("en"):
            stem = word[:-2]
            conjugations = {
                stem,
                f"{stem}e",
                f"{stem}st",
                f"{stem}t",
                f"{stem}en",
                f"{stem}et",
            }
            if corpus_words.intersection(conjugations):
                continue
        if word.endswith("e") and f"{word}n" in corpus_words:
            continue
        return False
    return bool(content_words)


def validate_content_pack(
    pack: dict[str, Any],
    *,
    source_language: str,
    target_language: str,
    language_variety: str,
    words_per_short: int,
    dialogue_turns_per_long: int,
) -> None:
    errors: list[str] = []
    expected = set(CONTENT_PACK_JSON_SCHEMA["required"])
    if set(pack) != expected:
        missing, extra = expected - set(pack), set(pack) - expected
        if missing:
            errors.append(f"missing fields: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"unexpected fields: {', '.join(sorted(extra))}")
    if str(pack.get("source_language", "")).casefold() != source_language.casefold():
        errors.append("source_language does not match configuration")
    if str(pack.get("target_language", "")).casefold() != target_language.casefold():
        errors.append("target_language does not match configuration")
    if str(pack.get("language_variety", "")).casefold() != language_variety.casefold():
        errors.append("language_variety does not match configuration")
    for field in ("pack_title", "level"):
        _nonempty(pack.get(field), field, errors)

    shorts = pack.get("shorts")
    longs = pack.get("long_videos")
    if not isinstance(shorts, list) or len(shorts) != 2:
        errors.append("shorts must contain exactly two assets")
        shorts = []
    if not isinstance(longs, list) or len(longs) != 2:
        errors.append("long_videos must contain exactly two assets")
        longs = []
    short_ids = {str(item.get("asset_id", "")) for item in shorts if isinstance(item, dict)}
    long_ids = {str(item.get("asset_id", "")) for item in longs if isinstance(item, dict)}
    if short_ids != {"short-1", "short-2"}:
        errors.append("Short asset IDs must be short-1 and short-2")
    if long_ids != {"long-1", "long-2"}:
        errors.append("Long asset IDs must be long-1 and long-2")

    vocab_by_short: dict[str, list[dict[str, Any]]] = {}
    required_short = set(SHORT_SCHEMA["required"])
    for index, short in enumerate(shorts, start=1):
        if not isinstance(short, dict):
            continue
        if set(short) != required_short:
            errors.append(f"shorts[{index}] has missing or unexpected fields")
        for field in ("asset_id", "title", "topic", "linked_long_asset_id", "description"):
            _nonempty(short.get(field), f"shorts[{index}].{field}", errors)
        tags = short.get("tags")
        if not isinstance(tags, list) or not 3 <= len(tags) <= 10:
            errors.append(f"shorts[{index}].tags must contain 3 to 10 entries")
        vocab_by_short[str(short.get("asset_id", ""))] = _validate_vocab(
            short.get("vocabulary"), words_per_short, f"shorts[{index}].vocabulary", errors
        )
        if str(short.get("linked_long_asset_id", "")) not in long_ids:
            errors.append(f"shorts[{index}] links to an unknown long video")

    required_long = set(LONG_SCHEMA["required"])
    for index, long_video in enumerate(longs, start=1):
        if not isinstance(long_video, dict):
            continue
        if set(long_video) != required_long:
            errors.append(f"long_videos[{index}] has missing or unexpected fields")
        for field in (
            "asset_id", "title", "scenario", "learning_objective",
            "linked_short_asset_id", "description",
        ):
            _nonempty(long_video.get(field), f"long_videos[{index}].{field}", errors)
        linked = str(long_video.get("linked_short_asset_id", ""))
        if linked not in short_ids:
            errors.append(f"long_videos[{index}] links to an unknown Short")
        focus = _validate_vocab(
            long_video.get("focus_vocabulary"),
            words_per_short,
            f"long_videos[{index}].focus_vocabulary",
            errors,
        )
        source_terms = {
            str(item.get("german", "")).strip().casefold() for item in vocab_by_short.get(linked, [])
        }
        focus_terms = {str(item.get("german", "")).strip().casefold() for item in focus}
        if source_terms and focus_terms != source_terms:
            errors.append(f"long_videos[{index}] focus vocabulary must exactly match its linked Short")
        dialogue = long_video.get("dialogue")
        if not isinstance(dialogue, list) or len(dialogue) != dialogue_turns_per_long:
            errors.append(
                f"long_videos[{index}].dialogue must contain exactly {dialogue_turns_per_long} turns"
            )
            dialogue = []
        speakers: list[str] = []
        corpus = ""
        for turn_index, turn in enumerate(dialogue, start=1):
            if not isinstance(turn, dict) or set(turn) != set(DIALOGUE_TURN_SCHEMA["required"]):
                errors.append(f"long_videos[{index}].dialogue[{turn_index}] has invalid fields")
                continue
            speaker = str(turn.get("speaker", ""))
            if speaker not in {"A", "B"}:
                errors.append(f"long_videos[{index}].dialogue[{turn_index}].speaker must be A or B")
            speakers.append(speaker)
            for field in ("english", "german", "pronunciation"):
                _nonempty(
                    turn.get(field),
                    f"long_videos[{index}].dialogue[{turn_index}].{field}",
                    errors,
                    maximum=240,
                )
            corpus += " " + str(turn.get("german", "")).casefold()
        if len(set(speakers)) < 2:
            errors.append(f"long_videos[{index}] must use both speakers")
        expected_speakers = [
            "A" if turn_index % 2 == 0 else "B"
            for turn_index in range(len(speakers))
        ]
        if speakers != expected_speakers:
            errors.append(
                f"long_videos[{index}] dialogue must start with A and alternate A/B exactly"
            )
        for term in focus_terms:
            if term and not _german_vocabulary_used(term, corpus):
                errors.append(
                    f"long_videos[{index}] does not use linked vocabulary word family {term!r}"
                )
        tags = long_video.get("tags")
        if not isinstance(tags, list) or not 3 <= len(tags) <= 10:
            errors.append(f"long_videos[{index}].tags must contain 3 to 10 entries")

    if errors:
        raise ContentValidationError("; ".join(errors))


def build_pack_record(
    pack: dict[str, Any],
    *,
    revision: int = 1,
    qa_problems: Iterable[str] = (),
    replacement_for: int | None = None,
    today: date | None = None,
) -> ContentPackRecord:
    pack_date = today or date.today()
    digest = hashlib.sha256(
        json.dumps(pack, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]
    language_slug = re.sub(
        r"[^a-z0-9]+", "-", str(pack["target_language"]).casefold()
    ).strip("-")
    pack_id = f"{pack_date.isoformat()}-{language_slug}-pack-r{revision}-{digest}"
    return ContentPackRecord(
        pack_id=pack_id,
        created_date=pack_date.isoformat(),
        revision=revision,
        content=pack,
        qa_problems=tuple(str(item)[:300] for item in qa_problems),
        replacement_for=replacement_for,
    )


def validate_record_integrity(record: ContentPackRecord) -> None:
    rebuilt = build_pack_record(
        record.content,
        revision=record.revision,
        qa_problems=record.qa_problems,
        replacement_for=record.replacement_for,
        today=date.fromisoformat(record.created_date),
    )
    if rebuilt.pack_id != record.pack_id:
        raise ContentValidationError(
            "Pack ID does not match the embedded content; the Issue may have been edited."
        )


def recent_vocabulary(
    records: Iterable[ContentPackRecord], target_language: str, limit: int = 120
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for record in records:
        if str(record.content.get("target_language", "")).casefold() != target_language.casefold():
            continue
        for short in record.content.get("shorts", []):
            for item in short.get("vocabulary", []):
                term = str(item.get("german", "")).strip()
                if term and term.casefold() not in seen:
                    found.append(term)
                    seen.add(term.casefold())
                    if len(found) >= limit:
                        return found
    return found
