from __future__ import annotations

import hashlib
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from .gemini import GeminiClient
from .models import ContentPackRecord


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class NarrationSegment:
    eyebrow: str
    title: str
    body: str
    transcript: str
    spoken_language: str
    pause_seconds: float
    accent: str
    display_mode: str = "intro"
    english_text: str = ""
    german_text: str = ""
    pronunciation: str = ""
    speaker: str = ""
    active_language: str = ""
    cue_text: str = ""


@dataclass(frozen=True)
class AssetRenderResult:
    asset_id: str
    kind: str
    title: str
    video_path: Path
    preview_path: Path
    thumbnail_path: Path
    duration_seconds: float
    segment_count: int


@dataclass(frozen=True)
class PackRenderResult:
    assets: tuple[AssetRenderResult, ...]
    unique_tts_requests: int


class SpeechProvider(Protocol):
    request_count: int

    def synthesize(self, segment: NarrationSegment, output_path: Path) -> None: ...


class GeminiSpeechProvider:
    def __init__(self, client: GeminiClient, *, model: str, voice: str) -> None:
        self.client = client
        self.model = model
        self.voice = voice

    @property
    def request_count(self) -> int:
        return self.client.request_count

    def synthesize(self, segment: NarrationSegment, output_path: Path) -> None:
        self.client.synthesize_wav(
            model=self.model,
            voice=self.voice,
            transcript=segment.transcript,
            language=segment.spoken_language,
            output_path=output_path,
        )


class ChatterboxSpeechProvider:
    """Pinned, local multilingual narration with no API or automatic voice fallback."""

    def __init__(
        self,
        *,
        model_version: str = "v3",
        device: str = "auto",
        seed: int = 271828,
        exaggeration: float = 0.65,
        cfg_weight: float = 0.35,
        english_reference_audio: str = "",
        german_reference_audio: str = "",
    ) -> None:
        self.model_version = model_version
        self.requested_device = device
        self.seed = seed
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight
        self.reference_audio = {
            "English": english_reference_audio,
            "German": german_reference_audio,
        }
        self.request_count = 0
        self._model: Any | None = None
        self._torch: Any | None = None
        self._torchaudio: Any | None = None
        self._device = ""

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            import torchaudio
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError as exc:
            raise RenderError(
                "Chatterbox narration is not installed. Install the project with the [tts] extra."
            ) from exc
        if self.requested_device != "auto":
            device = self.requested_device
        elif torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
        self._device = device
        self._torch = torch
        self._torchaudio = torchaudio
        try:
            self._model = ChatterboxMultilingualTTS.from_pretrained(
                device=device,
                t3_model=self.model_version,
            )
        except Exception as exc:
            raise RenderError(f"Unable to load pinned Chatterbox {self.model_version} model.") from exc

    def synthesize(self, segment: NarrationSegment, output_path: Path) -> None:
        self._load()
        assert self._model is not None
        assert self._torch is not None
        assert self._torchaudio is not None
        language = segment.spoken_language.casefold()
        language_id = "de" if language == "german" else "en"
        reference = self.reference_audio["German" if language_id == "de" else "English"]
        if reference and not Path(reference).is_file():
            raise RenderError(f"Configured Chatterbox reference audio does not exist: {reference}")

        # A content-derived seed keeps approved lines reproducible across fresh runners.
        digest = hashlib.sha256(
            f"{self.seed}\0{language_id}\0{segment.transcript}".encode("utf-8")
        ).digest()
        utterance_seed = int.from_bytes(digest[:4], "big")
        self._torch.manual_seed(utterance_seed)
        if self._device == "cuda":
            self._torch.cuda.manual_seed_all(utterance_seed)

        kwargs: dict[str, Any] = {
            "language_id": language_id,
            "exaggeration": self.exaggeration,
            "cfg_weight": self.cfg_weight,
        }
        if reference:
            kwargs["audio_prompt_path"] = reference
        try:
            waveform = self._model.generate(segment.transcript, **kwargs)
        except Exception as exc:
            raise RenderError(
                f"Chatterbox failed to synthesize {segment.spoken_language} narration."
            ) from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=".wav", prefix="talkivana-chatterbox-", dir=output_path.parent, delete=False
        ) as temporary:
            raw_path = Path(temporary.name)
        try:
            self._torchaudio.save(
                str(raw_path), waveform.detach().cpu(), int(self._model.sr)
            )
            converted = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(raw_path), "-ac", "1", "-ar", "24000",
                    "-c:a", "pcm_s16le", str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if converted.returncode != 0:
                raise RenderError(f"Chatterbox audio conversion failed: {converted.stderr[-800:]}")
        finally:
            raw_path.unlink(missing_ok=True)
        self.request_count += 1


