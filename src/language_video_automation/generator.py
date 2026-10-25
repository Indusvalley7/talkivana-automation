from __future__ import annotations

import json
from datetime import date

from .config import AppConfig, Playlist, load_guardrails
from .gemini import GeminiClient
from .models import (
    CONTENT_PACK_JSON_SCHEMA,
    QA_JSON_SCHEMA,
    ContentPackRecord,
    build_pack_record,
    recent_vocabulary,
    validate_content_pack,
)


class ContentPackGenerator:
    def __init__(self, config: AppConfig, client: GeminiClient) -> None:
        self.config = config
        self.client = client
        self.guardrails = load_guardrails()

    def create(
        self,
        *,
        playlist: Playlist,
        history: list[ContentPackRecord],
        revision: int = 1,
        replacement_for: int | None = None,
        revision_feedback: str = "",
        today: date | None = None,
    ) -> ContentPackRecord:
        channel = self.config.raw["channel"]
        content = self.config.raw["content"]
        source = str(channel["source_language"])
        level = str(channel["level"])
        words = int(content["words_per_short"])
        turns = int(content["dialogue_turns_per_long"])
        previously_taught = recent_vocabulary(history, playlist.target_language)
        ordinal = (today or date.today()).toordinal() * 2
        topics = [
            playlist.topics[(ordinal + offset + revision - 1) % len(playlist.topics)]
            for offset in range(2)
        ]
        feedback = (
            "\nThe owner requested this revision. Apply it exactly when it is safe and compatible "
            f"with the guardrails: {revision_feedback}"
            if revision_feedback
            else ""
        )
        prompt = f"""
Create one Talkivana daily content pack for an approval-gated language channel.

Non-negotiable configuration:
- Explanation language: {source}
- Learning language: {playlist.target_language}
- Variety: {playlist.variety}
- Level: {level}
- General-audience and family-safe; not specifically directed at children
- Exactly two Shorts: asset IDs short-1 and short-2
- Exactly two long videos: asset IDs long-1 and long-2
- Pair short-1 with long-1 and short-2 with long-2
- Exactly {words} useful words or verbs in each Short
- Exactly {turns} alternating A/B conversation turns in each long video
- Topics, in pair order: {json.dumps(topics, ensure_ascii=False)}
- Pronunciation: simplified English spelling, never IPA
- Every linked Short vocabulary item must appear verbatim in its long video's German dialogue
- Each dialogue turn is spoken later as English once, German once, then German repeated once
- After the teaching sequence, replay the complete coherent conversation in German only, once
- Each conversation must progress naturally so the final German-only pass works as a single scene
- Apply the Talkivana Language Learning Companion Profile in the repository guardrails to every
  Short, long lesson, tutor-facing line, and conversation
- Build each long conversation around stable speaker roles, one shared practical goal, and a
  complete opening-to-resolution arc; every turn must answer or advance the turn before it
- Use consistent register within each scene (never mix du and Sie), natural German chunks rather
  than word-for-word translation, and CEFR A1 high-frequency language
- Speaker A must start and the dialogue must alternate A/B exactly
- Shorts contain vocabulary and English meaning only; long videos contain conversations/sentences
- Previously taught German terms available for spaced-repetition recycling:
  {json.dumps(previously_taught, ensure_ascii=False)}
- Do not reuse those terms as the three new Short focus items. Recycle one or two in each long
  conversation only when they fit naturally and do not repeat an old scenario.
{feedback}

Make the two scenarios materially different. Use original examples and practical beginner situations.
Do not add subtitles, grammar lectures, calls to subscribe, or claims of fluency.
Follow every repository guardrail below and return only the requested structured object.

{self.guardrails}
""".strip()
        pack = self.client.generate_json(
            model=str(self.config.raw["models"]["text"]),
            prompt=prompt,
            schema=CONTENT_PACK_JSON_SCHEMA,
        )
        self._apply_fixed_fields(pack, playlist)

        qa_prompt = f"""
Act as a strict Standard German bilingual editor and an A1 tutor applying the Talkivana Language
Learning Companion Profile from the guardrails below.
Check every English/German meaning, simplified pronunciation, dialogue, cross-link, spelling,
capitalisation, grammatical gender, verb form, register, originality, family safety, and absolute-
beginner suitability. No dialects are allowed. The Shorts must be vocabulary-only; long videos
must be conversations/sentences. Preserve exactly two of each asset and the configured counts.

For each long video, ignore the English temporarily and read the German dialogue from first to last
as a real scene. Correct it unless it has stable roles, consistent facts and register, adjacent turns
that respond to one another, a practical goal, and a complete opening-to-resolution arc. Reject
isolated textbook lines, unanswered questions, abrupt topic changes, forced vocabulary, and
premature endings. Then verify that every English line exactly matches the corrected German.
Confirm Speaker A starts and A/B alternate exactly. Prefer short, idiomatic, high-frequency A1
chunks; simplify doubtful or advanced language. Record every material correction in problems.

If any item is doubtful, replace it with simpler Standard German. Always return a complete
corrected_pack. approved describes the corrected pack, not the original.

Guardrails:
{self.guardrails}

Pack:
{json.dumps(pack, ensure_ascii=False, indent=2)}
""".strip()
        qa = self.client.generate_json(
            model=str(self.config.raw["models"]["text"]),
            prompt=qa_prompt,
            schema=QA_JSON_SCHEMA,
        )
        corrected = qa.get("corrected_pack")
        if not isinstance(corrected, dict):
            raise ValueError("QA response did not contain corrected_pack.")
        self._apply_fixed_fields(corrected, playlist)
        self._validate(corrected, playlist)
        return build_pack_record(
            corrected,
            revision=revision,
            qa_problems=[str(item) for item in qa.get("problems", [])],
            replacement_for=replacement_for,
            today=today,
        )

    def _apply_fixed_fields(self, pack: dict, playlist: Playlist) -> None:
        """Keep channel configuration authoritative over model-written metadata."""
        pack["source_language"] = str(self.config.raw["channel"]["source_language"])
        pack["target_language"] = playlist.target_language
        pack["language_variety"] = playlist.variety
        pack["level"] = str(self.config.raw["channel"]["level"])

    def _validate(self, pack: dict, playlist: Playlist) -> None:
        validate_content_pack(
            pack,
            source_language=str(self.config.raw["channel"]["source_language"]),
            target_language=playlist.target_language,
            language_variety=playlist.variety,
            words_per_short=int(self.config.raw["content"]["words_per_short"]),
            dialogue_turns_per_long=int(self.config.raw["content"]["dialogue_turns_per_long"]),
        )
