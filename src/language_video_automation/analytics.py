from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .config import AppConfig
from .github_api import GitHubClient, Issue, read_upload_manifest
from .scheduling import PerformanceSample, build_timing_plan


TIMING_DATA_START = "<!-- TALKIVANA_TIMING_DATA_START"
TIMING_DATA_END = "TALKIVANA_TIMING_DATA_END -->"
TIMING_ISSUE_TITLE = "Talkivana Audience Timing Agent"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"


class AnalyticsError(RuntimeError):
    pass


class YouTubeAnalyticsClient:
    def __init__(self) -> None:
        values = {
            "client_id": os.environ.get("YOUTUBE_CLIENT_ID", ""),
            "client_secret": os.environ.get("YOUTUBE_CLIENT_SECRET", ""),
            "refresh_token": os.environ.get("YOUTUBE_REFRESH_TOKEN", ""),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise AnalyticsError(f"Missing YouTube credentials: {', '.join(missing)}")
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise AnalyticsError("Google API dependencies are not installed.") from exc
        credentials = Credentials(
            token=None,
            refresh_token=values["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=values["client_id"],
            client_secret=values["client_secret"],
            scopes=[YOUTUBE_SCOPE, ANALYTICS_SCOPE],
        )
        self.service = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)

    def video_metrics(self, *, video_id: str, start_date: date, end_date: date) -> dict[str, float]:
        if end_date < start_date:
            return {}
        metrics = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained"
        try:
            response = self.service.reports().query(
                ids="channel==MINE",
                startDate=start_date.isoformat(),
                endDate=end_date.isoformat(),
                metrics=metrics,
                dimensions="video",
                filters=f"video=={video_id}",
            ).execute()
        except Exception as exc:
            raise AnalyticsError(f"Analytics query failed for {video_id}: {exc}") from exc
        rows = response.get("rows") or []
        if not rows:
            return {}
        headers = [column["name"] for column in response.get("columnHeaders", [])]
        row = dict(zip(headers, rows[0]))
        return {name: float(value) for name, value in row.items() if name != "video"}


def run_timing_agent(*, repository: str, config: AppConfig, report: bool = False) -> dict[str, Any]:
    github = GitHubClient(repository)
    github.ensure_labels()
    control = _get_or_create_control_issue(github, config)
    data = _read_timing_data(control.body)
    samples_by_key = {
        (str(item["asset_id"]), int(item["window_hours"])): item
        for item in data.get("samples", [])
    }
    analytics = YouTubeAnalyticsClient()
    now = datetime.now(timezone.utc)
    scheduled_issues = github.list_issues(state="closed", labels=["talkivana", "pack-scheduled"])
    for issue in scheduled_issues:
        manifest = read_upload_manifest(issue.body)
        for asset_id, asset in manifest.get("assets", {}).items():
            scheduled_text = str(asset.get("scheduled_at", ""))
            if not scheduled_text:
                continue
            published = datetime.fromisoformat(scheduled_text.replace("Z", "+00:00"))
            for hours in config.raw["timing_agent"]["evaluation_windows_hours"]:
                hours = int(hours)
                key = (asset_id + ":" + str(asset.get("video_id", "")), hours)
                if key in samples_by_key or now < published + timedelta(hours=hours + 6):
                    continue
                end = min(now.date() - timedelta(days=1), (published + timedelta(hours=hours)).date())
                metrics = analytics.video_metrics(
                    video_id=str(asset["video_id"]),
                    start_date=published.date(),
                    end_date=end,
                )
                if not metrics:
                    continue
                sample = {
                    "asset_id": key[0],
                    "window_hours": hours,
                    "format": str(asset["kind"]),
                    "slot_local": str(asset.get("slot_local", "")),
                    "published_at": published.isoformat(),
                    "views": int(metrics.get("views", 0)),
                    "average_percentage_viewed": float(metrics.get("averageViewPercentage", 0)),
                    "subscribers_gained": int(metrics.get("subscribersGained", 0)),
                }
                samples_by_key[key] = sample
    data["samples"] = list(samples_by_key.values())
    data["last_collected_at"] = now.isoformat()

    performance = _performance_samples(data["samples"])
    launch = _launch_date(config, performance)
    timing = config.raw["timing_agent"]
    plan = build_timing_plan(
        launch_date=launch,
        on_date=now.date(),
        slots=list(config.raw["youtube"]["seed_publish_slots_local"]),
        samples=performance,
        stage_1_days=int(timing["stage_1_days"]),
        stage_2_days=int(timing["stage_2_days"]),
        stage_2_exploration_ratio=float(timing["stage_2_exploration_ratio"]),
        stage_3_exploration_ratio=float(timing["stage_3_exploration_ratio"]),
        minimum_samples=int(timing["minimum_samples_per_format_slot"]),
    )
    data["current_plan"] = {
        "stage": plan.stage,
        "day_number": plan.day_number,
        "exploration_ratio": plan.exploration_ratio,
        "assignments": list(plan.assignments),
        "scores": [asdict(score) for score in plan.scores],
        "explanation": plan.explanation,
    }
    updated = _format_control_body(data)
    github.update_issue(control.number, body=updated)
    if report:
        github.comment(control.number, _format_weekly_report(data))
    return data


def current_timing_assignments(github: GitHubClient) -> tuple[dict[str, str], str] | None:
    """Return the latest persisted timing-agent decision without making an analytics call."""
    for issue in github.list_issues(state="open", labels=["timing-agent"]):
        if issue.title != TIMING_ISSUE_TITLE:
            continue
        plan = _read_timing_data(issue.body).get("current_plan", {})
        assignments = {
            str(asset): str(slot) for asset, slot in plan.get("assignments", [])
        }
        if set(assignments) == {"short-1", "short-2", "long-1", "long-2"}:
            return assignments, str(plan.get("explanation", "Persisted timing-agent plan."))
    return None


def _launch_date(config: AppConfig, samples: list[PerformanceSample]) -> date:
    configured = str(config.raw["timing_agent"].get("launch_date", "")).strip()
    if configured:
        return date.fromisoformat(configured)
    if samples:
        return min(sample.published_at.date() for sample in samples)
    return date.today()


def _performance_samples(rows: list[dict[str, Any]]) -> list[PerformanceSample]:
    grouped: dict[str, dict[int, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["asset_id"]), {})[int(row["window_hours"])] = row
    result: list[PerformanceSample] = []
    for asset_id, windows in grouped.items():
        base = windows.get(24) or next(iter(windows.values()))
        week = windows.get(168, base)
        result.append(
            PerformanceSample(
                asset_id=asset_id,
                format=str(base["format"]),
                slot_local=str(base["slot_local"]),
                published_at=datetime.fromisoformat(str(base["published_at"]).replace("Z", "+00:00")),
                views_24h=int(base["views"]),
                views_7d=int(week["views"]),
                average_percentage_viewed=float(week["average_percentage_viewed"]),
                subscribers_gained=int(week["subscribers_gained"]),
            )
        )
    return result


def _get_or_create_control_issue(github: GitHubClient, config: AppConfig) -> Issue:
    for issue in github.list_issues(state="open", labels=["timing-agent"]):
        if issue.title == TIMING_ISSUE_TITLE:
            return issue
    return github.create_issue(
        title=TIMING_ISSUE_TITLE,
        body=_format_control_body({"samples": [], "status": "waiting for published-video data"}),
        labels=["talkivana", "timing-agent"],
        assignee=config.approver_login,
    )


def _read_timing_data(body: str) -> dict[str, Any]:
    match = re.search(
        re.escape(TIMING_DATA_START) + r"\s*(.*?)\s*" + re.escape(TIMING_DATA_END),
        body,
        flags=re.DOTALL,
    )
    if not match:
        return {"samples": []}
    value = json.loads(match.group(1))
    return value if isinstance(value, dict) else {"samples": []}


def _format_control_body(data: dict[str, Any]) -> str:
    plan = data.get("current_plan", {})
    assignments = "\n".join(
        f"- {asset}: {slot} IST" for asset, slot in plan.get("assignments", [])
    ) or "- Waiting for the first run"
    scores = "\n".join(
        f"| {item['format']} | {item['slot_local']} | {item['sample_count']} | "
        f"{item['score']:.2f} | {item['confidence']} |"
        for item in plan.get("scores", [])
    ) or "| — | — | 0 | 0 | waiting |"
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return f"""# Talkivana Audience Timing Agent

This control page is updated automatically. The agent never publishes videos and cannot bypass
either approval gate.

**Current stage:** {plan.get('stage', 'waiting')}  
**Experiment day:** {plan.get('day_number', 'waiting')}  
**Exploration allocation:** {float(plan.get('exploration_ratio', 1)):.0%}  
**Last collection:** {data.get('last_collected_at', 'No published data yet')}

## Current four-slot assignment

{assignments}

## Evidence by format and slot

| Format | Slot (IST) | Samples | Score | Confidence |
| --- | --- | ---: | ---: | --- |
{scores}

## Policy

- Days 1–30: balanced experimentation.
- Days 31–60: 70% promising slots and 30% controlled exploration.
- Day 61 onward: 85% proven slots and 15% continued exploration.
- Shorts and long videos are scored independently.
- An isolated viral or anomalous upload must not determine the schedule.

{TIMING_DATA_START}
{encoded}
{TIMING_DATA_END}
"""


def _format_weekly_report(data: dict[str, Any]) -> str:
    plan = data.get("current_plan", {})
    assignments = ", ".join(
        f"{asset} → {slot} IST" for asset, slot in plan.get("assignments", [])
    )
    return (
        "## Weekly timing report\n\n"
        f"Stage {plan.get('stage', 'waiting')}, experiment day {plan.get('day_number', 'waiting')}. "
        f"{plan.get('explanation', 'Waiting for enough published data.')}\n\n"
        f"Recommended assignment: {assignments or 'not enough data yet'}.\n\n"
        "No publishing-time change bypasses content or final-video approval."
    )
