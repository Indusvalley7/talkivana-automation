from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .analytics import YouTubeAnalyticsClient, current_timing_assignments
from .approvals import ApprovalCommand, Decision, is_authorized, parse_approval_command
from .config import AppConfig, ConfigurationError, load_config, project_root, validate_production_config
from .gemini import GeminiClient
from .generator import ContentPackGenerator
from .github_api import (
    GitHubClient,
    Issue,
    format_issue_body,
    parse_pack_record,
    read_upload_manifest,
    write_upload_manifest,
)
from .models import ContentPackRecord, validate_content_pack, validate_record_integrity
from .renderer import (
    AssetRenderResult,
    ChatterboxSpeechProvider,
    GeminiSpeechProvider,
    MacSpeechProvider,
    PackRenderResult,
    assemble_asset_stage,
    prepare_asset_visual_stage,
    prepare_asset_voice_stage,
    render_asset,
    render_pack,
)
from .scheduling import build_timing_plan, next_publish_time
from .thumbnails import DESIGN_VERSION, build_thumbnail_plan, render_youtube_thumbnail
from .youtube import YouTubeUploader


class PipelineError(RuntimeError):
    pass


def classify_event(event_path: Path) -> str:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    command = parse_approval_command(str(event.get("comment", {}).get("body", "")))
    return command.decision.value


def authorize_event(event_path: Path, repository: str) -> bool:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    sender = str(event.get("sender", {}).get("login", ""))
    config = load_config()
    return is_authorized(sender, config.approver_login, repository.split("/", 1)[0])


def create_daily_draft(*, repository: str, force: bool = False) -> Issue | None:
    config = load_config()
    if not config.enabled:
        print("Production lock is active: system.enabled is false. No content pack was generated.")
        return None
    validate_production_config(config)
    github = GitHubClient(repository)
    github.ensure_labels()
    issues = github.list_issues(state="all", labels=["talkivana"])
    history = _history_from_issues(issues)
    today = date.today()
    if not force and any(
        record.created_date == today.isoformat() and record.replacement_for is None
        for record in history
    ):
        print("A primary content pack already exists for today.")
        return None
    pending = [
        issue for issue in issues
        if issue.state == "open"
        and {
            "pack-awaiting-content", "pack-producing", "pack-awaiting-video",
            "pack-setup-blocked", "pack-failed",
        }.intersection(issue.labels)
    ]
    maximum = int(config.raw["system"]["max_pending_packs"])
    if len(pending) >= maximum and not force:
        print(f"Pending-pack guard reached ({len(pending)}/{maximum}); generation paused.")
        return None
    playlist = config.choose_playlist(today.toordinal())
    record = _generate_record(config=config, playlist=playlist, history=history, today=today)
    issue = _create_pack_issue(github, config, record)
    print(f"Created content approval Issue #{issue.number}: {issue.html_url}")
    return issue


def process_approval_event(*, event_path: Path, repository: str) -> None:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    command = parse_approval_command(str(event.get("comment", {}).get("body", "")))
    if command.decision is Decision.IGNORE:
        print("Comment is not a Talkivana command; ignoring.")
        return
    config = load_config()
    issue_number = int(event["issue"]["number"])
    sender = str(event.get("sender", {}).get("login", ""))
    github = GitHubClient(repository)
    github.ensure_labels()
    issue = github.get_issue(issue_number)
    if not is_authorized(sender, config.approver_login, repository.split("/", 1)[0]):
        github.comment(issue_number, f"Command ignored: `{sender}` is not the configured approver.")
        return
    if not config.enabled:
        github.comment(issue_number, "Production is disabled. No command was executed.")
        return
    validate_production_config(config)
    record = parse_pack_record(issue.body)
    _validate_record_again(record, config)

    if "pack-awaiting-content" in issue.labels:
        _process_content_stage(github, config, issue, record, command)
        return
    if "pack-awaiting-video" in issue.labels:
        _process_video_stage(github, config, issue, record, command)
        return
    print(f"Issue #{issue.number} is not at an approval gate; stale command ignored.")


