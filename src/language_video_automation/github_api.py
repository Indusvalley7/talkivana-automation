from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .models import ContentPackRecord


class GitHubAPIError(RuntimeError):
    pass


LABELS: dict[str, tuple[str, str]] = {
    "talkivana": ("17233c", "Managed Talkivana automation"),
    "pack-awaiting-content": ("d99a2b", "Waiting for content approval"),
    "pack-producing": ("168c82", "Voice, visuals, and assembly in progress"),
    "pack-awaiting-video": ("f47764", "Waiting for final-video approval"),
    "pack-scheduled": ("0e8a16", "Approved and scheduled"),
    "pack-rejected": ("6e7781", "Rejected by the owner"),
    "pack-failed": ("b60205", "Automation failed closed"),
    "pack-setup-blocked": ("5319e7", "Configuration or credentials incomplete"),
    "timing-agent": ("665a9e", "Audience timing experiments and reports"),
}

PACK_START = "<!-- TALKIVANA_PACK_JSON_START"
PACK_END = "TALKIVANA_PACK_JSON_END -->"
UPLOADS_START = "<!-- TALKIVANA_UPLOADS_JSON_START"
UPLOADS_END = "TALKIVANA_UPLOADS_JSON_END -->"


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    state: str
    labels: tuple[str, ...]
    html_url: str
    created_at: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Issue":
        return cls(
            number=int(data["number"]),
            title=str(data.get("title", "")),
            body=str(data.get("body") or ""),
            state=str(data.get("state", "")),
            labels=tuple(str(label["name"]) for label in data.get("labels", [])),
            html_url=str(data.get("html_url", "")),
            created_at=str(data.get("created_at", "")),
        )


class GitHubClient:
    def __init__(self, repository: str, token: str | None = None) -> None:
        if "/" not in repository:
            raise GitHubAPIError("Repository must be in OWNER/NAME form.")
        self.repository = repository
        self.owner = repository.split("/", 1)[0]
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not self.token:
            raise GitHubAPIError("GITHUB_TOKEN or GH_TOKEN is missing.")
        self.base = f"https://api.github.com/repos/{repository}"

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        allow_404: bool = False,
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "talkivana-automation",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise GitHubAPIError(f"GitHub API {method} {path} failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise GitHubAPIError(f"GitHub API connection failed: {exc}") from exc

    def ensure_labels(self) -> None:
        for name, (color, description) in LABELS.items():
            encoded = urllib.parse.quote(name, safe="")
            if self._request("GET", f"/labels/{encoded}", allow_404=True) is None:
                self._request("POST", "/labels", {"name": name, "color": color, "description": description})

    def create_issue(self, *, title: str, body: str, labels: list[str], assignee: str) -> Issue:
        payload: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if assignee:
            payload["assignees"] = [assignee]
        return Issue.from_api(self._request("POST", "/issues", payload))

    def get_issue(self, number: int) -> Issue:
        return Issue.from_api(self._request("GET", f"/issues/{number}"))

    def list_issues(self, *, state: str = "all", labels: list[str] | None = None) -> list[Issue]:
        params = {"state": state, "per_page": "100", "sort": "created", "direction": "desc"}
        if labels:
            params["labels"] = ",".join(labels)
        data = self._request("GET", "/issues?" + urllib.parse.urlencode(params))
        return [Issue.from_api(item) for item in data if "pull_request" not in item]

    def comment(self, number: int, body: str) -> None:
        self._request("POST", f"/issues/{number}/comments", {"body": body})

    def update_issue(
        self,
        number: int,
        *,
        labels: list[str] | None = None,
        state: str | None = None,
        body: str | None = None,
    ) -> Issue:
        payload: dict[str, Any] = {}
        if labels is not None:
            payload["labels"] = labels
        if state is not None:
            payload["state"] = state
        if body is not None:
            payload["body"] = body
        return Issue.from_api(self._request("PATCH", f"/issues/{number}", payload))


def _format_vocab(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- **{item['english']}** → **{item['german']}** "
        f"({item['pronunciation']}; {item['part_of_speech']})"
        for item in items
    )


def _format_dialogue(turns: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{index}. **Speaker {turn['speaker']} — English:** {turn['english']}  \n"
        f"   **German:** {turn['german']}  \n"
        f"   **Pronunciation:** {turn['pronunciation']}"
        for index, turn in enumerate(turns, start=1)
    )


def format_issue_body(record: ContentPackRecord) -> str:
    pack = record.content
    sections: list[str] = []
    for short in pack["shorts"]:
        sections.append(
            f"### Short — {short['title']} (`{short['asset_id']}`)\n\n"
            f"Topic: {short['topic']}  \nLinked lesson: `{short['linked_long_asset_id']}`\n\n"
            f"{_format_vocab(short['vocabulary'])}\n\n"
            f"Description: {short['description']}"
        )
    for long_video in pack["long_videos"]:
        sections.append(
            f"### Five-minute lesson — {long_video['title']} (`{long_video['asset_id']}`)\n\n"
            f"Scenario: {long_video['scenario']}  \n"
            f"Objective: {long_video['learning_objective']}  \n"
            f"Vocabulary source: `{long_video['linked_short_asset_id']}`\n\n"
            f"{_format_dialogue(long_video['dialogue'])}\n\n"
            f"Description: {long_video['description']}"
        )
    qa_note = (
        "\n".join(f"- {problem}" for problem in record.qa_problems)
        if record.qa_problems
        else "- Automated Standard German review reported no corrections."
    )
    machine_json = json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True)
    sections_text = "\n\n".join(sections)
    return f"""## Content approval required

Reply with one command as the first non-empty line:

- `APPROVE CONTENT`
- `REVISE CONTENT: describe the correction`
- `REJECT: optional reason`

Approval generates four videos and uploads them **privately** for full review. It does not
schedule or publish anything.

**Pack:** {pack['pack_title']}  
**Language:** {pack['target_language']} — {pack['language_variety']}  
**Level:** {pack['level']}  
**Pack ID:** `{record.pack_id}`

{sections_text}

## Automated language review

{qa_note}

> Text in the teaching scenes is lesson material, not subtitle tracks. Closed captions and
> burned-in subtitles remain disabled.

{PACK_START}
{machine_json}
{PACK_END}
"""


def parse_pack_record(body: str) -> ContentPackRecord:
    match = re.search(
        re.escape(PACK_START) + r"\s*(.*?)\s*" + re.escape(PACK_END),
        body,
        flags=re.DOTALL,
    )
    if not match:
        raise GitHubAPIError("Issue does not contain a machine-readable Talkivana pack.")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GitHubAPIError("Issue pack record is invalid JSON.") from exc
    return ContentPackRecord.from_dict(data)


def read_upload_manifest(body: str) -> dict[str, Any]:
    match = re.search(
        re.escape(UPLOADS_START) + r"\s*(.*?)\s*" + re.escape(UPLOADS_END),
        body,
        flags=re.DOTALL,
    )
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GitHubAPIError("Upload manifest is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise GitHubAPIError("Upload manifest must be an object.")
    return value


def write_upload_manifest(body: str, manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    block = f"{UPLOADS_START}\n{encoded}\n{UPLOADS_END}"
    pattern = re.compile(
        re.escape(UPLOADS_START) + r".*?" + re.escape(UPLOADS_END),
        flags=re.DOTALL,
    )
    if pattern.search(body):
        return pattern.sub(block, body)
    return f"{body.rstrip()}\n\n{block}\n"
