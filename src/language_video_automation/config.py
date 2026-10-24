from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Playlist:
    enabled: bool
    target_language: str
    variety: str
    youtube_playlist_id: str
    topics: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any]
    path: Path

    @property
    def enabled(self) -> bool:
        return bool(self.raw["system"]["enabled"])

    @property
    def approver_login(self) -> str:
        return str(self.raw["approval"]["approver_login"])

    @property
    def playlists(self) -> tuple[Playlist, ...]:
        return tuple(
            Playlist(
                enabled=bool(item.get("enabled", False)),
                target_language=str(item.get("target_language", "")).strip(),
                variety=str(item.get("variety", "")).strip(),
                youtube_playlist_id=str(item.get("youtube_playlist_id", "")).strip(),
                topics=tuple(str(topic).strip() for topic in item.get("topics", []) if str(topic).strip()),
            )
            for item in self.raw["playlists"]
        )

    @property
    def active_playlists(self) -> tuple[Playlist, ...]:
        return tuple(item for item in self.playlists if item.enabled)

    def choose_playlist(self, ordinal: int) -> Playlist:
        if not self.active_playlists:
            raise ConfigurationError("No enabled target-language playlist is configured.")
        return self.active_playlists[ordinal % len(self.active_playlists)]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(path: str | Path | None = None, *, require_enabled: bool = False) -> AppConfig:
    config_path = Path(path) if path else project_root() / "config" / "channel.json"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Configuration JSON is invalid: {exc}") from exc
    _validate_shape(raw)
    config = AppConfig(raw=raw, path=config_path)
    if require_enabled:
        validate_production_config(config)
    return config


def _clock_minutes(value: str) -> int:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid local time {value!r}; use HH:MM.") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigurationError(f"Invalid local time {value!r}; use HH:MM.")
    return hour * 60 + minute


