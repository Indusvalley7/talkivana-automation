from __future__ import annotations

import json
from datetime import date

from .config import AppConfig, Playlist, load_guardrails
from .gemini import GeminiClient
from .models import (
    CONTENT_PACK_JSON_SCHEMA,
    QA_JSON_SCHEMA,
    ContentPackRecord,
    ContentValidationError,
    build_pack_record,
    recent_vocabulary,
    validate_content_pack,
)
from .titles import validate_unique_titles


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
        reserved_titles: list[str] | tuple[str, ...] = (),
        today: date | None = None,
    ) -> ContentPackRecord:
        channel = self.config.raw["channel"]
        content = self.config.raw["content"]
        source = str(channel["source_language"])
        level = str(channel["level"])
        words = int(content["words_per_short"])
        turns = int(content["dialogue_turns_per_long"])
        previously_taught = recent_vocabulary(history, playlist.target_language)
        previous_headings = list(dict.fromkeys(str(title) for title in reserved_titles if title))
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
- Every linked Short vocabulary item must reappear naturally in its long video's German dialogue.
  Natural article/case changes, noun plurals, and ordinary verb conjugation are allowed; never
  distort German merely to reproduce a dictionary form verbatim.
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
- Titles already used by uploaded, scheduled, or published Talkivana videos:
  {json.dumps(previous_headings, ensure_ascii=False)}
- Do not reuse those terms as the three new Short focus items. Recycle one or two in each long
  conversation only when they fit naturally and do not repeat an old scenario.
