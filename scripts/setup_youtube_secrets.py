#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def set_secret(repository: str, name: str, value: str) -> None:
    result = subprocess.run(
        ["gh", "secret", "set", name, "--repo", repository],
        input=value,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not set {name}: {result.stderr.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize YouTube once and securely set GitHub secrets.")
    parser.add_argument("--client-secrets", required=True, type=Path)
    parser.add_argument("--repo", required=True, help="GitHub repository in OWNER/NAME form")
    args = parser.parse_args()
    if not args.client_secrets.is_file():
        raise SystemExit(f"Client-secret file not found: {args.client_secrets}")
    if "/" not in args.repo:
        raise SystemExit("--repo must use OWNER/NAME form")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise SystemExit("Install requirements.txt before running this helper.") from exc

    client_data = json.loads(args.client_secrets.read_text(encoding="utf-8"))
    section = client_data.get("installed") or client_data.get("web")
    if not section or not section.get("client_id") or not section.get("client_secret"):
        raise SystemExit("The supplied file is not a valid Google OAuth client-secret JSON file.")

    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secrets), scopes=SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise SystemExit("Google returned no refresh token. Revoke prior access and run the helper again.")

    set_secret(args.repo, "YOUTUBE_CLIENT_ID", section["client_id"])
    set_secret(args.repo, "YOUTUBE_CLIENT_SECRET", section["client_secret"])
    set_secret(args.repo, "YOUTUBE_REFRESH_TOKEN", credentials.refresh_token)
    print("YouTube OAuth secrets were added to the repository. Secret values were not displayed.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.SubprocessError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