def prepare_production_event(*, event_path: Path, repository: str, output_path: Path) -> None:
    """Authorize a rendering command and persist an immutable descriptor for downstream jobs."""
    event = json.loads(event_path.read_text(encoding="utf-8"))
    command = parse_approval_command(str(event.get("comment", {}).get("body", "")))
    allowed = {
        Decision.APPROVE_CONTENT,
        Decision.RETRY_VOICE,
        Decision.RETRY_SLIDES,
        Decision.RETRY_VIDEO,
    }
    if command.decision not in allowed:
        raise PipelineError(f"{command.decision.value} is not a production-render command.")
    config = load_config(require_enabled=True)
    validate_production_config(config)
    issue_number = int(event["issue"]["number"])
    sender = str(event.get("sender", {}).get("login", ""))
    github = GitHubClient(repository)
    github.ensure_labels()
    issue = github.get_issue(issue_number)
    if not is_authorized(sender, config.approver_login, repository.split("/", 1)[0]):
        raise PipelineError(f"{sender!r} is not the configured approver.")
    replace_existing = command.decision in {
        Decision.RETRY_VOICE,
        Decision.RETRY_SLIDES,
        Decision.RETRY_VIDEO,
    }
    expected_label = "pack-awaiting-video" if replace_existing else "pack-awaiting-content"
    if expected_label not in issue.labels:
        raise PipelineError(
            f"Issue #{issue.number} is not at the required {expected_label} approval gate."
        )
    missing = _missing_youtube_secrets()
    if missing:
        github.update_issue(
            issue.number,
            labels=["talkivana", "pack-setup-blocked", expected_label],
        )
        github.comment(
            issue.number,
            "Production is blocked by missing YouTube secrets: "
            + ", ".join(f"`{name}`" for name in missing)
            + ". Nothing was rendered or uploaded.",
        )
        raise PipelineError(f"Missing repository secrets: {', '.join(missing)}")
    record = parse_pack_record(issue.body)
    _validate_record_again(record, config)
    asset_ids = _production_asset_ids(config)
    github.update_issue(issue.number, labels=["talkivana", "pack-producing"])
    if replace_existing:
        github.comment(
            issue.number,
            f"{command.decision.value.replace('_', ' ').title()} accepted"
            + (f": {command.reason}" if command.reason else "")
            + f". {len(asset_ids)} voice worker(s) will rebuild the selected asset(s) before "
            "visuals, assembly, and QA.",
        )
    else:
        github.comment(
            issue.number,
            f"Content approved. Voice, visual, assembly, and technical-QA jobs have started for "
            f"{', '.join(asset_ids)}. "
            + (
                "Controlled dry-run output will remain a GitHub artifact and will not be uploaded."
                if len(asset_ids) == 1
                else "All YouTube uploads will remain private until final approval."
            ),
        )
    descriptor = {
        "schema_version": 1,
        "issue_number": issue.number,
        "repository": repository,
        "decision": command.decision.value,
        "replace_existing": replace_existing,
        "dry_run": len(asset_ids) == 1,
        "asset_ids": list(asset_ids),
        "record": record.as_dict(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(descriptor, indent=2, sort_keys=True), encoding="utf-8")


def run_production_voice_job(*, job_path: Path, asset_id: str, output_dir: Path) -> None:
    descriptor, record, config = _load_production_descriptor(job_path)
    if asset_id not in descriptor["asset_ids"]:
        raise PipelineError(f"Asset {asset_id!r} is outside this production descriptor.")
    kind, asset = _asset_with_kind(record, asset_id)
    settings = config.raw["models"]["tts_settings"]
    if bool(settings.get("automatic_voice_fallback", True)):
        raise PipelineError("Automatic voice fallback is forbidden.")
    speech = ChatterboxSpeechProvider(
        model_version=str(settings["model_version"]),
        device=str(settings.get("device", "auto")),
        seed=int(settings["seed"]),
        exaggeration=float(settings["exaggeration"]),
        cfg_weight=float(settings["cfg_weight"]),
        english_reference_audio=str(settings.get("english_reference_audio", "")),
        german_reference_audio=str(settings.get("german_reference_audio", "")),
        conversation_voice_references=dict(settings.get("conversation_voice_references", {})),
        require_distinct_conversation_voices=bool(
            settings.get("require_distinct_conversation_voices", True)
        ),
    )
    prepare_asset_voice_stage(
        record=record,
        asset=asset,
        kind=kind,
        config=config.raw,
        speech=speech,
        stage_dir=output_dir,
    )


def run_production_visual_job(*, stage_dir: Path) -> None:
    config = load_config(require_enabled=True)
    validate_production_config(config)
    prepare_asset_visual_stage(config=config.raw, stage_dir=stage_dir)


def run_production_assembly_job(*, stage_dir: Path) -> AssetRenderResult:
    config = load_config(require_enabled=True)
    validate_production_config(config)
    return assemble_asset_stage(config=config.raw, stage_dir=stage_dir)


def publish_production_previews(
    *, job_path: Path, rendered_root: Path, repository: str
) -> None:
    descriptor, record, config = _load_production_descriptor(job_path)
    issue_number = int(descriptor["issue_number"])
    if str(descriptor["repository"]) != repository:
        raise PipelineError("Production descriptor repository does not match the workflow repository.")
    github = GitHubClient(repository)
    issue = github.get_issue(issue_number)
    results: dict[str, tuple[AssetRenderResult, int]] = {}
    for result_path in rendered_root.rglob("asset-result.json"):
        data = json.loads(result_path.read_text(encoding="utf-8"))
        asset_id = str(data["asset_id"])
        result = AssetRenderResult(
            asset_id=asset_id,
            kind=str(data["kind"]),
            title=str(data["title"]),
            video_path=result_path.parent / str(data["video_file"]),
            preview_path=result_path.parent / str(data["preview_file"]),
            thumbnail_path=result_path.parent / str(data["thumbnail_file"]),
            duration_seconds=float(data["duration_seconds"]),
            segment_count=int(data["segment_count"]),
        )
        if asset_id in results:
            raise PipelineError(f"Duplicate assembled artifact for {asset_id}.")
        if (
            not result.video_path.is_file()
            or not result.preview_path.is_file()
            or not result.thumbnail_path.is_file()
        ):
            raise PipelineError(f"Assembled files are missing for {asset_id}.")
        results[asset_id] = (result, int(data.get("tts_request_count", 0)))
    expected_assets = set(descriptor["asset_ids"])
    if set(results) != expected_assets:
        raise PipelineError("The assembly jobs did not return the descriptor's validated assets.")
    total_requests = sum(value[1] for value in results.values())
    maximum = int(config.raw["system"]["max_tts_requests_per_pack"])
    if total_requests > maximum:
        raise PipelineError(f"TTS request guard exceeded ({total_requests}/{maximum}).")

    if bool(descriptor["dry_run"]):
        sample_asset_id = str(descriptor["asset_ids"][0])
        manifest = {
            "pack_id": record.pack_id,
            "assets": {},
            "dry_run": True,
            "sample_asset_id": sample_asset_id,
            "preview_workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
        }
        latest = github.get_issue(issue_number)
        github.update_issue(
            issue_number,
            body=write_upload_manifest(latest.body, manifest),
            labels=["talkivana", "pack-awaiting-video"],
        )
        run_url = f"https://github.com/{repository}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
        github.comment(
            issue_number,
            "## Controlled sample ready\n\n"
            f"Only `{sample_asset_id}` was rendered. Download the full-video artifact from "
            f"[{run_url}]({run_url}). Nothing was uploaded to YouTube.\n\n"
            "Reply with `APPROVE VIDEO` to accept this sample without scheduling anything, "
            "`RETRY VOICE: correction`, `RETRY VISUALS: correction`, "
            "`RETRY VIDEO: correction`, or `REJECT: reason`.",
        )
        return

    manifest = read_upload_manifest(issue.body)
    existing_assets = dict(manifest.get("assets", {}))
    uploader = YouTubeUploader()
    if bool(descriptor["replace_existing"]):
        for value in existing_assets.values():
            video_id = str(value.get("video_id", ""))
            if video_id:
                uploader.delete_private(video_id)
        existing_assets = {}
        manifest = {
            "pack_id": record.pack_id,
            "assets": {},
            "preview_workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
        }
        latest = github.get_issue(issue_number)
        github.update_issue(issue_number, body=write_upload_manifest(latest.body, manifest))

    youtube = config.raw["youtube"]
    asset_content = _assets_by_id(record)
    for asset_id in ("short-1", "short-2", "long-1", "long-2"):
        result = results[asset_id][0]
        content = asset_content[asset_id]
        if asset_id not in existing_assets:
            description = build_youtube_description(
                kind=result.kind,
                content=content,
                config=config,
                pack_id=record.pack_id,
                asset_id=asset_id,
            )
            tags = list(dict.fromkeys([*content.get("tags", []), *youtube.get("tags", [])]))
            uploaded = uploader.upload_private(
                video_path=result.video_path,
                title=str(content["title"]),
                description=description,
                tags=tags,
                category_id=str(youtube["category_id"]),
                default_language=str(youtube["default_language"]),
                made_for_kids=bool(youtube["made_for_kids"]),
                contains_synthetic_media=bool(youtube["contains_synthetic_media"]),
            )
            existing_assets[asset_id] = {
                "asset_id": asset_id,
                "kind": result.kind,
                "title": result.title,
                "video_id": uploaded.video_id,
                "url": uploaded.url,
                "duration_seconds": round(result.duration_seconds, 3),
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "thumbnail_status": "pending",
            }
            manifest = {
                "pack_id": record.pack_id,
                "assets": existing_assets,
                "preview_workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
            }
            latest = github.get_issue(issue_number)
            github.update_issue(issue_number, body=write_upload_manifest(latest.body, manifest))

        value = existing_assets[asset_id]
        if value.get("thumbnail_design_version") != DESIGN_VERSION:
            thumbnail_plan = build_thumbnail_plan(
                asset=content,
                kind=result.kind,
                pack_id=record.pack_id,
            )
            uploader.set_thumbnail(
                video_id=str(value["video_id"]),
                thumbnail_path=result.thumbnail_path,
            )
            value["thumbnail_status"] = "applied"
            value["thumbnail_design_version"] = DESIGN_VERSION
            value["thumbnail_palette"] = thumbnail_plan.palette_name
            value["thumbnail_headline"] = thumbnail_plan.headline
            value["thumbnail_updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest = {
            "pack_id": record.pack_id,
            "assets": existing_assets,
            "preview_workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
        }
        latest = github.get_issue(issue_number)
        github.update_issue(issue_number, body=write_upload_manifest(latest.body, manifest))

    github.update_issue(issue_number, labels=["talkivana", "pack-awaiting-video"])
    links = "\n".join(
        f"- **{asset_id} — {value['title']}:** {value['url']}"
        for asset_id, value in sorted(existing_assets.items())
    )
    run_url = f"https://github.com/{repository}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    github.comment(
        issue_number,
        "## Final-video approval required\n\n"
        "Watch every full private video while signed into the Talkivana channel account:\n\n"
        f"{links}\n\n"
        f"Thirty-second convenience clips and generated thumbnails are attached to "
        f"[{run_url}]({run_url}) for three days.\n\n"
        "Reply with `APPROVE VIDEO`, `RETRY VOICE: correction`, "
        "`RETRY VISUALS: correction`, `RETRY VIDEO: correction`, or `REJECT: reason`.\n\n"
        "Nothing is scheduled or public yet.",
    )