class TestToneSpeechProvider:
    """Deterministic tone for automated tests only; never use in a review copy."""

    def __init__(self) -> None:
        self.request_count = 0

    def synthesize(self, segment: NarrationSegment, output_path: Path) -> None:
        self.request_count += 1
        words = max(1, len(segment.transcript.split()))
        duration = max(0.8, words / 145 * 60)
        sample_rate = 24_000
        frame_count = int(duration * sample_rate)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(sample_rate)
            frames = bytearray()
            for index in range(frame_count):
                envelope = min(1.0, index / 500, (frame_count - index) / 500)
                sample = int(1200 * envelope * math.sin(2 * math.pi * 220 * index / sample_rate))
                frames.extend(struct.pack("<h", sample))
            stream.writeframes(frames)


class MacSpeechProvider:
    """Local spoken preview provider. Production continues to use Gemini TTS in GitHub."""

    def __init__(
        self,
        *,
        english_voice: str = "Flo (English (US))",
        german_voice: str = "Flo (German (Germany))",
        words_per_minute: int = 172,
    ) -> None:
        if not shutil.which("say"):
            raise RenderError("The spoken local demo requires macOS 'say'.")
        self.english_voice = english_voice
        self.german_voice = german_voice
        self.words_per_minute = words_per_minute
        self.request_count = 0

    def synthesize(self, segment: NarrationSegment, output_path: Path) -> None:
        self.request_count += 1
        voice = (
            self.german_voice
            if segment.spoken_language.casefold() == "german"
            else self.english_voice
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=".aiff", prefix="talkivana-", dir=output_path.parent, delete=False
        ) as temporary:
            aiff_path = Path(temporary.name)
        try:
            spoken = subprocess.run(
                [
                    "say", "-v", voice, "-r", str(self.words_per_minute),
                    "-o", str(aiff_path), segment.transcript,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if spoken.returncode != 0:
                raise RenderError(f"macOS speech failed: {spoken.stderr[-800:]}")
            converted = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(aiff_path), "-ac", "1", "-ar", "24000",
                    "-c:a", "pcm_s16le", str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if converted.returncode != 0:
                raise RenderError(f"Speech conversion failed: {converted.stderr[-800:]}")
        finally:
            aiff_path.unlink(missing_ok=True)


def build_asset_timeline(pack: dict[str, Any], asset: dict[str, Any], kind: str) -> list[NarrationSegment]:
    if kind == "short":
        return _short_timeline(pack, asset)
    if kind == "long":
        return _long_timeline(pack, asset)
    raise RenderError(f"Unknown asset kind: {kind}")


def _short_timeline(pack: dict[str, Any], asset: dict[str, Any]) -> list[NarrationSegment]:
    target = str(pack["target_language"])
    segments = [
        NarrationSegment(
            eyebrow="TALKIVANA • BEGINNER",
            title=str(asset["title"]),
            body="English first • German twice",
            transcript=f"{asset['title']}. Listen, then repeat.",
            spoken_language="English",
            pause_seconds=0.7,
            accent="secondary",
            display_mode="intro",
        )
    ]
    total = len(asset["vocabulary"])
    for index, item in enumerate(asset["vocabulary"], start=1):
        shared = {
            "english_text": str(item["english"]),
            "german_text": str(item["german"]),
            "pronunciation": str(item["pronunciation"]),
            "display_mode": "lesson",
        }
        segments.extend(
            [
                NarrationSegment(
                    eyebrow=f"WORD {index} OF {total}",
                    title=str(item["english"]),
                    body="English first",
                    transcript=str(item["english"]),
                    spoken_language="English",
                    pause_seconds=0.8,
                    accent="primary",
                    active_language="English",
                    **shared,
                ),
                NarrationSegment(
                    eyebrow=f"WORD {index} OF {total}",
                    title=str(item["german"]),
                    body=f"Say it like: {item['pronunciation']}",
                    transcript=str(item["german"]),
                    spoken_language=target,
                    pause_seconds=1.4,
                    accent="accent",
                    active_language="German",
                    **shared,
                ),
                NarrationSegment(
                    eyebrow=f"WORD {index} OF {total} • REPEAT",
                    title=str(item["german"]),
                    body="Listen again, then repeat aloud",
                    transcript=str(item["german"]),
                    spoken_language=target,
                    pause_seconds=4.0,
                    accent="secondary",
                    active_language="German",
                    **shared,
                ),
            ]
        )
    return segments


def _long_timeline(pack: dict[str, Any], asset: dict[str, Any]) -> list[NarrationSegment]:
    target = str(pack["target_language"])
    segments = [
        NarrationSegment(
            eyebrow="TALKIVANA • ABSOLUTE BEGINNER",
            title=str(asset["title"]),
            body=str(asset["learning_objective"]),
            transcript=(
                f"Welcome to Talkivana! Today, {asset['learning_objective'].lower()} "
                "I will guide you one sentence at a time. First, listen to the English meaning. "
                "Then you will hear the German twice, with time to repeat it aloud. Let's begin!"
            ),
            spoken_language="English",
            pause_seconds=2.0,
            accent="secondary",
            display_mode="intro",
        )
    ]
    total = len(asset["dialogue"])
    lead_ins = (
        "Let's begin with the English meaning.",
        "Nice start! Here is the next line in English.",
        "Now let's add another useful sentence.",
        "Good progress! Listen to the next English line.",
        "Let's continue with the next part of the conversation.",
    )
    german_cues = (
        "Now listen to the same idea in German.",
        "Here is how that sounds in German.",
        "Now hear the German sentence.",
    )
    for index, turn in enumerate(asset["dialogue"], start=1):
        speaker = f"SPEAKER {turn['speaker']}"
        shared = {
            "english_text": str(turn["english"]),
            "german_text": str(turn["german"]),
            "pronunciation": str(turn["pronunciation"]),
            "speaker": str(turn["speaker"]),
            "display_mode": "lesson",
        }
        segments.extend(
            [
                NarrationSegment(
                    eyebrow=f"LESSON {index} OF {total} • TUTOR",
                    title=str(turn["english"]),
                    body=lead_ins[(index - 1) % len(lead_ins)],
                    transcript=lead_ins[(index - 1) % len(lead_ins)],
                    spoken_language="English",
                    pause_seconds=0.25,
                    accent="primary",
                    active_language="English",
                    cue_text="TUTOR GUIDANCE",
                    **shared,
                ),
                NarrationSegment(
                    eyebrow=f"LESSON {index} OF {total} • {speaker}",
                    title=str(turn["english"]),
                    body="English first",
                    transcript=str(turn["english"]),
                    spoken_language="English",
                    pause_seconds=0.55,
                    accent="primary" if turn["speaker"] == "A" else "secondary",
                    active_language="English",
                    cue_text="LISTEN",
                    **shared,
                ),
                NarrationSegment(
                    eyebrow=f"LESSON {index} OF {total} • TUTOR",
                    title=str(turn["german"]),
                    body="Pronunciation coaching",
                    transcript=(
                        f"{german_cues[(index - 1) % len(german_cues)]} "
                        f"A simple pronunciation guide is: {turn['pronunciation']}."
                    ),
                    spoken_language="English",
                    pause_seconds=0.3,
                    accent="accent",
                    active_language="German",
                    cue_text="PRONUNCIATION TIP",
                    **shared,
                ),
                NarrationSegment(
                    eyebrow=f"LESSON {index} OF {total} • {speaker}",
                    title=str(turn["german"]),
                    body=f"Pronunciation: {turn['pronunciation']}",
                    transcript=str(turn["german"]),
                    spoken_language=target,
                    pause_seconds=0.8,
                    accent="accent",
                    active_language="German",
                    cue_text="LISTEN",
                    **shared,
                ),
                NarrationSegment(
                    eyebrow=f"LESSON {index} OF {total} • TUTOR",
                    title=str(turn["german"]),
                    body="Guided repetition",
                    transcript="Excellent! Listen once more, then repeat the German aloud.",
                    spoken_language="English",
                    pause_seconds=0.3,
                    accent="secondary",
                    active_language="German",
                    cue_text="GET READY TO REPEAT",
                    **shared,
                ),
                NarrationSegment(
                    eyebrow=f"LESSON {index} OF {total} • REPEAT",
                    title=str(turn["german"]),
                    body="Listen again, then repeat aloud",
                    transcript=str(turn["german"]),
                    spoken_language=target,
                    pause_seconds=min(5.0, 2.4 + 0.35 * len(str(turn["german"]).split())),
                    accent="secondary",
                    active_language="German",
                    cue_text="REPEAT ALOUD",
                    **shared,
                ),
            ]
        )
        if index < total and index % 4 == 0:
            segments.append(
                NarrationSegment(
                    eyebrow=f"CHECKPOINT • {index} OF {total}",
                    title="You're making great progress!",
                    body="Keep the German clear, connected, and natural. Let's continue.",
                    transcript=(
                        "You're making great progress! Keep the German clear, connected, "
                        "and natural. Let's continue."
                    ),
                    spoken_language="English",
                    pause_seconds=0.8,
                    accent="primary",
                    display_mode="conversation_intro",
                )
            )
    segments.append(
        NarrationSegment(
            eyebrow="FULL CONVERSATION",
            title="Now listen to the whole conversation",
            body="German only • one natural pass",
            transcript="Now listen to the complete conversation in German.",
            spoken_language="English",
            pause_seconds=2.0,
            accent="primary",
            display_mode="conversation_intro",
        )
    )
    for index, turn in enumerate(asset["dialogue"], start=1):
        segments.append(
            NarrationSegment(
                eyebrow=f"FULL CONVERSATION • {index} OF {total}",
                title=str(turn["german"]),
                body="German only",
                transcript=str(turn["german"]),
                spoken_language=target,
                pause_seconds=0.9,
                accent="primary" if turn["speaker"] == "A" else "secondary",
                display_mode="conversation",
                german_text=str(turn["german"]),
                speaker=str(turn["speaker"]),
                active_language="German",
            )
        )
    return segments


def render_pack(
    *,
    record: ContentPackRecord,
    config: dict[str, Any],
    speech: SpeechProvider,
    output_dir: Path,
) -> PackRenderResult:
    _require_ffmpeg()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache: dict[str, tuple[Path, float]] = {}
    results: list[AssetRenderResult] = []
    for kind, collection in (("short", record.content["shorts"]), ("long", record.content["long_videos"])):
        for asset in collection:
            results.append(
                render_asset(
                    record=record,
                    asset=asset,
                    kind=kind,
                    config=config,
                    speech=speech,
                    output_dir=output_dir / str(asset["asset_id"]),
                    audio_cache=cache,
                )
            )
    return PackRenderResult(tuple(results), len(cache))


def render_asset(
    *,
    record: ContentPackRecord,
    asset: dict[str, Any],
    kind: str,
    config: dict[str, Any],
    speech: SpeechProvider,
    output_dir: Path,
    audio_cache: dict[str, tuple[Path, float]] | None = None,
) -> AssetRenderResult:
    _require_ffmpeg()
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir.parent / "_audio"
    slide_dir = output_dir / "slides"
    audio_dir.mkdir(exist_ok=True)
    slide_dir.mkdir(exist_ok=True)
    cache = audio_cache if audio_cache is not None else {}
    timeline = build_asset_timeline(record.content, asset, kind)
    spec = config["video"][kind]
    with _workflow_group(f"Voice preparation — {asset['asset_id']}"):
        resolved = _resolve_timeline(timeline, speech, audio_dir, cache)
        resolved = _fit_duration(
            resolved,
            asset=asset,
            kind=kind,
            speech=speech,
            audio_dir=audio_dir,
            cache=cache,
            minimum=float(spec["minimum_seconds"]),
            target=float(spec["target_seconds"]),
            maximum=float(spec["maximum_seconds"]),
            max_practice_pause=float(config["video"].get("max_practice_pause_seconds", 6.0)),
        )
    width, height = int(spec["width"]), int(spec["height"])
    visual_style = _select_visual_style(config["video"].get("visual_style", {}), str(asset["asset_id"]))
    scenes: list[tuple[Path, float]] = []
    with _workflow_group(f"Visual scene preparation — {asset['asset_id']}"):
        for index, (segment, _, audio_duration) in enumerate(resolved):
            scene = slide_dir / f"{index:03d}.png"
            _render_scene(
                segment,
                scene,
                width=width,
                height=height,
                visual_style=visual_style,
                channel_name=str(config["channel"]["name"]),
                pack_id=record.pack_id,
            )
            scenes.append((scene, audio_duration + segment.pause_seconds))
    with _workflow_group(f"Assembly — {asset['asset_id']}"):
        soundtrack = output_dir / "soundtrack.wav"
        _join_audio(resolved, soundtrack)
        concat = output_dir / "slides.ffconcat"
        _write_concat_file(scenes, concat)
        video = output_dir / f"{record.pack_id}-{asset['asset_id']}.mp4"
        _mux_video(
            concat_file=concat,
            soundtrack=soundtrack,
            output=video,
            fps=int(config["video"]["fps"]),
        )
    with _workflow_group(f"Technical QA — {asset['asset_id']}"):
        actual = _probe_duration(video)
        minimum, maximum = float(spec["minimum_seconds"]), float(spec["maximum_seconds"])
        if actual < minimum - 1 or actual > maximum + 1:
            raise RenderError(
                f"{asset['asset_id']} duration {actual:.1f}s is outside {minimum:.0f}-{maximum:.0f}s."
            )
        thumbnail = output_dir / "thumbnail.png"
        shutil.copy2(scenes[0][0], thumbnail)
        preview = output_dir / f"{record.pack_id}-{asset['asset_id']}-preview.mp4"
        _make_preview(video, preview, seconds=int(config["approval"]["quick_preview_seconds"]))
    return AssetRenderResult(
        asset_id=str(asset["asset_id"]),
        kind=kind,
        title=str(asset["title"]),
        video_path=video,
        preview_path=preview,
        thumbnail_path=thumbnail,
        duration_seconds=actual,
        segment_count=len(resolved),
    )


def _select_visual_style(style_config: dict[str, Any], asset_id: str) -> dict[str, str]:
    templates = style_config.get("templates", {})
    order = style_config.get("template_order", [])
    if not isinstance(templates, dict) or not isinstance(order, list) or not order:
        return {str(key): str(value) for key, value in style_config.items()}
    asset_positions = {"long-1": 0, "long-2": 1, "short-1": 2, "short-2": 3}
    position = asset_positions.get(asset_id, 0) % len(order)
    name = str(order[position])
    selected = templates.get(name, {})
    if not isinstance(selected, dict):
        raise RenderError(f"Unknown visual template: {name}")
    return {"template_name": name, **{str(key): str(value) for key, value in selected.items()}}


def _resolve_timeline(
    timeline: list[NarrationSegment],
    speech: SpeechProvider,
    audio_dir: Path,
    cache: dict[str, tuple[Path, float]],
) -> list[tuple[NarrationSegment, Path, float]]:
    return [
        (segment, *_synthesize_cached(segment, speech, audio_dir, cache))
        for segment in timeline
    ]


def _fit_duration(
    resolved: list[tuple[NarrationSegment, Path, float]],
    *,
    asset: dict[str, Any],
    kind: str,
    speech: SpeechProvider,
    audio_dir: Path,
    cache: dict[str, tuple[Path, float]],
    minimum: float,
    target: float,
    maximum: float,
    max_practice_pause: float,
) -> list[tuple[NarrationSegment, Path, float]]:
    total = sum(duration + segment.pause_seconds for segment, _, duration in resolved)
    # Fit the target length by giving the learner intentional response time.
    # Never append duplicate lesson material after the German-only conversation.
    if total < target:
        practice_indexes = [
            index
            for index, (segment, _, _) in enumerate(resolved)
            if segment.display_mode == "lesson" and "REPEAT" in segment.eyebrow
        ]
        if not practice_indexes:
            practice_indexes = [
                index
                for index, (segment, _, _) in enumerate(resolved)
                if segment.display_mode == "lesson"
            ]
        if not practice_indexes:
            raise RenderError("No lesson practice segments are available for duration fitting.")
        remaining = min(target, maximum - 0.25) - total
        while remaining > 0.01:
            eligible = [
                index for index in practice_indexes
                if resolved[index][0].pause_seconds < max_practice_pause - 0.01
            ]
            if not eligible:
                break
            share = remaining / len(eligible)
            added = 0.0
            for index in eligible:
                segment, path, duration = resolved[index]
                increase = min(share, max_practice_pause - segment.pause_seconds)
                resolved[index] = (
                    replace(segment, pause_seconds=segment.pause_seconds + increase),
                    path,
                    duration,
                )
                added += increase
            if added <= 0.01:
                break
            remaining -= added
            total += added
    if total < minimum - 0.5 or total > maximum + 0.5:
        raise RenderError(f"Could not fit asset duration safely ({total:.1f}s).")
    return resolved


def _synthesize_cached(
    segment: NarrationSegment,
    speech: SpeechProvider,
    audio_dir: Path,
    cache: dict[str, tuple[Path, float]],
) -> tuple[Path, float]:
    key = hashlib.sha256(
        f"{segment.spoken_language}\0{segment.transcript}".encode("utf-8")
    ).hexdigest()[:20]
    if key in cache:
        return cache[key]
    path = audio_dir / f"{key}.wav"
    speech.synthesize(segment, path)
    duration = _wav_duration(path)
    if not 0.3 <= duration <= 120:
        raise RenderError(f"Unexpected narration duration {duration:.1f}s.")
    cache[key] = (path, duration)
    return path, duration


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as stream:
            if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != 24_000:
                raise RenderError(f"Narration WAV must be mono 16-bit PCM at 24 kHz: {path}")
            return stream.getnframes() / stream.getframerate()
    except wave.Error as exc:
        raise RenderError(f"Invalid narration WAV: {path}") from exc


def _join_audio(resolved: list[tuple[NarrationSegment, Path, float]], output: Path) -> None:
    sample_rate = 24_000
    with wave.open(str(output), "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        for segment, path, _ in resolved:
            with wave.open(str(path), "rb") as source:
                destination.writeframes(source.readframes(source.getnframes()))
            destination.writeframes(b"\x00\x00" * int(segment.pause_seconds * sample_rate))


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _font(size: int, *, bold: bool = False, text: str = ""):
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/manrope/Manrope-SemiBold.ttf" if bold else "",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _fit_wrapped_font(draw, text: str, *, max_width: int, max_lines: int, start: int, minimum: int, bold: bool):
    size = start
    while size >= minimum:
        font = _font(size, bold=bold, text=text)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines and all(
            draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines
        ):
            return font, lines
        size -= 2
    font = _font(minimum, bold=bold, text=text)
    return font, _wrap(draw, text, font, max_width)[:max_lines]


def _draw_centered_lines(draw, lines, font, *, center_x: int, center_y: int, fill, spacing: int) -> None:
    heights = [draw.textbbox((0, 0), line or " ", font=font)[3] for line in lines]
    total_height = sum(heights) + spacing * max(0, len(lines) - 1)
    y = center_y - total_height // 2
    for line, line_height in zip(lines, heights):
        box = draw.textbbox((0, 0), line, font=font)
        x = center_x - (box[2] - box[0]) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + spacing


def _render_scene(
    segment: NarrationSegment,
    output: Path,
    *,
    width: int,
    height: int,
    visual_style: dict[str, str],
    channel_name: str,
    pack_id: str,
) -> None:
    from PIL import Image, ImageDraw

    background_top = _hex(visual_style.get("background_top", "#F3F1EB"))
    background_bottom = _hex(visual_style.get("background_bottom", "#D9D7D0"))
    foreground = _hex(visual_style.get("foreground", "#FFFFFF"))
    card_text = _hex(visual_style.get("card_text", "#17233C"))
    muted = _hex(visual_style.get("muted", "#D9E8BE"))
    caption = _hex(visual_style.get("caption", "#FFE783"))
    panel = _hex(visual_style.get("panel", "#0D5F63"))
    shape_a = _hex(visual_style.get("shape_a", "#087067"))
    shape_b = _hex(visual_style.get("shape_b", "#39957D"))
    line = _hex(visual_style.get("line", "#74B8A8"))
    shadow = _hex(visual_style.get("shadow", "#173F3C"))
    cue_bg = _hex(visual_style.get("cue_bg", "#0A6764"))
    vertical = height > width

    image = Image.new("RGB", (width, height), background_top)
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / max(1, height - 1)
        colour = tuple(
            int(background_top[index] * (1 - ratio) + background_bottom[index] * ratio)
            for index in range(3)
        )
        draw.line((0, y, width, y), fill=colour)
    draw.ellipse((-int(width * 0.12), -int(height * 0.22), int(width * 0.42), int(height * 0.32)), fill=shape_a)
    draw.ellipse((int(width * 0.76), int(height * 0.65), int(width * 1.18), int(height * 1.15)), fill=shape_b)
    draw.polygon(
        [
            (int(width * 0.50), 0), (width, 0),
            (width, int(height * 0.35)), (int(width * 0.76), int(height * 0.62)),
        ],
        fill=shape_b,
    )
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    panel_margin_x = int(width * (0.08 if vertical else 0.16))
    overlay_draw.rounded_rectangle(
        (panel_margin_x, int(height * 0.105), width - panel_margin_x, int(height * 0.91)),
        radius=max(28, int(min(width, height) * 0.035)),
        fill=(*panel, 150),
        outline=(*line, 95),
        width=max(2, int(width * 0.002)),
    )
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)

    # Fine contour arcs echo the supplied templates without embedding a static image.
    arc_width = max(1, int(width * 0.0012))
    for offset in range(0, int(min(width, height) * 0.20), max(10, int(min(width, height) * 0.016))):
        draw.arc(
            (-int(width * 0.12) - offset, int(height * 0.64) - offset,
             int(width * 0.20) + offset, int(height * 1.04) + offset),
            start=180, end=330, fill=line, width=arc_width,
        )

    margin = int(width * (0.075 if vertical else 0.065))
    brand_font = _font(max(20, int(height * (0.016 if vertical else 0.024))), bold=True)
    meta_font = _font(max(18, int(height * (0.014 if vertical else 0.020))), bold=True)
    small_font = _font(max(18, int(height * (0.016 if vertical else 0.024))))
    draw.text((margin, int(height * 0.045)), channel_name.upper(), font=brand_font, fill=muted)
    meta_width = draw.textbbox((0, 0), segment.eyebrow, font=meta_font)[2]
    draw.text((width - margin - meta_width, int(height * 0.047)), segment.eyebrow, font=meta_font, fill=muted)

    if segment.display_mode == "lesson":
        max_width = int(width * (0.78 if vertical else 0.62))
        english_center = int(height * (0.34 if vertical else 0.32))
        german_center = int(height * (0.62 if vertical else 0.61))
        box_height = int(height * (0.16 if vertical else 0.20))
        radius = max(24, int(min(width, height) * 0.03))
        label_size = max(18, int(height * (0.014 if vertical else 0.020)))
        label_font = _font(label_size, bold=True)
        for label, center in (("ENGLISH", english_center), ("DEUTSCH", german_center)):
            label_width = draw.textbbox((0, 0), label, font=label_font)[2]
            draw.text((width // 2 - label_width // 2, center - box_height // 2 - int(height * 0.045)), label, font=label_font, fill=muted)
        english_font, english_lines = _fit_wrapped_font(
            draw, segment.english_text, max_width=max_width, max_lines=3,
            start=int(height * (0.050 if vertical else 0.064)), minimum=34, bold=True,
        )
        german_font, german_lines = _fit_wrapped_font(
            draw, segment.german_text, max_width=max_width, max_lines=3,
            start=int(height * (0.056 if vertical else 0.071)), minimum=38, bold=True,
        )

        active_center = english_center if segment.active_language == "English" else german_center
        active_lines = english_lines if segment.active_language == "English" else german_lines
        active_font = english_font if segment.active_language == "English" else german_font
        widest = max(draw.textbbox((0, 0), item, font=active_font)[2] for item in active_lines)
        box_width = min(int(width * 0.76), max(int(width * 0.36), widest + int(width * 0.10)))
        box_left = width // 2 - box_width // 2
        box_right = width // 2 + box_width // 2
        shadow_offset = max(8, int(min(width, height) * 0.012))
        draw.rounded_rectangle(
            (box_left + shadow_offset, active_center - box_height // 2 + shadow_offset,
             box_right + shadow_offset, active_center + box_height // 2 + shadow_offset),
            radius=radius, fill=shadow,
        )
        draw.rounded_rectangle(
            (box_left, active_center - box_height // 2, box_right, active_center + box_height // 2),
            radius=radius, fill=caption, outline=muted, width=max(2, int(width * 0.002)),
        )
        _draw_centered_lines(
            draw, english_lines, english_font, center_x=width // 2, center_y=english_center,
            fill=card_text if segment.active_language == "English" else foreground, spacing=10,
        )
        _draw_centered_lines(
            draw, german_lines, german_font, center_x=width // 2, center_y=german_center,
            fill=card_text if segment.active_language == "German" else foreground, spacing=10,
        )
        pronunciation = f"Say it like: {segment.pronunciation}"
        pronunciation_width = draw.textbbox((0, 0), pronunciation, font=small_font)[2]
        draw.text((width // 2 - pronunciation_width // 2, int(height * (0.77 if vertical else 0.77))), pronunciation, font=small_font, fill=muted)
        cue = segment.cue_text or ("LISTEN" if "REPEAT" not in segment.eyebrow else "YOUR TURN")
        cue_width = draw.textbbox((0, 0), cue, font=meta_font)[2]
        cue_y = int(height * 0.85)
        cue_padding_x = int(width * 0.022)
        cue_padding_y = int(height * 0.014)
        draw.rounded_rectangle(
            (width // 2 - cue_width // 2 - cue_padding_x, cue_y - cue_padding_y,
             width // 2 + cue_width // 2 + cue_padding_x,
             cue_y + draw.textbbox((0, 0), cue, font=meta_font)[3] + cue_padding_y),
            radius=max(16, int(height * 0.025)), fill=cue_bg, outline=line,
            width=max(2, int(width * 0.0015)),
        )
        draw.text((width // 2 - cue_width // 2, cue_y), cue, font=meta_font, fill=muted)
    elif segment.display_mode == "conversation":
        caption_left = margin + int(width * 0.04)
        caption_right = width - margin - int(width * 0.04)
        caption_top = int(height * (0.36 if vertical else 0.38))
        caption_bottom = int(height * (0.69 if vertical else 0.72))
        radius = max(28, int(min(width, height) * 0.035))
        draw.rounded_rectangle(
            (caption_left, caption_top, caption_right, caption_bottom),
            radius=radius, fill=caption,
        )
        speaker_label = f"SPEAKER {segment.speaker} • GERMAN"
        speaker_width = draw.textbbox((0, 0), speaker_label, font=meta_font)[2]
        draw.text((width // 2 - speaker_width // 2, caption_top - int(height * 0.07)), speaker_label, font=meta_font, fill=muted)
        conversation_font, conversation_lines = _fit_wrapped_font(
            draw, segment.german_text, max_width=caption_right - caption_left - int(width * 0.08),
            max_lines=4, start=int(height * (0.060 if vertical else 0.075)), minimum=38, bold=True,
        )
        _draw_centered_lines(
            draw, conversation_lines, conversation_font, center_x=width // 2,
            center_y=(caption_top + caption_bottom) // 2, fill=card_text, spacing=12,
        )
    else:
        title_font, title_lines = _fit_wrapped_font(
            draw, segment.title, max_width=width - 2 * margin, max_lines=4,
            start=int(height * (0.060 if vertical else 0.078)), minimum=42, bold=True,
        )
        _draw_centered_lines(
            draw, title_lines, title_font, center_x=width // 2,
            center_y=int(height * 0.46), fill=foreground, spacing=14,
        )
        body_font, body_lines = _fit_wrapped_font(
            draw, segment.body, max_width=width - 2 * margin, max_lines=4,
            start=int(height * (0.026 if vertical else 0.036)), minimum=26, bold=False,
        )
        _draw_centered_lines(
            draw, body_lines, body_font, center_x=width // 2,
            center_y=int(height * 0.66), fill=muted, spacing=10,
        )

    footer = pack_id.split("-")[-1]
    draw.text((margin, int(height * 0.94)), footer, font=small_font, fill=line)
    image.save(output, format="PNG", optimize=True)


def _write_concat_file(slides: list[tuple[Path, float]], output: Path) -> None:
    lines = ["ffconcat version 1.0"]
    for path, duration in slides:
        escaped = str(path.resolve()).replace("'", "'\\''")
        lines.extend((f"file '{escaped}'", f"duration {duration:.6f}"))
    final_path = str(slides[-1][0].resolve()).replace("'", "'\\''")
    lines.append(f"file '{final_path}'")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mux_video(*, concat_file: Path, soundtrack: Path, output: Path, fps: int) -> None:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(soundtrack), "-vf", f"fps={fps},format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-shortest", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1200)
    if result.returncode != 0:
        raise RenderError(f"FFmpeg failed: {result.stderr[-2000:]}")


def _make_preview(source: Path, output: Path, *, seconds: int) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(output),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RenderError(f"Preview creation failed: {result.stderr[-1000:]}")


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed: {result.stderr[-1000:]}")
    return float(result.stdout.strip())


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("ffmpeg and ffprobe are required.")


@contextmanager
def _workflow_group(title: str):
    print(f"::group::{title}", flush=True)
    try:
        yield
    finally:
        print("::endgroup::", flush=True)
