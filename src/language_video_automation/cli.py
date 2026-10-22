from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .analytics import run_timing_agent
from .config import load_config
from .pipeline import (
    classify_event,
    cleanup_rejected_previews,
    create_daily_draft,
    process_approval_event,
    render_chatterbox_demo,
    render_demo,
    run_preflight,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Talkivana approval-gated video automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    draft = subparsers.add_parser("draft", help="Create today's four-asset content pack")
    draft.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    draft.add_argument("--force", action="store_true")

    approval = subparsers.add_parser("process-approval", help="Process one issue_comment event")
    approval.add_argument("--event", type=Path, default=Path(os.environ.get("GITHUB_EVENT_PATH", "event.json")))
    approval.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))

    classify = subparsers.add_parser("classify-event", help="Print the normalized approval command")
    classify.add_argument("--event", type=Path, default=Path(os.environ.get("GITHUB_EVENT_PATH", "event.json")))

    cleanup = subparsers.add_parser("cleanup-previews", help="Delete expired rejected private previews")
    cleanup.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))

    timing = subparsers.add_parser("timing-agent", help="Collect analytics and update the timing plan")
    timing.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    timing.add_argument("--report", action="store_true", help="Post the weekly human-readable report")

    preflight = subparsers.add_parser("preflight", help="Validate configuration and required tools")
    preflight.add_argument("--mode", choices=("local", "github"), default="local")

    demo = subparsers.add_parser("render-demo", help="Render a four-video sample pack with spoken local preview voices")
    demo.add_argument("--output", type=Path, default=Path("build/demo-v3"))
    demo.add_argument("--asset", choices=("short-1", "short-2", "long-1", "long-2"), default="")

    chatterbox_demo = subparsers.add_parser(
        "render-chatterbox-demo",
        help="Render exactly one sample with the pinned multilingual Chatterbox voice",
    )
    chatterbox_demo.add_argument("--output", type=Path, default=Path("build/chatterbox-sample"))
    chatterbox_demo.add_argument(
        "--asset", choices=("short-1", "short-2", "long-1", "long-2"), default="long-1"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "draft":
            _require_repo(args.repo)
            create_daily_draft(repository=args.repo, force=args.force)
        elif args.command == "process-approval":
            _require_repo(args.repo)
            process_approval_event(event_path=args.event, repository=args.repo)
        elif args.command == "classify-event":
            print(classify_event(args.event))
        elif args.command == "cleanup-previews":
            _require_repo(args.repo)
            print(f"Deleted {cleanup_rejected_previews(repository=args.repo)} expired private previews.")
        elif args.command == "timing-agent":
            _require_repo(args.repo)
            data = run_timing_agent(
                repository=args.repo,
                config=load_config(require_enabled=True),
                report=args.report,
            )
            print(json.dumps(data.get("current_plan", {}), indent=2, sort_keys=True))
        elif args.command == "preflight":
            problems = run_preflight(mode=args.mode)
            if problems:
                print("Preflight failed:", file=sys.stderr)
                for problem in problems:
                    print(f"- {problem}", file=sys.stderr)
                raise SystemExit(1)
            print("Preflight passed.")
        elif args.command == "render-demo":
            result = render_demo(output_dir=args.output, asset_id=args.asset)
            for asset in result.assets:
                print(f"{asset.asset_id}: {asset.video_path} ({asset.duration_seconds:.1f}s)")
            print(f"Unique speech requests: {result.unique_tts_requests}")
        elif args.command == "render-chatterbox-demo":
            result = render_chatterbox_demo(output_dir=args.output, asset_id=args.asset)
            asset = result.assets[0]
            print(f"{asset.asset_id}: {asset.video_path} ({asset.duration_seconds:.1f}s)")
            print(f"Unique speech requests: {result.unique_tts_requests}")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _require_repo(repository: str) -> None:
    if not repository:
        raise ValueError("--repo or GITHUB_REPOSITORY is required")
