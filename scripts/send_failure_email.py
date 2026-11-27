#!/usr/bin/env python3
"""Send one concise SMTP email for a failed Talkivana GitHub Actions run."""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any


def _github_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "talkivana-failure-mailer",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _github_text(url: str, token: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "talkivana-failure-mailer",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_failure_reason(log_text: str) -> str:
    """Return the most useful final error without reproducing an entire Actions log."""
    candidates: list[tuple[int, str]] = []
    patterns = (
        (5, re.compile(r"::error::\s*(.+)", re.IGNORECASE)),
        (4, re.compile(r"\b(?:ERROR|Error):\s*(.+)")),
        (3, re.compile(r"(No files were found.+)", re.IGNORECASE)),
        (3, re.compile(r"(timed? out.+)", re.IGNORECASE)),
        (2, re.compile(r"(Process completed with exit code\s+\d+)", re.IGNORECASE)),
    )
    for raw_line in log_text.splitlines():
        line = re.sub(r"^\d{4}-\d{2}-\d{2}T[^ ]+\s+", "", raw_line).strip()
        for priority, pattern in patterns:
            match = pattern.search(line)
            if match:
                reason = " ".join(match.group(1).split())
                if reason and "##[error]" not in reason:
                    candidates.append((priority, reason[:900]))
    if not candidates:
        return "The job failed without a specific error annotation. Open the run logs for details."
    highest = max(priority for priority, _ in candidates)
    return next(reason for priority, reason in reversed(candidates) if priority == highest)


def failure_summary(repository: str, run_id: int, token: str) -> list[tuple[str, str]]:
    url = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
    payload = _github_json(url, token)
    failures: list[tuple[str, str]] = []
    for job in payload.get("jobs", []):
        if job.get("conclusion") not in {"failure", "timed_out", "cancelled"}:
            continue
        job_id = int(job["id"])
        reason = f"Job concluded with {job.get('conclusion')}."
        try:
            logs = _github_text(
                f"https://api.github.com/repos/{repository}/actions/jobs/{job_id}/logs",
                token,
            )
            reason = extract_failure_reason(logs)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            pass
        failures.append((str(job.get("name") or f"job {job_id}"), reason))
    return failures


def send_email(
    *,
    smtp_username: str,
    smtp_password: str,
    recipient: str,
    workflow: str,
    repository: str,
    run_id: int,
    run_url: str,
    branch: str,
    attempt: str,
    failures: list[tuple[str, str]],
) -> None:
    message = EmailMessage()
    message["Subject"] = f"Talkivana automation failed: {workflow}"
    message["From"] = smtp_username
    message["To"] = recipient
    details = "\n\n".join(f"Failed job: {name}\nReason: {reason}" for name, reason in failures)
    if not details:
        details = "GitHub marked the workflow as failed, but no failed job details were available."
    message.set_content(
        "Talkivana stopped safely because an automation error occurred.\n"
        "No failed or partially verified video was made public.\n\n"
        f"Workflow: {workflow}\n"
        f"Repository: {repository}\n"
        f"Branch: {branch}\n"
        f"Attempt: {attempt}\n\n"
        f"{details}\n\n"
        f"Open the failed run: {run_url}\n"
    )
    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30
    ) as smtp:
        smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--branch", default="")
    parser.add_argument("--attempt", default="1")
    args = parser.parse_args()

    required = {
        "GH_TOKEN": os.environ.get("GH_TOKEN", "").strip(),
        "ALERT_SMTP_USERNAME": os.environ.get("ALERT_SMTP_USERNAME", "").strip(),
        "ALERT_SMTP_APP_PASSWORD": os.environ.get("ALERT_SMTP_APP_PASSWORD", "").strip(),
        "ALERT_EMAIL_TO": os.environ.get("ALERT_EMAIL_TO", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("Missing failure-email secrets: " + ", ".join(missing))

    failures = failure_summary(args.repository, args.run_id, required["GH_TOKEN"])
    send_email(
        smtp_username=required["ALERT_SMTP_USERNAME"],
        smtp_password=required["ALERT_SMTP_APP_PASSWORD"],
        recipient=required["ALERT_EMAIL_TO"],
        workflow=args.workflow,
        repository=args.repository,
        run_id=args.run_id,
        run_url=args.run_url,
        branch=args.branch,
        attempt=args.attempt,
        failures=failures,
    )
    print(f"Failure email sent to {required['ALERT_EMAIL_TO']}.")


if __name__ == "__main__":
    main()
