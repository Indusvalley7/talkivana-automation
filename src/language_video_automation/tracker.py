from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .analytics import TIMING_ISSUE_TITLE, _read_timing_data
from .config import load_config
from .github_api import GitHubClient, Issue, parse_pack_record, read_upload_manifest
from .youtube import YouTubeUploader


TRACKER_FIELDS = (
    "s_no",
    "youtube_video_or_short_name",
    "content_description",
    "approved",
    "rejected",
    "review_status_reason",
    "publishing_date",
    "publishing_timezone",
    "successfully_published",
    "publication_status",
    "pack_id",
    "asset_id",
    "format",
    "publish_slot_local",
    "youtube_video_id",
    "youtube_url",
    "github_issue",
    "views_24h",
    "views_7d",
    "average_view_percentage_24h",
    "average_view_percentage_7d",
    "subscribers_gained_24h",
    "subscribers_gained_7d",
)


def sync_video_tracker(*, repository: str) -> dict[str, Any]:
    config = load_config(require_enabled=True)
    github = GitHubClient(repository)
    issues = github.list_issues(state="all", labels=["talkivana"])
    packs: list[tuple[Issue, Any, dict[str, Any]]] = []
    video_ids: list[str] = []
    for issue in issues:
        try:
            record = parse_pack_record(issue.body)
        except Exception:
            continue
        manifest = read_upload_manifest(issue.body)
        packs.append((issue, record, manifest))
        video_ids.extend(
            str(value.get("video_id", ""))
            for value in manifest.get("assets", {}).values()
            if value.get("video_id")
        )

    statuses = YouTubeUploader().publication_statuses(video_ids) if video_ids else {}
    metrics = _analytics_metrics(github)
    zone_name = str(config.raw["youtube"]["timezone"])
    zone = ZoneInfo(zone_name)
    rows: list[dict[str, str]] = []
    ordered_packs = sorted(packs, key=lambda item: (item[1].created_date, item[0].number))
    for issue, record, manifest in ordered_packs:
        content_by_id = {
            str(asset["asset_id"]): (kind, asset)
            for kind, collection in (
                ("short", record.content["shorts"]),
                ("long", record.content["long_videos"]),
            )
            for asset in collection
        }
        comments = github.list_comments(issue.number)
        approved, rejected, reason = _review_state(
            issue,
            comments,
            approver_login=config.approver_login,
        )
        for asset_id in ("short-1", "short-2", "long-1", "long-2"):
            kind, content = content_by_id[asset_id]
            asset = dict(manifest.get("assets", {}).get(asset_id, {}))
            video_id = str(asset.get("video_id", ""))
            status = statuses.get(video_id, {})
            privacy = str(status.get("privacy_status", "not uploaded"))
            upload_status = str(status.get("upload_status", ""))
            successfully_published = "Yes" if privacy == "public" else "No"
            publishing_date = _local_publish_date(str(asset.get("scheduled_at", "")), zone)
            label = "Short" if kind == "short" else "Video"
            number = asset_id.rsplit("-", 1)[-1]
            metric = metrics.get(video_id, {})
            rows.append({
                "s_no": str(len(rows) + 1),
                "youtube_video_or_short_name": f"{label} {number}: {content['title']}",
                "content_description": str(content["description"]),
                "approved": approved,
                "rejected": rejected,
                "review_status_reason": reason,
                "publishing_date": publishing_date,
                "publishing_timezone": zone_name,
                "successfully_published": successfully_published,
                "publication_status": _publication_label(privacy, upload_status, publishing_date),
                "pack_id": record.pack_id,
                "asset_id": asset_id,
                "format": kind,
                "publish_slot_local": str(asset.get("slot_local", "")),
                "youtube_video_id": video_id,
                "youtube_url": str(asset.get("url", "")),
                "github_issue": f"https://github.com/{repository}/issues/{issue.number}",
                "views_24h": str(metric.get("views_24h", "")),
                "views_7d": str(metric.get("views_7d", "")),
                "average_view_percentage_24h": str(
                    metric.get("average_view_percentage_24h", "")
                ),
                "average_view_percentage_7d": str(
                    metric.get("average_view_percentage_7d", "")
                ),
                "subscribers_gained_24h": str(metric.get("subscribers_gained_24h", "")),
                "subscribers_gained_7d": str(metric.get("subscribers_gained_7d", "")),
            })

    csv_text = _render_csv(rows)
    markdown_text = _render_markdown(rows[-100:], total_rows=len(rows))
    changed_csv = github.upsert_file(
        path="tracker/video_tracker.csv",
        text=csv_text,
        message="Update Talkivana video tracker",
    )
    changed_markdown = github.upsert_file(
        path="tracker/video_tracker.md",
        text=markdown_text,
        message="Update Talkivana readable video tracker",
    )
    return {
        "rows": len(rows),
        "csv_updated": changed_csv,
        "markdown_updated": changed_markdown,
    }