def report_production_failure(*, event_path: Path, repository: str) -> None:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    issue_number = int(event["issue"]["number"])
    github = GitHubClient(repository)
    issue = github.get_issue(issue_number)
    labels = ["talkivana", "pack-failed"]
    if read_upload_manifest(issue.body).get("assets"):
        labels.append("pack-awaiting-video")
    else:
        labels.append("pack-awaiting-content")
    github.update_issue(issue_number, labels=labels)
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    github.comment(
        issue_number,
        f"Production failed closed. No video was made public. Inspect the failed job at {run_url}.",
    )


def _load_production_descriptor(
    job_path: Path,
) -> tuple[dict[str, Any], ContentPackRecord, AppConfig]:
    descriptor = json.loads(job_path.read_text(encoding="utf-8"))
    if int(descriptor.get("schema_version", 0)) != 1:
        raise PipelineError("Unsupported production-job descriptor.")
    record = ContentPackRecord.from_dict(dict(descriptor["record"]))
    config = load_config(require_enabled=True)
    validate_production_config(config)
    _validate_record_again(record, config)
    allowed = {"short-1", "short-2", "long-1", "long-2"}
    asset_ids = descriptor.get("asset_ids") or sorted(allowed)
    if not isinstance(asset_ids, list) or not asset_ids or not set(asset_ids) <= allowed:
        raise PipelineError("Production descriptor contains invalid asset IDs.")
    descriptor["asset_ids"] = [str(item) for item in asset_ids]
    descriptor["dry_run"] = bool(descriptor.get("dry_run", len(asset_ids) == 1))
    return descriptor, record, config


def _production_asset_ids(config: AppConfig) -> tuple[str, ...]:
    dry_run_asset = str(config.raw["system"].get("dry_run_asset_id", "")).strip()
    if dry_run_asset:
        return (dry_run_asset,)
    return ("short-1", "short-2", "long-1", "long-2")


def _asset_with_kind(
    record: ContentPackRecord, asset_id: str
) -> tuple[str, dict[str, Any]]:
    for kind, collection in (
        ("short", record.content["shorts"]),
        ("long", record.content["long_videos"]),
    ):
        for asset in collection:
            if str(asset["asset_id"]) == asset_id:
                return kind, asset
    raise PipelineError(f"Unknown production asset: {asset_id}")


def _process_content_stage(
    github: GitHubClient,
    config: AppConfig,
    issue: Issue,
    record: ContentPackRecord,
    command: ApprovalCommand,
) -> None:
    if command.decision is Decision.REVISE_CONTENT:
        _revise_content(github, config, issue, record, command.reason)
    elif command.decision is Decision.REJECT:
        github.update_issue(issue.number, labels=["talkivana", "pack-rejected"], state="closed")
        github.comment(issue.number, "Content pack rejected. Nothing was rendered or uploaded.")
    elif command.decision is Decision.APPROVE_CONTENT:
        _produce_private_previews(github, config, issue, record, replace_existing=False)
    else:
        github.comment(issue.number, "That command is not valid at the content-approval stage.")


def _process_video_stage(
    github: GitHubClient,
    config: AppConfig,
    issue: Issue,
    record: ContentPackRecord,
    command: ApprovalCommand,
) -> None:
    if command.decision is Decision.APPROVE_VIDEO:
        manifest = read_upload_manifest(issue.body)
        if bool(manifest.get("dry_run")):
            github.update_issue(
                issue.number,
                labels=["talkivana", "pack-sample-approved"],
                state="closed",
            )
            github.comment(
                issue.number,
                "Controlled sample approved. No YouTube upload was created and nothing was scheduled. "
                "Daily schedules remain disabled.",
            )
        else:
            _schedule_approved_pack(github, config, issue, record)
    elif command.decision in {Decision.RETRY_VOICE, Decision.RETRY_SLIDES, Decision.RETRY_VIDEO}:
        # A complete deterministic rerender prevents a corrected component from becoming
        # desynchronised with the approved audio/visual timeline.
        github.comment(
            issue.number,
            f"{command.decision.value.replace('_', ' ').title()} accepted"
            + (f": {command.reason}" if command.reason else "")
            + ". The complete pack will be rebuilt so voice, visuals, and timing remain synchronized.",
        )
        _produce_private_previews(github, config, issue, record, replace_existing=True)
    elif command.decision is Decision.REJECT:
        manifest = read_upload_manifest(issue.body)
        manifest["rejected_at"] = datetime.now(timezone.utc).isoformat()
        github.update_issue(
            issue.number,
            body=write_upload_manifest(issue.body, manifest),
            labels=["talkivana", "pack-rejected"],
            state="closed",
        )
        days = int(config.raw["approval"]["rejected_preview_retention_days"])
        github.comment(
            issue.number,
            f"Final videos rejected. They remain private and will be deleted after {days} days.",
        )
    else:
        github.comment(issue.number, "That command is not valid at the final-video approval stage.")