- Give all four assets specific, audience-friendly headings. No heading may duplicate or closely
  imitate a previous heading. Changing singular/plural, adding "German", or swapping generic
  words such as "vocabulary", "lesson", or "video" does not make a title distinct.
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
        qa_problems = [str(item) for item in qa.get("problems", [])]
        corrected, repair_problems = self._repair_validation_errors(
            corrected,
            playlist=playlist,
            reserved_titles=previous_headings,
            maximum_attempts=3,
        )
        qa_problems.extend(repair_problems)
        corrected, audit_problems = self._audit_conversation_naturalness(
            corrected,
            playlist=playlist,
        )
        qa_problems.extend(audit_problems)
        corrected, final_repair_problems = self._repair_validation_errors(
            corrected,
            playlist=playlist,
            reserved_titles=previous_headings,
            maximum_attempts=3,
        )
        qa_problems.extend(final_repair_problems)
        return build_pack_record(
            corrected,
            revision=revision,
            qa_problems=qa_problems,
            replacement_for=replacement_for,
            today=today,
        )

    def _apply_fixed_fields(self, pack: dict, playlist: Playlist) -> None:
        """Keep channel configuration authoritative over model-written metadata."""
        pack["source_language"] = str(self.config.raw["channel"]["source_language"])
        pack["target_language"] = playlist.target_language
        pack["language_variety"] = playlist.variety
        pack["level"] = str(self.config.raw["channel"]["level"])

    def _repair_validation_errors(
        self,
        pack: dict,
        *,
        playlist: Playlist,
        reserved_titles: list[str] | tuple[str, ...],
        maximum_attempts: int,
    ) -> tuple[dict, list[str]]:
        """Give the tutor reviewer a bounded chance to repair schema-level content defects."""
        corrected = pack
        problems: list[str] = []
        for attempt in range(1, maximum_attempts + 1):
            try:
                self._validate(corrected, playlist, reserved_titles=reserved_titles)
                return corrected, problems
            except ContentValidationError as exc:
                if attempt == maximum_attempts:
                    raise
                validation_error = str(exc)

            repair_prompt = f"""
Act as the final Talkivana Language Learning Companion repair editor. The otherwise reviewed pack
failed deterministic validation for these exact reasons:

{validation_error}

Return a complete corrected pack. Fix every listed defect while preserving all valid content,
natural CEFR A1 Standard German, stable speaker roles, consistent du/Sie register, and the complete
opening-to-resolution conversation arc. A linked vocabulary item's `german` value must occur as one
recognisable natural word-family form in its linked dialogue. Article/case changes, noun plurals,
and normal verb conjugation are valid; an unrelated word is not. If a selected item cannot occur
naturally, change it in both the Short and focus_vocabulary and use the replacement in the scene.
Speaker A starts and all 12 turns alternate A/B exactly.
All four titles must also remain distinct from these existing audience-facing titles:
{json.dumps(list(reserved_titles), ensure_ascii=False)}
Record each material repair in problems. Do not merely explain the error.

Guardrails:
{self.guardrails}

Pack to repair:
{json.dumps(corrected, ensure_ascii=False, indent=2)}
""".strip()
            repair = self.client.generate_json(
                model=str(self.config.raw["models"]["text"]),
                prompt=repair_prompt,
                schema=QA_JSON_SCHEMA,
            )
            replacement = repair.get("corrected_pack")
            if not isinstance(replacement, dict):
                raise ValueError("Validation-repair response did not contain corrected_pack.")
            corrected = replacement
            self._apply_fixed_fields(corrected, playlist)
            problems.append(f"Deterministic validation repair: {validation_error}")
            problems.extend(str(item) for item in repair.get("problems", []))

        raise AssertionError("Validation repair loop ended unexpectedly.")

    def _audit_conversation_naturalness(
        self,
        pack: dict,
        *,
        playlist: Playlist,
    ) -> tuple[dict, list[str]]:
        """Run a separate adversarial audit for pragmatic, role-level naturalness."""
        audit_prompt = f"""
Act as the final adversarial Talkivana conversation auditor. An earlier editor already checked
grammar, so assume it may still have missed artificial textbook dialogue or a phrase inserted only
to satisfy vocabulary matching. Apply the Language Learning Companion Profile rigorously.

For each long lesson:
1. Identify the two roles and their single practical goal.
2. Read only the German turns as one uninterrupted real-world scene.
3. Check that each utterance is something that specific role would naturally say at that moment.
4. Check that questions receive relevant answers, facts remain consistent, and the practical goal
   is resolved before a natural closing.
5. Reject word-for-word English structures, semantic nonsense, weakly related focus vocabulary,
   and German manufactured solely to contain an exact term.

Examples of defects that must be rewritten, not accepted:
- `Was kostet das Zahlen?` is not a natural way to ask a purchase price or request payment. A
  natural scene separates `Was kostet das?` from a line such as `Ich möchte zahlen.`
- A passenger should ask for a departure time or platform; telling station staff to look at a clock
  is not a plausible information request.
- A seller naturally asks `Ist das alles?`, not a literal English-shaped construction when a more
  idiomatic Standard German question is available.

If a focus item causes artificial dialogue, replace it in the Short and focus_vocabulary with a
more central A1 item, then use its natural word-family form. Preserve exactly two Shorts,
two long lessons, three linked vocabulary items per pair, and 12 alternating A/B turns beginning
with A. Keep the approved asset IDs and metadata fields. Return the complete corrected pack and
record every material correction in problems. Do not return the pack unchanged unless both German
scenes pass every pragmatic test above.

Guardrails:
{self.guardrails}

Pack to audit:
{json.dumps(pack, ensure_ascii=False, indent=2)}
""".strip()
        audit = self.client.generate_json(
            model=str(self.config.raw["models"]["text"]),
            prompt=audit_prompt,
            schema=QA_JSON_SCHEMA,
        )
        corrected = audit.get("corrected_pack")
        if not isinstance(corrected, dict):
            raise ValueError("Naturalness-audit response did not contain corrected_pack.")
        self._apply_fixed_fields(corrected, playlist)
        return corrected, [str(item) for item in audit.get("problems", [])]

    def _validate(
        self,
        pack: dict,
        playlist: Playlist,
        *,
        reserved_titles: list[str] | tuple[str, ...] = (),
    ) -> None:
        validate_content_pack(
            pack,
            source_language=str(self.config.raw["channel"]["source_language"]),
            target_language=playlist.target_language,
            language_variety=playlist.variety,
            words_per_short=int(self.config.raw["content"]["words_per_short"]),
            dialogue_turns_per_long=int(self.config.raw["content"]["dialogue_turns_per_long"]),
        )
        validate_unique_titles(pack, reserved_titles=reserved_titles)