def _validate_shape(raw: dict[str, Any]) -> None:
    required = {
        "system", "approval", "channel", "playlists", "content", "models",
        "video", "brand", "youtube", "timing_agent",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ConfigurationError(f"Missing configuration sections: {', '.join(missing)}")
    if raw["system"].get("schema_version") != 2:
        raise ConfigurationError("Unsupported configuration schema_version; expected 2.")
    if not isinstance(raw["playlists"], list) or not raw["playlists"]:
        raise ConfigurationError("playlists must be a non-empty list.")

    content = raw["content"]
    if int(content.get("shorts_per_day", 0)) != 2 or int(content.get("long_videos_per_day", 0)) != 2:
        raise ConfigurationError("Talkivana is configured for exactly two Shorts and two long videos per day.")
    if not 1 <= int(content.get("words_per_short", 0)) <= 6:
        raise ConfigurationError("words_per_short must be between 1 and 6.")
    if not 6 <= int(content.get("dialogue_turns_per_long", 0)) <= 16:
        raise ConfigurationError("dialogue_turns_per_long must be between 6 and 16.")

    for format_name in ("short", "long"):
        spec = raw["video"].get(format_name, {})
        width, height = int(spec.get("width", 0)), int(spec.get("height", 0))
        if width < 640 or height < 360:
            raise ConfigurationError(f"video.{format_name} dimensions are too small.")
        minimum = int(spec.get("minimum_seconds", 0))
        target = int(spec.get("target_seconds", 0))
        maximum = int(spec.get("maximum_seconds", 0))
        if not 15 <= minimum <= target <= maximum <= 600:
            raise ConfigurationError(
                f"video.{format_name} duration must satisfy 15 <= minimum <= target <= maximum <= 600."
            )
    if int(raw["video"]["short"]["height"]) <= int(raw["video"]["short"]["width"]):
        raise ConfigurationError("Shorts must use a vertical frame.")
    if int(raw["video"]["long"]["width"]) <= int(raw["video"]["long"]["height"]):
        raise ConfigurationError("Long videos must use a horizontal frame.")

    pending = int(raw["system"].get("max_pending_packs", 0))
    if not 1 <= pending <= 14:
        raise ConfigurationError("max_pending_packs must be between 1 and 14.")
    dry_run_asset = str(raw["system"].get("dry_run_asset_id", "")).strip()
    if dry_run_asset not in {"", "short-1", "short-2", "long-1", "long-2"}:
        raise ConfigurationError("dry_run_asset_id must be empty or a known Talkivana asset ID.")
    if not 1 <= int(raw["approval"].get("quick_preview_seconds", 0)) <= 60:
        raise ConfigurationError("quick_preview_seconds must be between 1 and 60.")

    slots = [str(item) for item in raw["youtube"].get("seed_publish_slots_local", [])]
    if len(slots) != 4 or len(set(slots)) != 4:
        raise ConfigurationError("Exactly four distinct seed publishing slots are required.")
    minutes = sorted(_clock_minutes(slot) for slot in slots)
    circular_gaps = [
        minutes[index + 1] - minutes[index] for index in range(len(minutes) - 1)
    ] + [24 * 60 - minutes[-1] + minutes[0]]
    minimum_gap = int(raw["youtube"].get("minimum_slot_gap_minutes", 0))
    if min(circular_gaps) < minimum_gap:
        raise ConfigurationError("Publishing slots are too close together.")
    try:
        ZoneInfo(str(raw["youtube"]["timezone"]))
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError("youtube.timezone is unknown.") from exc

    if bool(raw["youtube"].get("made_for_kids")):
        raise ConfigurationError("Talkivana was approved as general-audience, not made-for-kids.")
    if bool(content.get("burned_in_subtitles")) or bool(content.get("youtube_closed_captions")):
        raise ConfigurationError("Subtitles are disabled by the approved Talkivana specification.")


def validate_production_config(config: AppConfig) -> None:
    if not config.enabled:
        raise ConfigurationError("Production is locked because system.enabled is false.")
    if config.approver_login != "Indusvalley7":
        raise ConfigurationError("approval.approver_login must remain Indusvalley7.")
    if str(config.raw["channel"].get("name")) != "Talkivana":
        raise ConfigurationError("channel.name must remain Talkivana.")
    if not config.active_playlists:
        raise ConfigurationError("At least one playlist must be enabled.")
    for playlist in config.active_playlists:
        if playlist.target_language != "German":
            raise ConfigurationError("The trial supports only German.")
        if "standard german" not in playlist.variety.casefold() or "dialect" not in playlist.variety.casefold():
            raise ConfigurationError("The German playlist must explicitly require Standard German and exclude dialects.")
        if not playlist.topics:
            raise ConfigurationError("The German playlist needs topics.")
        if not playlist.youtube_playlist_id:
            raise ConfigurationError("The enabled German playlist needs its YouTube playlist ID.")
    if not str(config.raw["models"].get("text", "")).strip():
        raise ConfigurationError("models.text is required.")
    if not str(config.raw["models"].get("tts", "")).strip():
        raise ConfigurationError("models.tts is required.")
    if str(config.raw["models"].get("tts_provider", "")) != "chatterbox":
        raise ConfigurationError("models.tts_provider must remain chatterbox.")
    settings = config.raw["models"].get("tts_settings", {})
    if bool(settings.get("automatic_voice_fallback", True)):
        raise ConfigurationError("Automatic TTS voice fallback must remain disabled.")
    if str(settings.get("model_version", "")) != "v3":
        raise ConfigurationError("The approved multilingual Chatterbox model version must remain v3.")
    german_reference = str(settings.get("german_reference_audio", "")).strip()
    if not german_reference:
        raise ConfigurationError("An approved Standard German narration reference is required.")
    if not bool(settings.get("require_distinct_conversation_voices", False)):
        raise ConfigurationError("Distinct fixed voices are required for final conversations.")
    conversation_voices = settings.get("conversation_voice_references", {})
    if not isinstance(conversation_voices, dict):
        raise ConfigurationError("conversation_voice_references must map speaker labels to files.")
    initial_references = [str(conversation_voices.get(speaker, "")).strip() for speaker in ("A", "B")]
    if not all(initial_references):
        raise ConfigurationError("Approved reference voices for speakers A and B are required.")
    if len(set(initial_references)) != len(initial_references):
        raise ConfigurationError("Speakers A and B must use different reference voices.")


def load_guardrails() -> str:
    root = project_root()
    files = [root / "GUARDRAILS.md", *sorted((root / "guardrails").glob("*.md"))]
    return "\n\n".join(path.read_text(encoding="utf-8") for path in files)