def _generate_record(
    *,
    config: AppConfig,
    playlist,
    history: list[ContentPackRecord],
    revision: int = 1,
    replacement_for: int | None = None,
    revision_feedback: str = "",
    today: date | None = None,
) -> ContentPackRecord:
    client = GeminiClient(max_requests=int(config.raw["system"]["max_generation_requests_per_run"]))
    return ContentPackGenerator(config, client).create(
        playlist=playlist,
        history=history,
        revision=revision,
        replacement_for=replacement_for,
        revision_feedback=revision_feedback,
        today=today,
    )


def _create_pack_issue(github: GitHubClient, config: AppConfig, record: ContentPackRecord) -> Issue:
    return github.create_issue(
        title=f"Talkivana content approval: {record.content['pack_title']} [{record.pack_id}]"[:250],
        body=format_issue_body(record),
        labels=["talkivana", "pack-awaiting-content"],
        assignee=config.approver_login,
    )


def _revise_content(
    github: GitHubClient,
    config: AppConfig,
    issue: Issue,
    record: ContentPackRecord,
    reason: str,
) -> None:
    if not reason:
        github.comment(issue.number, "Use `REVISE CONTENT: describe the correction`.")
        return
    github.update_issue(issue.number, labels=["talkivana", "pack-rejected"], state="closed")
    github.comment(issue.number, f"Revision requested: {reason}\n\nNothing was rendered or uploaded.")
    try:
        history = _history_from_issues(github.list_issues(state="all", labels=["talkivana"]))
        playlist = _playlist_for_record(config, record)
        replacement = _generate_record(
            config=config,
            playlist=playlist,
            history=history,
            revision=record.revision + 1,
            replacement_for=issue.number,
            revision_feedback=reason,
            today=date.fromisoformat(record.created_date),
        )
        new_issue = _create_pack_issue(github, config, replacement)
        github.comment(issue.number, f"Replacement content pack: #{new_issue.number}")
    except Exception as exc:
        github.update_issue(issue.number, labels=["talkivana", "pack-rejected", "pack-failed"])
        github.comment(issue.number, f"Revision generation failed closed: `{_safe_error(exc)}`")
        raise


def _produce_private_previews(
    github: GitHubClient,
    config: AppConfig,
    issue: Issue,
    record: ContentPackRecord,
    *,
    replace_existing: bool,
) -> None:
    missing = _missing_secrets()
    if missing:
        github.update_issue(issue.number, labels=["talkivana", "pack-setup-blocked"])
        github.comment(
            issue.number,
            "Content approval was accepted, but production is blocked by missing secrets: "
            + ", ".join(f"`{name}`" for name in missing)
            + ". Nothing was uploaded.",
        )
        raise PipelineError(f"Missing repository secrets: {', '.join(missing)}")
    github.update_issue(issue.number, labels=["talkivana", "pack-producing"])
    github.comment(
        issue.number,
        "Content approved. Voice preparation, visual scene preparation, assembly, and technical QA have started. "
        "All uploads will remain private.",
    )
    try:
        latest = github.get_issue(issue.number)
        manifest = read_upload_manifest(latest.body)
        existing_assets = dict(manifest.get("assets", {}))
        uploader = YouTubeUploader()
        tts_settings = config.raw["models"]["tts_settings"]
        if bool(tts_settings.get("automatic_voice_fallback", True)):
            raise PipelineError("Automatic voice fallback is forbidden.")
        rendered = render_pack(
            record=record,
            config=config.raw,
            speech=ChatterboxSpeechProvider(
                model_version=str(tts_settings["model_version"]),
                device=str(tts_settings.get("device", "auto")),
                seed=int(tts_settings["seed"]),
                exaggeration=float(tts_settings["exaggeration"]),
                cfg_weight=float(tts_settings["cfg_weight"]),
                english_reference_audio=str(tts_settings.get("english_reference_audio", "")),
                german_reference_audio=str(tts_settings.get("german_reference_audio", "")),
                conversation_voice_references=dict(
                    tts_settings.get("conversation_voice_references", {})
                ),
                require_distinct_conversation_voices=bool(
                    tts_settings.get("require_distinct_conversation_voices", True)
                ),
            ),
            output_dir=project_root() / "build" / "review" / str(issue.number),
        )
        if replace_existing:
            # Keep the old review copies available until the replacement render has passed
            # technical QA. Only then remove them and begin the new idempotent upload set.
            for value in existing_assets.values():
                video_id = str(value.get("video_id", ""))
                if video_id:
                    uploader.delete_private(video_id)
            existing_assets = {}
            manifest = {
                "pack_id": record.pack_id,
                "assets": {},
                "preview_workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
            }
            latest = github.get_issue(issue.number)
            github.update_issue(issue.number, body=write_upload_manifest(latest.body, manifest))
        youtube = config.raw["youtube"]
        asset_content = _assets_by_id(record)
        for result in rendered.assets:
            content = asset_content[result.asset_id]
            if result.asset_id not in existing_assets:
                description = build_youtube_description(
                    kind=result.kind,
                    content=content,
                    config=config,
                    pack_id=record.pack_id,
                    asset_id=result.asset_id,
                )
                tags = list(dict.fromkeys([*content.get("tags", []), *youtube.get("tags", [])]))
                uploaded = uploader.upload_private(
                    video_path=result.video_path,
                    title=str(content["title"]),
                    description=description,
                    tags=tags,
                    category_id=str(youtube["category_id"]),
                    default_language=str(youtube["default_language"]),
                    made_for_kids=bool(youtube["made_for_kids"]),
                    contains_synthetic_media=bool(youtube["contains_synthetic_media"]),
                )
                existing_assets[result.asset_id] = {
                    "asset_id": result.asset_id,
                    "kind": result.kind,
                    "title": result.title,
                    "video_id": uploaded.video_id,
                    "url": uploaded.url,
                    "duration_seconds": round(result.duration_seconds, 3),
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "thumbnail_status": "pending",
                }
                manifest = {
                    "pack_id": record.pack_id,
                    "assets": existing_assets,
                    "preview_workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
                }
                latest = github.get_issue(issue.number)
                github.update_issue(issue.number, body=write_upload_manifest(latest.body, manifest))

            value = existing_assets[result.asset_id]
            if value.get("thumbnail_design_version") != DESIGN_VERSION:
                thumbnail_plan = build_thumbnail_plan(
                    asset=content,
                    kind=result.kind,
                    pack_id=record.pack_id,
                )
                uploader.set_thumbnail(
                    video_id=str(value["video_id"]),
                    thumbnail_path=result.thumbnail_path,
                )
                value["thumbnail_status"] = "applied"
                value["thumbnail_design_version"] = DESIGN_VERSION
                value["thumbnail_palette"] = thumbnail_plan.palette_name
                value["thumbnail_headline"] = thumbnail_plan.headline
                value["thumbnail_updated_at"] = datetime.now(timezone.utc).isoformat()
            manifest = {
                "pack_id": record.pack_id,
                "assets": existing_assets,
                "preview_workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
            }
            latest = github.get_issue(issue.number)
            github.update_issue(issue.number, body=write_upload_manifest(latest.body, manifest))

        if set(existing_assets) != {"short-1", "short-2", "long-1", "long-2"}:
            raise PipelineError("Private upload manifest does not contain all four assets.")
        github.update_issue(issue.number, labels=["talkivana", "pack-awaiting-video"])
        links = "\n".join(
            f"- **{asset_id} — {value['title']}:** {value['url']}"
            for asset_id, value in sorted(existing_assets.items())
        )
        run_url = (
            f"https://github.com/{github.repository}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}"
            if os.environ.get("GITHUB_RUN_ID")
            else "the current Actions run"
        )
        github.comment(
            issue.number,
            "## Final-video approval required\n\n"
            "Watch every full private video while signed into the Talkivana channel account:\n\n"
            f"{links}\n\n"
            f"Thirty-second convenience clips and generated thumbnails are attached to "
            f"[{run_url}]({run_url}) as a short-lived artifact.\n\n"
            "Reply with one command:\n\n"
            "- `APPROVE VIDEO`\n"
            "- `RETRY VOICE: optional correction`\n"
            "- `RETRY VISUALS: optional correction`\n"
            "- `RETRY VIDEO: optional correction`\n"
            "- `REJECT: optional reason`\n\n"
            "Nothing is scheduled or public yet.",
        )
    except Exception as exc:
        latest = github.get_issue(issue.number)
        labels = ["talkivana", "pack-failed"]
        if read_upload_manifest(latest.body).get("assets"):
            labels.append("pack-awaiting-video")
        github.update_issue(issue.number, labels=labels)
        github.comment(issue.number, f"Production failed closed: `{_safe_error(exc)}`")
        raise


