from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import fmean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class PerformanceSample:
    asset_id: str
    format: str
    slot_local: str
    published_at: datetime
    views_24h: int
    views_7d: int
    average_percentage_viewed: float
    subscribers_gained: int = 0
    impressions_ctr: float | None = None
    country: str = ""
    anomalous: bool = False


@dataclass(frozen=True)
class SlotScore:
    format: str
    slot_local: str
    sample_count: int
    score: float
    confidence: str


@dataclass(frozen=True)
class TimingPlan:
    stage: int
    day_number: int
    exploration_ratio: float
    assignments: tuple[tuple[str, str], ...]
    scores: tuple[SlotScore, ...]
    explanation: str


def next_publish_time(
    *,
    timezone_name: str,
    local_time: str,
    minimum_lead_hours: int,
    now: datetime | None = None,
    not_before_date: date | None = None,
) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    try:
        hour, minute = (int(value) for value in local_time.split(":"))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
    except ValueError as exc:
        raise ValueError("local_time must use 24-hour HH:MM") from exc
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    earliest = current.astimezone(zone) + timedelta(hours=minimum_lead_hours)
    target_date = max(earliest.date(), not_before_date or earliest.date())
    candidate = datetime(
        target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=zone
    )
    if candidate < earliest:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def timing_stage(*, launch_date: date, on_date: date, stage_1_days: int = 30, stage_2_days: int = 30) -> tuple[int, int]:
    day_number = max(1, (on_date - launch_date).days + 1)
    if day_number <= stage_1_days:
        return 1, day_number
    if day_number <= stage_1_days + stage_2_days:
        return 2, day_number
    return 3, day_number


def score_slots(
    samples: list[PerformanceSample],
    *,
    slots: list[str],
    formats: tuple[str, ...] = ("short", "long"),
    minimum_samples: int = 4,
) -> tuple[SlotScore, ...]:
    scores: list[SlotScore] = []
    clean = [sample for sample in samples if not sample.anomalous]
    for format_name in formats:
        for slot in slots:
            group = [
                sample for sample in clean
                if sample.format == format_name and sample.slot_local == slot
            ]
            if not group:
                scores.append(SlotScore(format_name, slot, 0, 0.0, "insufficient"))
                continue
            views_24 = [max(0, sample.views_24h) for sample in group]
            views_7d = [max(0, sample.views_7d) for sample in group]
            completion = [max(0.0, min(100.0, sample.average_percentage_viewed)) for sample in group]
            subscribers = [max(0, sample.subscribers_gained) for sample in group]
            ctr = [
                max(0.0, min(100.0, sample.impressions_ctr))
                for sample in group if sample.impressions_ctr is not None
            ]
            # Relative ranking matters more than absolute scale. Log-like caps prevent one viral
            # upload from overwhelming the schedule before there is repeatable evidence.
            v24 = min(100.0, fmean(views_24) ** 0.5 * 10)
            v7 = min(100.0, fmean(views_7d) ** 0.5 * 6)
            retention = fmean(completion)
            sub_score = min(100.0, fmean(subscribers) * 20)
            ctr_score = fmean(ctr) * 10 if ctr else retention
            score = round(0.25 * v24 + 0.20 * v7 + 0.35 * retention + 0.10 * sub_score + 0.10 * ctr_score, 3)
            count = len(group)
            confidence = "sufficient" if count >= minimum_samples else "provisional"
            scores.append(SlotScore(format_name, slot, count, score, confidence))
    return tuple(scores)


def build_timing_plan(
    *,
    launch_date: date,
    on_date: date,
    slots: list[str],
    samples: list[PerformanceSample],
    stage_1_days: int = 30,
    stage_2_days: int = 30,
    stage_2_exploration_ratio: float = 0.30,
    stage_3_exploration_ratio: float = 0.15,
    minimum_samples: int = 4,
) -> TimingPlan:
    if len(slots) != 4:
        raise ValueError("Exactly four separated daily slots are required.")
    stage, day_number = timing_stage(
        launch_date=launch_date,
        on_date=on_date,
        stage_1_days=stage_1_days,
        stage_2_days=stage_2_days,
    )
    scores = score_slots(samples, slots=slots, minimum_samples=minimum_samples)
    if stage == 1:
        exploration = 1.0
    elif stage == 2:
        exploration = stage_2_exploration_ratio
    else:
        exploration = stage_3_exploration_ratio

    # A deterministic rotation gives every format/slot combination equal early exposure and
    # makes reruns idempotent. Later stages rank slots separately for Shorts and long videos.
    digest = hashlib.sha256(on_date.isoformat().encode()).digest()[0]
    rotation = (on_date.toordinal() + digest) % len(slots)
    rotated = slots[rotation:] + slots[:rotation]
    if stage == 1:
        assignments = (
            ("short-1", rotated[0]), ("long-1", rotated[1]),
            ("short-2", rotated[2]), ("long-2", rotated[3]),
        )
        explanation = "Stage 1: balanced exploration across all four separated slots."
    else:
        ranked: dict[str, list[str]] = {}
        for format_name in ("short", "long"):
            format_scores = [item for item in scores if item.format == format_name]
            ranked[format_name] = [
                item.slot_local
                for item in sorted(
                    format_scores,
                    key=lambda item: (item.confidence == "sufficient", item.score, item.sample_count),
                    reverse=True,
                )
            ]
        # Preserve four unique daily slots. Best supported slots are preferred; a deterministic
        # exploration position rotates through the remainder.
        chosen: list[str] = []
        for format_name in ("short", "long", "short", "long"):
            candidates = ranked[format_name]
            choice = next((slot for slot in candidates if slot not in chosen), None)
            if choice is None:
                choice = next(slot for slot in rotated if slot not in chosen)
            chosen.append(choice)
        explore_today = ((on_date.toordinal() % 100) / 100) < exploration
        if explore_today:
            chosen = chosen[1:] + chosen[:1]
        assignments = (
            ("short-1", chosen[0]), ("long-1", chosen[1]),
            ("short-2", chosen[2]), ("long-2", chosen[3]),
        )
        explanation = (
            f"Stage {stage}: {'controlled exploration' if explore_today else 'evidence-weighted exploitation'} "
            f"with a {exploration:.0%} exploration policy."
        )
    return TimingPlan(stage, day_number, exploration, assignments, scores, explanation)