def _review_state(
    issue: Issue,
    comments: list[dict[str, Any]],
    *,
    approver_login: str,
) -> tuple[str, str, str]:
    latest_command = ""
    for comment in comments:
        if str(comment.get("user", {}).get("login", "")).casefold() != approver_login.casefold():
            continue
        body = str(comment.get("body", "")).strip()
        first = body.splitlines()[0].strip().upper() if body else ""
        if first.startswith(("APPROVE", "REJECT", "REVISE", "RETRY")):
            latest_command = body
    detail = " ".join(line.strip() for line in latest_command.splitlines() if line.strip())
    labels = set(issue.labels)
    if "pack-scheduled" in labels:
        return "Yes", "No", "Final videos approved; publication scheduled."
    if "pack-rejected" in labels:
        return "No", "Yes", detail or "Rejected or superseded; see the linked GitHub Issue."
    if "pack-awaiting-video" in labels:
        suffix = f" Latest instruction: {detail}" if detail.startswith("RETRY") else ""
        return "No", "No", "Pending final video review." + suffix
    if "pack-producing" in labels:
        return "No", "No", "Content approved; production and technical review in progress."
    if "pack-awaiting-content" in labels:
        return "No", "No", "Pending content review."
    if "pack-setup-blocked" in labels or "pack-failed" in labels:
        return "No", "No", "Pending correction because automation is blocked or failed."
    if "pack-sample-approved" in labels:
        return "Yes", "No", "Controlled sample approved; not intended for publication."
    return "No", "No", "Status pending; see the linked GitHub Issue."


def _local_publish_date(value: str, zone: ZoneInfo) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(zone).isoformat(timespec="minutes")


def _publication_label(privacy: str, upload_status: str, publishing_date: str) -> str:
    if privacy == "public":
        return "Published publicly"
    if publishing_date:
        return "Scheduled; currently private"
    if privacy == "private":
        return "Uploaded privately; awaiting approval or scheduling"
    if upload_status:
        return f"{privacy}; upload status {upload_status}"
    return privacy


def _analytics_metrics(github: GitHubClient) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for issue in github.list_issues(state="open", labels=["timing-agent"]):
        if issue.title != TIMING_ISSUE_TITLE:
            continue
        data = _read_timing_data(issue.body)
        for sample in data.get("samples", []):
            key = str(sample.get("asset_id", ""))
            video_id = key.rsplit(":", 1)[-1] if ":" in key else ""
            if not video_id:
                continue
            window = int(sample.get("window_hours", 0))
            target = result.setdefault(video_id, {})
            if window == 24:
                target["views_24h"] = int(sample.get("views", 0))
                target["average_view_percentage_24h"] = float(
                    sample.get("average_percentage_viewed", 0)
                )
                target["subscribers_gained_24h"] = int(
                    sample.get("subscribers_gained", 0)
                )
            if window == 168:
                target["views_7d"] = int(sample.get("views", 0))
                target["average_view_percentage_7d"] = float(
                    sample.get("average_percentage_viewed", 0)
                )
                target["subscribers_gained_7d"] = int(
                    sample.get("subscribers_gained", 0)
                )
        break
    return result


def _render_csv(rows: list[dict[str, str]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=TRACKER_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _render_markdown(
    rows: list[dict[str, str]],
    *,
    total_rows: int | None = None,
) -> str:
    total = len(rows) if total_rows is None else total_rows
    range_note = (
        f"Showing the newest {len(rows)} of {total} records. "
        if total > len(rows)
        else f"Showing all {total} records. "
    )
    lines = [
        "# Talkivana video tracker",
        "",
        "This view is generated from approval Issues, YouTube status, and timing-agent data. "
        + range_note,
        "The CSV file in this folder contains the complete analysis-ready history.",
        "",
        "| No. | Video / Short | Approval | Reason | Publishing date | Published | YouTube |",
        "|---:|---|---|---|---|---|---|",
    ]
    for row in rows:
        approval = "Approved" if row["approved"] == "Yes" else (
            "Rejected" if row["rejected"] == "Yes" else "Pending"
        )
        title = row["youtube_video_or_short_name"].replace("|", "\\|")
        reason = row["review_status_reason"].replace("|", "\\|")
        link = f"[Open]({row['youtube_url']})" if row["youtube_url"] else "—"
        lines.append(
            f"| {row['s_no']} | {title} | {approval} | {reason} | "
            f"{row['publishing_date'] or '—'} | {row['successfully_published']} | {link} |"
        )
    lines.extend(["", "## Content descriptions", ""])
    for row in rows:
        description = row["content_description"].replace("\n", "  \n")
        lines.extend([
            f"### {row['s_no']}. {row['youtube_video_or_short_name']}",
            "",
            description,
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"