def _schedule_approved_pack(
    github: GitHubClient,
    config: AppConfig,
    issue: Issue,
    record: ContentPackRecord,
) -> None:
    manifest = read_upload_manifest(issue.body)
    assets = manifest.get("assets", {})
    if set(assets) != {"short-1", "short-2", "long-1", "long-2"}:
        raise PipelineError("Final approval cannot run without four private-video IDs.")
    launch_text = str(config.raw["timing_agent"].get("launch_date", "")).strip()
    launch = date.fromisoformat(launch_text) if launch_text else date.fromisoformat(record.created_date)
    on_date = date.today()
    timing = config.raw["timing_agent"]
    plan = build_timing_plan(
        launch_date=launch,
        on_date=on_date,
        slots=list(config.raw["youtube"]["seed_publish_slots_local"]),
        samples=[],
        stage_1_days=int(timing["stage_1_days"]),
        stage_2_days=int(timing["stage_2_days"]),
        stage_2_exploration_ratio=float(timing["stage_2_exploration_ratio"]),
        stage_3_exploration_ratio=float(timing["stage_3_exploration_ratio"]),
        minimum_samples=int(timing["minimum_samples_per_format_slot"]),
    )
    persisted = current_timing_assignments(github)
    if persisted:
        slot_by_asset, timing_explanation = persisted
    else:
        slot_by_asset = dict(plan.assignments)
        timing_explanation = plan.explanation
    short_date, long_date, actual_slots, publish_times = _build_earliest_pack_schedule(
        github=github,
        config=config,
        record=record,
        slot_by_asset=slot_by_asset,
    )
    uploader = YouTubeUploader()
    youtube = config.raw["youtube"]
    playlist = _playlist_for_record(config, record)
    scheduled_lines: list[str] = []
    for asset_id in ("short-1", "short-2", "long-1", "long-2"):
        value = assets[asset_id]
        if value.get("scheduled_at"):
            scheduled_lines.append(
                f"- {asset_id}: `{value['scheduled_at']}` — {value['url']} (already confirmed)"
            )
            continue
        publish_at = publish_times[asset_id]
        uploader.schedule_existing(
            video_id=str(value["video_id"]),
            publish_at=publish_at,
            made_for_kids=bool(youtube["made_for_kids"]),
            contains_synthetic_media=bool(youtube["contains_synthetic_media"]),
        )
        uploader.add_to_playlist(
            video_id=str(value["video_id"]),
            playlist_id=playlist.youtube_playlist_id,
        )
        value["scheduled_at"] = publish_at.isoformat()
        value["slot_local"] = actual_slots[asset_id]
        scheduled_lines.append(f"- {asset_id}: `{publish_at.isoformat()}` — {value['url']}")
        latest = github.get_issue(issue.number)
        manifest["assets"] = assets
        github.update_issue(issue.number, body=write_upload_manifest(latest.body, manifest))
    github.update_issue(issue.number, labels=["talkivana", "pack-scheduled"], state="closed")
    github.comment(
        issue.number,
        "## Approved and scheduled\n\n"
        + "\n".join(scheduled_lines)
        + f"\n\nTiming agent: {timing_explanation}\n"
        "The linked vocabulary Shorts are scheduled one day before their conversation lessons.",
    )


def cleanup_rejected_previews(*, repository: str) -> int:
    config = load_config(require_enabled=True)
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=int(config.raw["approval"]["rejected_preview_retention_days"])
    )
    github = GitHubClient(repository)
    uploader = YouTubeUploader()
    deleted = 0
    for issue in github.list_issues(state="closed", labels=["talkivana", "pack-rejected"]):
        manifest = read_upload_manifest(issue.body)
        rejected_at = str(manifest.get("rejected_at", ""))
        if not rejected_at or manifest.get("deleted_at"):
            continue
        when = datetime.fromisoformat(rejected_at.replace("Z", "+00:00"))
        if when > cutoff:
            continue
        for value in manifest.get("assets", {}).values():
            if value.get("video_id"):
                uploader.delete_private(str(value["video_id"]))
                deleted += 1
        manifest["deleted_at"] = datetime.now(timezone.utc).isoformat()
        github.update_issue(issue.number, body=write_upload_manifest(issue.body, manifest))
        github.comment(issue.number, "Expired rejected private previews were deleted automatically.")
    return deleted


def reschedule_pack_earliest(*, repository: str, issue_number: int) -> None:
    """Move one still-private scheduled pack to the earliest safe rolling dates."""
    config = load_config(require_enabled=True)
    github = GitHubClient(repository)
    issue = github.get_issue(issue_number)
    if "pack-scheduled" not in issue.labels:
        raise PipelineError(f"Issue #{issue_number} is not a scheduled Talkivana pack.")
    record = parse_pack_record(issue.body)
    _validate_record_again(record, config)
    manifest = read_upload_manifest(issue.body)
    assets = dict(manifest.get("assets", {}))
    expected = {"short-1", "short-2", "long-1", "long-2"}
    if set(assets) != expected:
        raise PipelineError("Rescheduling requires the complete four-video manifest.")
    slot_by_asset = {
        asset_id: str(assets[asset_id].get("slot_local", ""))
        for asset_id in expected
    }
    if any(not slot for slot in slot_by_asset.values()):
        raise PipelineError("Rescheduling requires the existing experimental slots.")

    short_date, long_date, actual_slots, publish_times = _build_earliest_pack_schedule(
        github=github,
        config=config,
        record=record,
        slot_by_asset=slot_by_asset,
        exclude_issue_number=issue_number,
    )
    uploader = YouTubeUploader()
    youtube = config.raw["youtube"]
    lines: list[str] = []
    zone = ZoneInfo(str(youtube["timezone"]))
    for asset_id in ("short-1", "short-2", "long-1", "long-2"):
        value = assets[asset_id]
        publish_at = publish_times[asset_id]
        uploader.schedule_existing(
            video_id=str(value["video_id"]),
            publish_at=publish_at,
            made_for_kids=bool(youtube["made_for_kids"]),
            contains_synthetic_media=bool(youtube["contains_synthetic_media"]),
        )
        value["scheduled_at"] = publish_at.isoformat()
        value["slot_local"] = actual_slots[asset_id]
        local_label = publish_at.astimezone(zone).strftime("%d %B %Y, %I:%M %p %Z")
        lines.append(f"- {asset_id}: **{local_label}** — {value['url']}")

    manifest["assets"] = assets
    latest = github.get_issue(issue_number)
    github.update_issue(
        issue_number,
        body=write_upload_manifest(latest.body, manifest),
    )
    github.comment(
        issue_number,
        "## Schedule moved to the earliest safe dates\n\n"
        + "\n".join(lines)
        + f"\n\nShorts lead their linked long lessons by {(long_date - short_date).days} day. "
        "All four experimental times remain different.",
    )


def build_youtube_description(
    *,
    kind: str,
    content: dict[str, Any],
    config: AppConfig,
    pack_id: str,
    asset_id: str,
) -> str:
    if kind == "long":
        heading = str(content["title"]).strip().rstrip(".")
        topic = heading.lower()
        template = str(config.raw["youtube"]["long_description_template"])
        return template.format(
            brand_bold=_visual_bold("Talkivana"),
            lesson_topic_bold=_visual_bold(topic),
            situation_bold=_visual_bold(topic),
            tagline_bold=_visual_bold("Talkivana — Real Conversations. Clear Language."),
        )
    return (
        f"{content['description']}\n\n{config.raw['channel']['description_footer']}\n"
        f"Pack ID: {pack_id}\nAsset ID: {asset_id}"
    )


def _visual_bold(value: str) -> str:
    """Use API-safe Unicode display characters because the Data API has no rich-text spans."""
    converted: list[str] = []
    for character in value:
        codepoint = ord(character)
        if ord("A") <= codepoint <= ord("Z"):
            converted.append(chr(0x1D5D4 + codepoint - ord("A")))
        elif ord("a") <= codepoint <= ord("z"):
            converted.append(chr(0x1D5EE + codepoint - ord("a")))
        elif ord("0") <= codepoint <= ord("9"):
            converted.append(chr(0x1D7EC + codepoint - ord("0")))
        else:
            converted.append(character)
    return "".join(converted)


def refresh_private_video_metadata(*, repository: str, issue_number: int) -> None:
    """Refresh long-video descriptions without rendering, uploading, or scheduling videos."""
    config = load_config(require_enabled=True)
    github = GitHubClient(repository)
    issue = github.get_issue(issue_number)
    if "pack-awaiting-video" not in issue.labels:
        raise PipelineError(
            f"Issue #{issue_number} is not waiting at the private-video approval gate."
        )
    record = parse_pack_record(issue.body)
    _validate_record_again(record, config)
    manifest = read_upload_manifest(issue.body)
    assets = dict(manifest.get("assets", {}))
    if set(assets) != {"short-1", "short-2", "long-1", "long-2"}:
        raise PipelineError("Metadata refresh requires the complete four-video private manifest.")

    content_by_id = _assets_by_id(record)
    uploader = YouTubeUploader()
    updated_at = datetime.now(timezone.utc).isoformat()
    updated_lines: list[str] = []
    for asset_id in ("long-1", "long-2"):
        value = assets[asset_id]
        description = build_youtube_description(
            kind="long",
            content=content_by_id[asset_id],
            config=config,
            pack_id=record.pack_id,
            asset_id=asset_id,
        )
        uploader.update_description(
            video_id=str(value["video_id"]),
            description=description,
        )
        value["description_updated_at"] = updated_at
        updated_lines.append(f"- {asset_id} — {value['title']}: {value['url']}")

    manifest["assets"] = assets
    latest = github.get_issue(issue_number)
    github.update_issue(
        issue_number,
        body=write_upload_manifest(latest.body, manifest),
    )
    github.comment(
        issue_number,
        "## Long-video descriptions updated\n\n"
        + "\n".join(updated_lines)
        + "\n\nOnly the descriptions changed. All four videos remain private and unscheduled. "
        "Review the descriptions, then reply with `APPROVE VIDEO` when the complete pack is ready.",
    )


def refresh_video_thumbnails(
    *, repository: str, output_dir: Path, issue_number: int | None = None
) -> dict[str, Any]:
    """Render and apply content-specific thumbnails without changing video metadata or status."""
    config = load_config(require_enabled=True)
    github = GitHubClient(repository)
    issues = (
        [github.get_issue(issue_number)]
        if issue_number is not None
        else github.list_issues(state="all", labels=["talkivana"])
    )
    candidates: list[tuple[Issue, ContentPackRecord, dict[str, Any]]] = []
    for issue in issues:
        manifest = read_upload_manifest(issue.body)
        if manifest.get("deleted_at") or not manifest.get("assets"):
            continue
        try:
            record = parse_pack_record(issue.body)
            _validate_record_again(record, config)
        except Exception:
            if issue_number is not None:
                raise
            continue
        candidates.append((issue, record, manifest))
    if not candidates:
        scope = f"issue #{issue_number}" if issue_number is not None else "the repository"
        raise PipelineError(f"No uploaded Talkivana videos were found in {scope}.")

    uploader = YouTubeUploader()
    maximum = int(config.raw["video"]["thumbnail"]["max_file_size_bytes"])
    applied = 0
    issue_numbers: list[int] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for issue, record, manifest in candidates:
        assets = dict(manifest.get("assets", {}))
        content_by_id = _assets_by_id(record)
        updated_lines: list[str] = []
        for asset_id in ("short-1", "short-2", "long-1", "long-2"):
            value = assets.get(asset_id)
            content = content_by_id.get(asset_id)
            if not isinstance(value, dict) or not content or not value.get("video_id"):
                continue
            kind = str(value.get("kind") or ("short" if asset_id.startswith("short") else "long"))
            thumbnail_path = output_dir / f"issue-{issue.number}" / f"{record.pack_id}-{asset_id}-thumbnail.jpg"
            plan = render_youtube_thumbnail(
                asset=content,
                kind=kind,
                pack_id=record.pack_id,
                output_path=thumbnail_path,
                root=project_root(),
                max_file_size_bytes=maximum,
            )
            uploader.set_thumbnail(
                video_id=str(value["video_id"]),
                thumbnail_path=thumbnail_path,
            )
            value["thumbnail_status"] = "applied"
            value["thumbnail_design_version"] = DESIGN_VERSION
            value["thumbnail_palette"] = plan.palette_name
            value["thumbnail_headline"] = plan.headline
            value["thumbnail_updated_at"] = datetime.now(timezone.utc).isoformat()
            updated_lines.append(
                f"- `{asset_id}` — **{plan.headline}** ({plan.palette_name}): {value.get('url', '')}"
            )
            applied += 1
            # Persist after every successful API call so a later failure can be retried without
            # losing the audit state for thumbnails that YouTube already accepted.
            manifest["assets"] = assets
            latest = github.get_issue(issue.number)
            github.update_issue(issue.number, body=write_upload_manifest(latest.body, manifest))
        if not updated_lines:
            continue
        github.comment(
            issue.number,
            "## Custom thumbnails applied\n\n"
            + "\n".join(updated_lines)
            + "\n\nOnly custom thumbnails changed. Titles, descriptions, visibility, publishing "
              "times, playlists, and audience settings were left untouched.",
        )
        issue_numbers.append(issue.number)
    if applied == 0:
        raise PipelineError("No uploaded videos with usable content records were found.")
    return {"applied": applied, "issues": issue_numbers, "design_version": DESIGN_VERSION}


def _assets_by_id(record: ContentPackRecord) -> dict[str, dict[str, Any]]:
    return {
        str(asset["asset_id"]): asset
        for collection in (record.content["shorts"], record.content["long_videos"])
        for asset in collection
    }


def _next_available_short_date(
    github: GitHubClient,
    record: ContentPackRecord,
    buffer_days: int,
    *,
    exclude_issue_number: int | None = None,
    not_before: date | None = None,
    base_date: date | None = None,
) -> date:
    candidate = max(
        (base_date or date.today()) + timedelta(days=buffer_days),
        date.fromisoformat(record.created_date) + timedelta(days=buffer_days),
        not_before or date.min,
    )
    used: set[date] = set()
    for other in github.list_issues(state="closed", labels=["talkivana", "pack-scheduled"]):
        if other.number == exclude_issue_number:
            continue
        for asset_id, asset in read_upload_manifest(other.body).get("assets", {}).items():
            if not str(asset_id).startswith("short") or not asset.get("scheduled_at"):
                continue
            used.add(datetime.fromisoformat(str(asset["scheduled_at"]).replace("Z", "+00:00")).date())
    while candidate in used:
        candidate += timedelta(days=1)
    return candidate


def _reserved_slots_by_date(
    github: GitHubClient,
    *,
    exclude_issue_number: int | None = None,
) -> dict[date, set[str]]:
    reservations: dict[date, set[str]] = {}
    for other in github.list_issues(state="closed", labels=["talkivana", "pack-scheduled"]):
        if other.number == exclude_issue_number:
            continue
        for asset in read_upload_manifest(other.body).get("assets", {}).values():
            scheduled = str(asset.get("scheduled_at", ""))
            slot = str(asset.get("slot_local", ""))
            if not scheduled or not slot:
                continue
            day = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).date()
            reservations.setdefault(day, set()).add(slot)
    return reservations


def _build_earliest_pack_schedule(
    *,
    github: GitHubClient,
    config: AppConfig,
    record: ContentPackRecord,
    slot_by_asset: dict[str, str],
    exclude_issue_number: int | None = None,
    now: datetime | None = None,
) -> tuple[date, date, dict[str, str], dict[str, datetime]]:
    youtube = config.raw["youtube"]
    timezone_name = str(youtube["timezone"])
    zone = ZoneInfo(timezone_name)
    minimum_lead_hours = int(youtube["minimum_lead_hours"])
    buffer_days = int(config.raw["approval"]["rolling_buffer_days"])
    lead_days = int(config.raw["content"]["vocabulary_lead_days"])
    seed_slots = list(youtube["seed_publish_slots_local"])
    scheduling_now = now or datetime.now(timezone.utc)
    reservations = _reserved_slots_by_date(
        github,
        exclude_issue_number=exclude_issue_number,
    )
    candidate = _next_available_short_date(
        github,
        record,
        buffer_days,
        exclude_issue_number=exclude_issue_number,
        base_date=scheduling_now.astimezone(zone).date(),
    )

    for _attempt in range(370):
        short_date = candidate
        long_date = short_date + timedelta(days=lead_days)
        actual_slots: dict[str, str] = {}
        allocation_failed = False
        for target_date, asset_ids in (
            (short_date, ("short-1", "short-2")),
            (long_date, ("long-1", "long-2")),
        ):
            occupied = set(reservations.get(target_date, set()))
            for asset_id in asset_ids:
                preferred = slot_by_asset[asset_id]
                available = [slot for slot in seed_slots if slot not in occupied]
                if not available:
                    allocation_failed = True
                    break
                chosen = preferred if preferred in available else available[0]
                actual_slots[asset_id] = chosen
                occupied.add(chosen)
            if allocation_failed:
                break

        if not allocation_failed:
            publish_times: dict[str, datetime] = {}
            dates_match = True
            for asset_id in ("short-1", "short-2", "long-1", "long-2"):
                target_date = short_date if asset_id.startswith("short") else long_date
                publish_at = next_publish_time(
                    timezone_name=timezone_name,
                    local_time=actual_slots[asset_id],
                    minimum_lead_hours=minimum_lead_hours,
                    now=scheduling_now,
                    not_before_date=target_date,
                )
                publish_times[asset_id] = publish_at
                if publish_at.astimezone(zone).date() != target_date:
                    dates_match = False
            if dates_match:
                if actual_slots["long-1"] == actual_slots["long-2"]:
                    raise PipelineError("The two long videos must use different publishing times.")
                return short_date, long_date, actual_slots, publish_times

        candidate = _next_available_short_date(
            github,
            record,
            buffer_days,
            exclude_issue_number=exclude_issue_number,
            not_before=candidate + timedelta(days=1),
            base_date=scheduling_now.astimezone(zone).date(),
        )
    raise PipelineError("No safe Talkivana publishing dates were available within one year.")


def _playlist_for_record(config: AppConfig, record: ContentPackRecord):
    target = str(record.content["target_language"])
    try:
        return next(
            item for item in config.active_playlists
            if item.target_language.casefold() == target.casefold()
        )
    except StopIteration as exc:
        raise ConfigurationError(f"No enabled playlist matches {target!r}.") from exc


def _history_from_issues(issues: list[Issue]) -> list[ContentPackRecord]:
    records: list[ContentPackRecord] = []
    for issue in issues:
        try:
            records.append(parse_pack_record(issue.body))
        except Exception:
            continue
    return records


def _validate_record_again(record: ContentPackRecord, config: AppConfig) -> None:
    validate_record_integrity(record)
    playlist = _playlist_for_record(config, record)
    validate_content_pack(
        record.content,
        source_language=str(config.raw["channel"]["source_language"]),
        target_language=playlist.target_language,
        language_variety=playlist.variety,
        words_per_short=int(config.raw["content"]["words_per_short"]),
        dialogue_turns_per_long=int(config.raw["content"]["dialogue_turns_per_long"]),
    )


def _missing_secrets() -> list[str]:
    names = (
        "GEMINI_API_KEY", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
    )
    return [name for name in names if not os.environ.get(name)]


def _missing_youtube_secrets() -> list[str]:
    names = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    return [name for name in names if not os.environ.get(name)]


def _safe_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}".replace("`", "'")
    for name in (
        "GEMINI_API_KEY", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
    ):
        value = os.environ.get(name)
        if value:
            message = message.replace(value, "[REDACTED]")
    return " ".join(message.split())[:800]


def run_preflight(*, mode: str) -> list[str]:
    config = load_config()
    problems: list[str] = []
    try:
        validate_production_config(config)
    except ConfigurationError as exc:
        problems.append(str(exc))
    if mode == "local" and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
        problems.append("ffmpeg and ffprobe are required")
    if mode == "github":
        missing = _missing_secrets()
        problems.extend(f"missing secret: {name}" for name in missing)
        if not os.environ.get("GITHUB_TOKEN") and not os.environ.get("GH_TOKEN"):
            problems.append("missing GitHub Actions token")
        if not missing:
            try:
                playlist = config.active_playlists[0]
                identity = YouTubeUploader().validate_access(
                    expected_channel_name=str(config.raw["channel"]["name"]),
                    playlist_id=playlist.youtube_playlist_id,
                )
                print(
                    "YouTube access confirmed for "
                    f"{identity['channel_title']} / {identity['playlist_title']}."
                )
            except Exception as exc:
                problems.append(_safe_error(exc))
            try:
                YouTubeAnalyticsClient().validate_access()
                print("YouTube Analytics read access confirmed.")
            except Exception as exc:
                problems.append(_safe_error(exc))
    return problems


def render_demo(*, output_dir: Path, asset_id: str = "") -> PackRenderResult:
    fixture = project_root() / "tests" / "fixtures" / "sample_pack.json"
    record = ContentPackRecord.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
    config = load_config().raw
    speech = MacSpeechProvider()
    if asset_id:
        for kind, collection in (("short", record.content["shorts"]), ("long", record.content["long_videos"])):
            for asset in collection:
                if str(asset["asset_id"]) == asset_id:
                    cache: dict[str, tuple[Path, float]] = {}
                    result = render_asset(
                        record=record,
                        asset=asset,
                        kind=kind,
                        config=config,
                        speech=speech,
                        output_dir=output_dir / asset_id,
                        audio_cache=cache,
                    )
                    return PackRenderResult((result,), len(cache))
        raise PipelineError(f"Unknown demo asset: {asset_id}")
    return render_pack(
        record=record,
        config=config,
        speech=speech,
        output_dir=output_dir,
    )


def render_chatterbox_demo(*, output_dir: Path, asset_id: str = "long-1") -> PackRenderResult:
    fixture = project_root() / "tests" / "fixtures" / "sample_pack.json"
    record = ContentPackRecord.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
    config = load_config().raw
    settings = config["models"]["tts_settings"]
    speech = ChatterboxSpeechProvider(
        model_version=str(settings["model_version"]),
        device=str(settings.get("device", "auto")),
        seed=int(settings["seed"]),
        exaggeration=float(settings["exaggeration"]),
        cfg_weight=float(settings["cfg_weight"]),
        english_reference_audio=str(settings.get("english_reference_audio", "")),
        german_reference_audio=str(settings.get("german_reference_audio", "")),
        conversation_voice_references=dict(settings.get("conversation_voice_references", {})),
        require_distinct_conversation_voices=bool(
            settings.get("require_distinct_conversation_voices", True)
        ),
    )
    for kind, collection in (("short", record.content["shorts"]), ("long", record.content["long_videos"])):
        for asset in collection:
            if str(asset["asset_id"]) == asset_id:
                result = render_asset(
                    record=record,
                    asset=asset,
                    kind=kind,
                    config=config,
                    speech=speech,
                    output_dir=output_dir / asset_id,
                    audio_cache={},
                )
                return PackRenderResult((result,), speech.request_count)
    raise PipelineError(f"Unknown Chatterbox demo asset: {asset_id}")
